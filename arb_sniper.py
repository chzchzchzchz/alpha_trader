#!/usr/bin/env python3
"""
Arb sniper — fast poller over the tight-book watchlist. READ-ONLY.

PLACES NO ORDERS. It detects crossings, prices the full execution, and logs
them. Turning a detection into a trade is a human decision, made by a human.

Why this exists
---------------
arb_scanner.py sweeps all ~1.4M open markets, which takes ~7 minutes. A
two-leg book sitting at 98c does not stay crossed for 7 minutes -- when it
crosses it is gone in seconds. Discovery and execution need different speeds:

    arb_scanner.py  (slow, hourly)  -> finds which books run tight, writes
                                       logs/watchlist.json
    arb_sniper.py   (fast, seconds) -> polls only those, catches the crossing

That two-tier split is the whole point of the scanning architecture. A single
loop cannot be both exhaustive and fast.

What it checks, per event, per poll
-----------------------------------
  BUY-ALL   sum(yes_ask over every leg) + fees < 100c
            Requires the set to be collectively exhaustive -- exactly one leg
            must pay. Guarded the same way as the scanner: the bids must sum
            near 100c, or the set may resolve all-NO and the "arb" is a punt.

  SELL-ALL  sum(yes_bid over every leg) - fees > 100c
            Relies on mutual exclusivity only (at most one 100c payout), which
            is what Kalshi's flag actually guarantees. If nothing resolves YES
            you simply keep the credit, so this direction is safe against a
            non-exhaustive set.

Execution realism
-----------------
Fillable size is the MINIMUM depth across all legs, because a partial fill on
a subset is not an arbitrage -- it is naked directional risk. The reported
profit uses that minimum, never the best leg.

Usage:
    python3 arb_sniper.py                 # poll watchlist every 3s
    python3 arb_sniper.py --interval 1
    python3 arb_sniper.py --max-events 60
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from pathlib import Path

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SESSION = requests.Session()
HERE = Path(__file__).parent
WATCHLIST = HERE / "logs" / "watchlist.json"
HITLOG = HERE / "logs" / "arb_sniper_hits.jsonl"
TICKLOG = HERE / "logs" / "arb_sniper_ticks.jsonl"

EXHAUSTIVE_MIN_BID_SUM = 90   # cents; see module docstring


def fee(price_cents: int, contracts: int = 1) -> int:
    if price_cents <= 0:
        return 0
    p = price_cents / 100.0
    return max(1, math.ceil(0.07 * contracts * p * (1 - p) * 100))


def cents(v):
    if v is None:
        return None
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def size_of(m, field) -> float:
    try:
        return float(m.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def legs_for(event_ticker: str):
    """One request per event. Returns the event's live markets, or None."""
    try:
        r = SESSION.get(f"{BASE}/markets",
                        params={"event_ticker": event_ticker,
                                "status": "open", "limit": 200},
                        timeout=15)
        if r.status_code != 200:
            return None
        return r.json().get("markets", [])
    except requests.RequestException:
        return None


