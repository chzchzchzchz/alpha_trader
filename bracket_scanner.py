#!/usr/bin/env python3
"""
BRACKET SCANNER — "Converging Singles" detector for Kalshi weather markets.

Thesis: Edge = finding where sum(bracket_YES_asks) < 1.0 across a series.
If you can buy all brackets at total cost < $1.00, one MUST resolve YES → free money.

Also implements:
  - VWAP deviation: |YES_ask + NO_ask - 1.0| > threshold
  - LMSR-aware probability (KL-distance metric, not Euclidean)
  - Modified Kelly sizing: f = (b*p - q) / b * sqrt(p)
  - Fill-rate tracker: tracks placed vs filled per session

Usage:
  python bracket_scanner.py                 # scan + report, no trades
  python bracket_scanner.py --execute       # actually trade on signals
  python bracket_scanner.py --min-edge 0.03 # custom edge threshold
"""
import os, sys, time, json, math, logging, argparse
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

import requests

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

# ── Config ──────────────────────────────────────────────────────────────────
KEY_ID = os.environ.get("KALSHI_API_KEY_ID")
PEM    = os.path.expanduser("~/.kalshi/private_key.pem")
BASE   = "https://api.elections.kalshi.com/trade-api/v2"

WEATHER_SERIES = [
    "KXHIGHNY", "KXLOWTPHIL", "KXLOWTLAX",
    "KXTEMPCHI", "KXTEMPDAL",  "KXTEMPMIA",
    "KXTEMPNYC", "KXTEMPHOUSTON",
]

# Thresholds (all in probability space, 0-1)
VWAP_DEVIATION_MIN    = 0.02   # |YES_ask + NO_ask - 1| must exceed this
MIN_BRACKET_EDGE      = 0.03   # bracket sum must be < (1 - this) to trade
MIN_PROFIT_PER_DOLLAR = 0.05   # RohOnChain's $0.05 per dollar rule
MAX_POSITION_FRAC     = 0.50   # never exceed 50% of thinner book side
KELLY_FRACTION        = 0.25   # fractional Kelly (conservative)
MAX_CONTRACTS         = 10     # hard cap per signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BRACKET] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("bracket")


# ── LMSR Math ────────────────────────────────────────────────────────────────

def lmsr_price_to_prob(price_cents: float) -> float:
    """
    In an LMSR market, prices ARE probabilities.
    But the information content of a move scales logarithmically, not linearly.
    This function returns the probability, noting that KL-distance (not Euclidean)
    is the correct distance metric between two market states.
    """
    return max(0.001, min(0.999, price_cents / 100.0))


def kl_divergence(p: float, q: float) -> float:
    """
    KL(P || Q) — measures information distance between two probability distributions.
    A move from 0.05→0.15 has higher KL than 0.50→0.60 (both +10¢ moves).
    This is why low-probability edges are informationally richer.
    """
    p = max(1e-9, min(1-1e-9, p))
    q = max(1e-9, min(1-1e-9, q))
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def modified_kelly(b: float, p: float, q: float) -> float:
    """
    f* = (b*p - q) / b * sqrt(p)
    where:
      b = net odds on a winning bet (payout / cost - 1)
      p = probability of winning (our estimate)
      q = 1 - p
    The sqrt(p) term is RohOnChain's modification for execution probability
    given book depth uncertainty.
    Returns fraction of bankroll to wager (0-1).
    """
    if b <= 0 or p <= 0:
        return 0.0
    raw_kelly = (b * p - q) / b
    execution_discount = math.sqrt(p)
    return max(0.0, min(0.5, raw_kelly * execution_discount * KELLY_FRACTION))


def vwap_deviation(yes_ask: float, no_ask: float) -> float:
    """
    |YES_ask + NO_ask - 1.0|
    In a perfectly efficient market this = 0 (no-arbitrage).
    When > 0.02, the market has structural deviation worth entering.
    """
    return abs(yes_ask + no_ask - 1.0)


# ── Market Fetcher ────────────────────────────────────────────────────────────

def fetch_series_markets(series: str) -> list[dict]:
    url = f"{BASE}/markets?series_ticker={series}&limit=200&status=open"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("markets", [])
    except Exception as e:
        log.warning(f"fetch {series}: {e}")
    return []


def fetch_orderbook(ticker: str) -> dict:
    url = f"{BASE}/markets/{ticker}/orderbook"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get("orderbook_fp", {})
    except:
        pass
    return {}


