#!/usr/bin/env python3
"""
Kalshi arbitrage scanner — READ-ONLY. Places no orders, ever.

Hunts three forms of *internal* inconsistency in the order book. None of them
require predicting anything, and none require an external data feed: the profit
is guaranteed by the structure of the contracts themselves.

  FORM A — bracket underpricing (mutually-exclusive event)
      Kalshi flags events as `mutually_exclusive`. In such an event exactly one
      market resolves YES and pays 100c. If you can buy YES on every market in
      the event for a combined cost under 100c (after fees), the payout is
      guaranteed to exceed the cost. Free money, whatever happens.

  FORM B — bracket overpricing (mutually-exclusive event)
      The mirror. If you can SELL YES on every market for a combined credit
      above 100c (after fees), you collect more than the 100c you can ever be
      required to pay out.

  FORM C — complementary pair (any single market)
      YES and NO on one market are complements: exactly one pays 100c. If
      yes_ask + no_ask < 100c after fees, buy both. If yes_bid + no_bid > 100c
      after fees, sell both.

Why scan the whole board rather than the weather series: there are ~41,000 open
markets. Inefficiency does not survive where people are watching; it survives in
thin, unloved corners. This is the "trade the bronze cards, not the meta" rule.

Usage:
    python3 arb_scanner.py                # one full pass
    python3 arb_scanner.py --watch        # repeat forever
    python3 arb_scanner.py --min-net 2    # only report >= 2c net edge
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SESSION = requests.Session()


def fee(price_cents: int, contracts: int = 1) -> int:
    """Kalshi taker fee: ceil(0.07 * C * P * (1-P)) dollars -> cents, min 1c."""
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


def depth_of(m, field) -> float:
    try:
        return float(m.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ fetching
class FetchIncomplete(Exception):
    """Raised when pagination could not complete. Never swallow this: a partial
    board silently scanned as if it were the whole board reports 'no arbitrage'
    with total confidence while never having looked."""


def iter_pages(path, key, params=None, page_pause=0.12):
    """
    Yield each page of an endpoint, retrying transient failures.

    Streaming rather than accumulating matters here: there are ~1.4 MILLION
    open markets. An earlier version capped the sweep at 80,000 and reported
    "no arbitrage" after examining 5.7% of the board -- a confident negative
    drawn from a truncated sample. Nothing here may silently stop early.
    """
    cursor, page = None, 0
    params = dict(params or {})
    while True:
        if cursor:
            params["cursor"] = cursor
        d = None
        for attempt in range(6):
            try:
                r = SESSION.get(f"{BASE}/{path}", params=params, timeout=45)
                if r.status_code == 200:
                    d = r.json()
                    break
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(min(2 ** attempt * 0.5, 12))
                    continue
                raise FetchIncomplete(
                    f"{path} page {page}: HTTP {r.status_code} {r.text[:120]}")
            except requests.RequestException:
                time.sleep(min(2 ** attempt * 0.5, 12))
        if d is None:
            raise FetchIncomplete(
                f"{path}: gave up on page {page} after retries")

        batch = d.get(key, [])
        if not batch:
            return
        yield page, batch
        cursor = d.get("cursor")
        page += 1
        if not cursor:
            return
        time.sleep(page_pause)


def fetch_all(path, key, params=None, cap=80000, page_pause=0.15):
    """
    Paginate an endpoint to exhaustion, retrying transient failures.

    The first version of this simply `break`-ed on any non-200 or exception.
    Because the markets sweep runs ~38 requests first, the events sweep was
    getting rate-limited on page 2 and returning 200 of several thousand
    events -- so the scan checked 33 mutually-exclusive events, found nothing,
    and printed "no arbitrage" as though it had covered the board.
    """
    out, cursor, page = [], None, 0
    params = dict(params or {})
    while len(out) < cap:
        if cursor:
            params["cursor"] = cursor
        d = None
        for attempt in range(6):
            try:
                r = SESSION.get(f"{BASE}/{path}", params=params, timeout=45)
                if r.status_code == 200:
                    d = r.json()
                    break
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(min(2 ** attempt * 0.5, 12))
                    continue
                raise FetchIncomplete(
                    f"{path} page {page}: HTTP {r.status_code} {r.text[:120]}")
            except requests.RequestException:
                time.sleep(min(2 ** attempt * 0.5, 12))
        if d is None:
            raise FetchIncomplete(
                f"{path}: gave up on page {page} after retries "
                f"({len(out)} records fetched so far)")

        batch = d.get(key, [])
        out.extend(batch)
        cursor = d.get("cursor")
        page += 1
        if not cursor or not batch:
            break
        time.sleep(page_pause)
    return out


# ------------------------------------------------------------------ the scan
def scan(min_net=1, verbose=True):
    """Full-board sweep. Streams markets so the whole 1.4M can be covered."""
    t0 = time.time()

    if verbose:
        print("fetching events (for mutually_exclusive flags) ...", flush=True)
    me = set()
    n_events = 0
    for page, batch in iter_pages("events", "events", {"limit": 200, "status": "open"}):
        n_events += len(batch)
        for e in batch:
            if e.get("mutually_exclusive"):
                me.add(e["event_ticker"])
    if verbose:
        print(f"  {n_events} events, {len(me)} mutually exclusive "
              f"({time.time()-t0:.0f}s)", flush=True)
        print("streaming markets ...", flush=True)

    hits = []
    near = []
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    n_markets = 0
    # Only markets belonging to mutually-exclusive events need to be held in
    # memory; everything else is checked for Form C and discarded immediately.
    legs = defaultdict(list)

    for page, batch in iter_pages("markets", "markets",
                                  {"limit": 1000, "status": "open"}):
        n_markets += len(batch)
        for m in batch:
            et = m.get("event_ticker")
            if et in me:
                legs[et].append({
                    "t": m.get("ticker"),
                    "ya": cents(m.get("yes_ask_dollars")),
                    "yb": cents(m.get("yes_bid_dollars")),
                    "da": depth_of(m, "yes_ask_size_fp"),
                    "db": depth_of(m, "yes_bid_size_fp"),
                    "v": float(m.get("volume_24h_fp") or 0),
                })

            # ---- FORM C: complementary pair ----
            ya, na = cents(m.get("yes_ask_dollars")), cents(m.get("no_ask_dollars"))
            yb, nb = cents(m.get("yes_bid_dollars")), cents(m.get("no_bid_dollars"))
            if ya and na and 0 < ya < 100 and 0 < na < 100:
                net = 100 - ya - na - fee(ya) - fee(na)
                if net >= min_net:
                    d = min(depth_of(m, "yes_ask_size_fp"),
                            depth_of(m, "no_ask_size_fp"))
                    if d >= 1:
                        hits.append({"ts": stamp, "form": "C-buy",
                                     "ticker": m["ticker"],
                                     "detail": f"yes_ask={ya} no_ask={na}",
                                     "net_cents": net, "depth": d,
                                     "volume": m.get("volume_24h_fp")})
            if yb and nb and 0 < yb < 100 and 0 < nb < 100:
                net = yb + nb - 100 - fee(yb) - fee(nb)
                if net >= min_net:
                    d = min(depth_of(m, "yes_bid_size_fp"),
                            depth_of(m, "no_bid_size_fp"))
                    if d >= 1:
                        hits.append({"ts": stamp, "form": "C-sell",
                                     "ticker": m["ticker"],
                                     "detail": f"yes_bid={yb} no_bid={nb}",
                                     "net_cents": net, "depth": d,
                                     "volume": m.get("volume_24h_fp")})
        if verbose and page % 200 == 0 and page:
            print(f"    {n_markets} markets ({time.time()-t0:.0f}s) "
                  f"{len(hits)} hits so far", flush=True)

    # ---- FORMS A/B over mutually-exclusive events ----
    complete_a = complete_b = 0
    for et, group in legs.items():
        if len(group) < 2:
            continue
        asks = [g["ya"] for g in group]
        bids = [g["yb"] for g in group]

        # EXHAUSTIVENESS GATE -- the correctness of Form A depends entirely on
        # this, and getting it wrong is how you lose the whole stake.
        #
        # Kalshi's `mutually_exclusive` flag means AT MOST one leg resolves YES.
        # It does NOT promise that at least one does. "Who will the next Pope
        # be?" lists 7 cardinals and is flagged mutually exclusive, but the
        # actual pope is probably none of them -- the market prices the entire
        # set at 29c precisely because ~71% of the probability sits on
        # "somebody not listed". Buying every leg for 29c is not arbitrage; it
        # is a 29c punt that expires worthless most of the time.
        #
        # Without an exhaustiveness flag in the API, use the market's own
        # opinion: for a set that really does partition the outcome space, the
        # bids must sum to near 100c. A set whose bids sum far below 100c is
        # one the market believes can all resolve NO. Requiring this is
        # conservative -- it rejects genuine arbs on wide books -- but the
        # alternative is confidently buying lottery tickets and calling them
        # risk-free.
        bid_sum = sum(b for b in bids if b is not None)
        exhaustive = bid_sum >= 90

        if exhaustive and all(a is not None and 0 < a < 100 for a in asks):
            complete_a += 1
            cost = sum(asks) + sum(fee(a) for a in asks)
            net = 100 - cost
            d = min(g["da"] for g in group)
            rec = {"ts": stamp, "form": "A-buy-all", "ticker": et,
                   "detail": f"{len(group)} legs, sum(ask)={sum(asks)}c",
                   "net_cents": net, "depth": d,
                   "volume": sum(g["v"] for g in group)}
            if net >= min_net and d >= 1:
                hits.append(rec)
            else:
                near.append((net, rec))

        # Form B (sell every leg) is the safe direction on exhaustiveness: if
        # no leg resolves YES you simply keep the whole credit. It relies on
        # MUTUAL EXCLUSIVITY instead -- at most one payout of 100c -- which is
        # exactly what Kalshi's flag does guarantee.
        if all(b is not None and 0 < b < 100 for b in bids):
            complete_b += 1
            credit = sum(bids) - sum(fee(b) for b in bids)
            net = credit - 100
            d = min(g["db"] for g in group)
            rec = {"ts": stamp, "form": "B-sell-all", "ticker": et,
                   "detail": f"{len(group)} legs, sum(bid)={sum(bids)}c",
                   "net_cents": net, "depth": d,
                   "volume": sum(g["v"] for g in group)}
            if net >= min_net and d >= 1:
                hits.append(rec)
            else:
                near.append((net, rec))

    hits.sort(key=lambda h: -h["net_cents"])
    near.sort(key=lambda x: -x[0])

    # Emit a WATCHLIST of the tightest books. A full sweep costs ~7 minutes,
    # far too slow to catch a crossing that lasts seconds. The fast poller
    # (arb_sniper.py) consumes this and polls only these events, so discovery
    # and execution run at the speeds each actually needs.
    watch = [
        {"event": rec["ticker"], "form": rec["form"], "net_cents": n,
         "legs": rec["detail"], "depth": rec["depth"], "volume": rec["volume"]}
        for n, rec in near if n >= -6
    ]
    wl = Path(__file__).parent / "logs" / "watchlist.json"
    wl.parent.mkdir(exist_ok=True)
    wl.write_text(json.dumps(
        {"generated": stamp, "count": len(watch), "sets": watch}, indent=1))

    cov = {"markets": n_markets, "events": n_events, "me_events": len(me),
           "me_with_markets": len(legs),
           "priceable_buy": complete_a, "priceable_sell": complete_b,
           "watchlist": len(watch),
           "seconds": round(time.time() - t0)}
    return hits, near, cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--min-net", type=int, default=1, help="min net cents")
    args = ap.parse_args()

    out = Path(__file__).parent / "logs" / "arb_hits.jsonl"
    out.parent.mkdir(exist_ok=True)

    while True:
        print("=" * 78, flush=True)
        print(f"ARB SCAN {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
              f"   (read-only, places no orders)", flush=True)
        print("=" * 78, flush=True)

        hits, near, cov = scan(min_net=args.min_net)

        print(f"\nCOVERAGE: {cov['markets']:,} markets | {cov['events']:,} events | "
              f"{cov['me_events']:,} mutually-exclusive "
              f"({cov['me_with_markets']:,} with live markets)", flush=True)
        print(f"          fully-priceable: {cov['priceable_buy']:,} buy-side, "
              f"{cov['priceable_sell']:,} sell-side  [{cov['seconds']}s]", flush=True)
        if hits:
            print(f"\n*** {len(hits)} ARBITRAGE(S) ***", flush=True)
            for h in hits[:25]:
                print(f"  [{h['form']:10s}] {h['ticker']:36s} "
                      f"net +{h['net_cents']}c  depth={h['depth']:.0f}  {h['detail']}",
                      flush=True)
            with out.open("a") as fh:
                for h in hits:
                    fh.write(json.dumps(h) + "\n")
            print(f"\nlogged to {out}", flush=True)
        else:
            print("\nno arbitrage this pass.", flush=True)

        # Always record the near-miss distribution. The decisive question is
        # not "is there an arb right now" but "how often does the book cross".
        nearlog = out.parent / "arb_nearmiss.jsonl"
        with nearlog.open("a") as fh:
            for n, rec in near[:40]:
                r = dict(rec); r["net_cents"] = n
                fh.write(json.dumps(r) + "\n")
            if near:
                print("closest misses (how far the book is from crossing):", flush=True)
                for n, rec in near[:8]:
                    print(f"   {rec['form']:10s} {rec['ticker']:34s} "
                          f"net {n:+d}c  {rec['detail']}", flush=True)

        if not args.watch:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