def evaluate(event_ticker: str, markets):
    """Return a list of crossing findings for this event, right now."""
    if not markets or len(markets) < 2:
        return []

    asks = [cents(m.get("yes_ask_dollars")) for m in markets]
    bids = [cents(m.get("yes_bid_dollars")) for m in markets]
    ask_sz = [size_of(m, "yes_ask_size_fp") for m in markets]
    bid_sz = [size_of(m, "yes_bid_size_fp") for m in markets]

    found = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    # ---- BUY ALL LEGS ----
    if all(a is not None and 0 < a < 100 for a in asks):
        bid_sum = sum(b for b in bids if b is not None)
        exhaustive = bid_sum >= EXHAUSTIVE_MIN_BID_SUM
        gross = 100 - sum(asks)
        net = gross - sum(fee(a) for a in asks)
        size = min(ask_sz)
        if net > 0 and exhaustive and size >= 1:
            found.append({
                "ts": now, "event": event_ticker, "side": "buy-all",
                "legs": len(markets), "sum_ask": sum(asks),
                "net_cents_per_set": net, "fillable_sets": int(size),
                "total_profit_cents": int(net * min(size, 10000)),
                "bid_sum": bid_sum,
                "tickers": [m["ticker"] for m in markets],
            })

    # ---- SELL ALL LEGS ----
    if all(b is not None and 0 < b < 100 for b in bids):
        credit = sum(bids)
        net = credit - 100 - sum(fee(b) for b in bids)
        size = min(bid_sz)
        if net > 0 and size >= 1:
            found.append({
                "ts": now, "event": event_ticker, "side": "sell-all",
                "legs": len(markets), "sum_bid": credit,
                "net_cents_per_set": net, "fillable_sets": int(size),
                "total_profit_cents": int(net * min(size, 10000)),
                "tickers": [m["ticker"] for m in markets],
            })

    return found


def closeness(markets):
    """How many cents from crossing, best of either direction (0 = crossed)."""
    if not markets or len(markets) < 2:
        return None
    asks = [cents(m.get("yes_ask_dollars")) for m in markets]
    bids = [cents(m.get("yes_bid_dollars")) for m in markets]
    best = None
    if all(a is not None and 0 < a < 100 for a in asks):
        n = 100 - sum(asks) - sum(fee(a) for a in asks)
        best = n if best is None else max(best, n)
    if all(b is not None and 0 < b < 100 for b in bids):
        n = sum(bids) - 100 - sum(fee(b) for b in bids)
        best = n if best is None else max(best, n)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--max-events", type=int, default=80,
                    help="poll only the N tightest books")
    args = ap.parse_args()

    if not WATCHLIST.exists():
        print(f"No watchlist at {WATCHLIST}. Run arb_scanner.py first.")
        return

    wl = json.loads(WATCHLIST.read_text())
    sets = wl.get("sets", [])
    sets.sort(key=lambda s: -s["net_cents"])
    events = []
    seen = set()
    for s in sets:
        if s["event"] not in seen:
            seen.add(s["event"])
            events.append(s["event"])
        if len(events) >= args.max_events:
            break

    print(f"watchlist generated {wl.get('generated','?')}")
    print(f"polling {len(events)} tightest events every {args.interval}s "
          f"(read-only, places no orders)\n", flush=True)

    HITLOG.parent.mkdir(exist_ok=True)
    polls = 0
    hits_total = 0
    best_seen = None
    t0 = time.time()

    try:
        while True:
            polls += 1
            round_best = None
            for et in events:
                ms = legs_for(et)
                if ms is None:
                    continue
                for f in evaluate(et, ms):
                    hits_total += 1
                    print(f"*** CROSSED {f['side']:9s} {f['event']:34s} "
                          f"+{f['net_cents_per_set']}c/set x{f['fillable_sets']} "
                          f"= +{f['total_profit_cents']}c", flush=True)
                    with HITLOG.open("a") as fh:
                        fh.write(json.dumps(f) + "\n")
                c = closeness(ms)
                if c is not None and (round_best is None or c > round_best[0]):
                    round_best = (c, et)

            if round_best:
                if best_seen is None or round_best[0] > best_seen[0]:
                    best_seen = round_best
                with TICKLOG.open("a") as fh:
                    fh.write(json.dumps({
                        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "best_net_cents": round_best[0],
                        "event": round_best[1]}) + "\n")

            if polls % 20 == 0:
                el = time.time() - t0
                print(f"  [{polls} polls, {el/60:.1f}min] crossings: {hits_total} | "
                      f"closest ever: {best_seen[0]:+d}c on {best_seen[1]}"
                      if best_seen else f"  [{polls} polls] no data", flush=True)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\nstopped. {polls} polls, {hits_total} crossings detected.")


if __name__ == "__main__":
    main()