def extract_prices(mkt: dict) -> tuple[float | None, float | None]:
    """Returns (yes_ask_cents, no_ask_cents) or (None, None)."""
    yb = mkt.get("yes_bid_dollars")
    ya = mkt.get("yes_ask_dollars")
    if ya is None or yb is None:
        return None, None
    yes_ask = round(float(ya) * 100)
    no_ask  = 100 - round(float(yb) * 100)   # NO_ask = 100 - YES_bid
    return yes_ask, no_ask


# ── Bracket Group Analysis ────────────────────────────────────────────────────

def group_by_date(markets: list[dict]) -> dict[str, list[dict]]:
    """Group markets by (series, date) key to find bracket groups."""
    groups = defaultdict(list)
    for m in markets:
        ticker = m.get("ticker", "")
        parts = ticker.split("-")
        if len(parts) < 3:
            continue
        series_date = f"{parts[0]}-{parts[1]}"   # e.g. KXHIGHNY-26APR08
        groups[series_date].append(m)
    return dict(groups)


def analyze_bracket_group(series_date: str, markets: list[dict]) -> dict | None:
    """
    Check if sum(YES_asks) across all brackets in a series/date < 1.0.

    "Converging singles" logic:
      If you buy YES on EVERY bracket at current ask prices,
      exactly ONE must resolve YES (exhaustive, mutually exclusive).
      If total_cost < $1.00 → guaranteed profit = 1.00 - total_cost.

    Returns signal dict or None if no opportunity.
    """
    priced = []
    for m in markets:
        yes_ask, no_ask = extract_prices(m)
        if yes_ask is None:
            continue
        ticker = m.get("ticker", "")
        vol = float(m.get("volume_24h_fp", 0) or 0)
        priced.append({
            "ticker": ticker,
            "yes_ask_cents": yes_ask,
            "no_ask_cents": no_ask,
            "volume": vol,
            "market": m,
        })

    if len(priced) < 2:
        return None   # need at least 2 brackets to form a group

    total_yes_cost = sum(b["yes_ask_cents"] for b in priced)
    bracket_edge   = 100 - total_yes_cost   # cents of guaranteed profit

    signals = []

    # 1. Bracket arb: buy all YES when total < 100¢
    if bracket_edge > MIN_PROFIT_PER_DOLLAR * 100:
        signals.append({
            "type": "bracket_arb",
            "series_date": series_date,
            "brackets": len(priced),
            "total_yes_cost_cents": total_yes_cost,
            "guaranteed_profit_cents": bracket_edge,
            "roi": bracket_edge / total_yes_cost,
            "legs": priced,
        })

    # 2. Per-bracket VWAP deviation signals
    for b in priced:
        ya_frac   = b["yes_ask_cents"] / 100.0
        na_frac   = b["no_ask_cents"] / 100.0
        deviation = vwap_deviation(ya_frac, na_frac)

        if deviation > VWAP_DEVIATION_MIN:
            # Market has structural gap — determine which side is cheap
            if ya_frac + na_frac < 1.0:
                side = "buy_both"    # both cheap → buy both guaranteed profit
                profit = 1.0 - ya_frac - na_frac
            elif ya_frac > 0.5:
                side = "buy_no"      # YES overpriced → buy NO
                profit = na_frac - (1.0 - ya_frac)
            else:
                side = "buy_yes"
                profit = ya_frac - (1.0 - na_frac)

            signals.append({
                "type": "vwap_deviation",
                "ticker": b["ticker"],
                "deviation": deviation,
                "yes_ask": b["yes_ask_cents"],
                "no_ask": b["no_ask_cents"],
                "side": side,
                "profit_per_dollar": profit,
                "volume": b["volume"],
            })

    return signals if signals else None


# ── Fill Rate Tracker ─────────────────────────────────────────────────────────

class FillTracker:
    """Tracks placed vs filled orders to surface fill-rate problems."""

    def __init__(self):
        self.placed: dict[str, float] = {}   # order_id → placed_ts
        self.filled: set[str] = set()
        self.canceled: set[str] = set()

    def record_placed(self, order_id: str):
        self.placed[order_id] = time.time()

    def record_filled(self, order_id: str):
        self.filled.add(order_id)

    def record_canceled(self, order_id: str):
        self.canceled.add(order_id)

    def fill_rate(self) -> float:
        total = len(self.placed)
        if total == 0:
            return 0.0
        return len(self.filled) / total

    def stale_orders(self, max_age_seconds: int = 300) -> list[str]:
        """Orders placed > max_age seconds ago that haven't filled or canceled."""
        now = time.time()
        return [
            oid for oid, ts in self.placed.items()
            if oid not in self.filled
            and oid not in self.canceled
            and (now - ts) > max_age_seconds
        ]

    def report(self):
        log.info(f"Fill rate: {self.fill_rate():.1%} ({len(self.filled)}/{len(self.placed)} placed)")
        stale = self.stale_orders()
        if stale:
            log.warning(f"  {len(stale)} stale orders (unfilled >5min): {stale[:5]}")


# ── Signal Printer ────────────────────────────────────────────────────────────

def print_signal(sig: dict):
    if sig["type"] == "bracket_arb":
        log.info(
            f"  🔷 BRACKET ARB | {sig['series_date']} | "
            f"{sig['brackets']} brackets | total_cost={sig['total_yes_cost_cents']}¢ | "
            f"profit={sig['guaranteed_profit_cents']}¢ | ROI={sig['roi']:.1%}"
        )
        for leg in sig["legs"]:
            log.info(f"       └ {leg['ticker']}  YES_ask={leg['yes_ask_cents']}¢  vol={leg['volume']:.0f}")

    elif sig["type"] == "vwap_deviation":
        log.info(
            f"  🔶 VWAP DEV | {sig['ticker']} | "
            f"YES={sig['yes_ask']}¢ NO={sig['no_ask']}¢ | "
            f"dev={sig['deviation']:.3f} | side={sig['side']} | "
            f"profit/$ ={sig['profit_per_dollar']:.3f} | vol={sig['volume']:.0f}"
        )


# ── Main Scanner Loop ─────────────────────────────────────────────────────────

def run_scan(execute: bool = False, min_edge: float = MIN_BRACKET_EDGE):
    client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=False) if execute else None
    tracker = FillTracker()

    log.info(f"\n{'='*65}")
    log.info(f"BRACKET SCANNER — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"execute={execute}  min_edge={min_edge:.1%}  vwap_threshold={VWAP_DEVIATION_MIN}")
    log.info(f"{'='*65}")

    all_signals = []

    for series in WEATHER_SERIES:
        markets = fetch_series_markets(series)
        if not markets:
            continue

        groups = group_by_date(markets)
        log.info(f"\n{series}: {len(markets)} markets across {len(groups)} dates")

        for series_date, group_markets in sorted(groups.items()):
            signals = analyze_bracket_group(series_date, group_markets)
            if signals:
                for sig in signals:
                    print_signal(sig)
                    all_signals.append(sig)

    # Summary
    log.info(f"\n{'─'*65}")
    bracket_arbs  = [s for s in all_signals if s["type"] == "bracket_arb"]
    vwap_devs     = [s for s in all_signals if s["type"] == "vwap_deviation"]
    log.info(f"TOTAL: {len(bracket_arbs)} bracket arbs | {len(vwap_devs)} VWAP deviations")

    if bracket_arbs:
        best = max(bracket_arbs, key=lambda s: s["guaranteed_profit_cents"])
        log.info(f"BEST BRACKET ARB: {best['series_date']} → {best['guaranteed_profit_cents']}¢ profit")

    if vwap_devs:
        best_v = max(vwap_devs, key=lambda s: s["deviation"])
        log.info(
            f"BIGGEST VWAP DEV: {best_v['ticker']} → "
            f"deviation={best_v['deviation']:.3f} | side={best_v['side']}"
        )

    tracker.report()
    return all_signals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kalshi bracket integrity + VWAP scanner")
    parser.add_argument("--execute",  action="store_true", help="Place trades on signals")
    parser.add_argument("--loop",     type=int, default=0, help="Loop every N seconds (0=once)")
    parser.add_argument("--min-edge", type=float, default=MIN_BRACKET_EDGE)
    args = parser.parse_args()

    if args.loop > 0:
        while True:
            try:
                run_scan(execute=args.execute, min_edge=args.min_edge)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Scan error: {e}")
            log.info(f"Sleeping {args.loop}s...")
            time.sleep(args.loop)
    else:
        run_scan(execute=args.execute, min_edge=args.min_edge)
