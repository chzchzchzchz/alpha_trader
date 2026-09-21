#!/usr/bin/env python3
"""Kalshi Market Scanner (Unauthenticated) - Real market data, no trading."""
import os
import sys
import json
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests library required. pip install requests")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_markets_sample(status: str = "open", max_pages: int = 5) -> list:
    """Fetch a sample of markets (first N pages)."""
    markets = []
    cursor = ""
    for page in range(max_pages):
        url = f"{KALSHI_BASE}/markets?limit=200"
        if status:
            url += f"&status={status}"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                print(f"  Page {page+1} error: {r.status_code}")
                break
            data = r.json()
            page_markets = data.get("markets", [])
            markets.extend(page_markets)
            print(f"  Page {page+1}: {len(page_markets)} markets")
            cursor = data.get("cursor", "")
            if not cursor or not page_markets:
                break
            time.sleep(0.05)
        except Exception as e:
            print(f"  Fetch error page {page+1}: {e}")
            break
    return markets


def fetch_markets_by_series(series: str, status: str = "open") -> list:
    """Fetch markets for a specific series."""
    url = f"{KALSHI_BASE}/markets?series_ticker={series}&limit=200&status={status}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get("markets", [])
    except:
        pass
    return []


def fetch_orderbook(ticker: str) -> dict:
    """Fetch orderbook for a specific market."""
    url = f"{KALSHI_BASE}/markets/{ticker}/orderbook"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get("orderbook_fp", {})
    except:
        pass
    return {}


def analyze_market(mkt: dict) -> dict | None:
    """Analyze a single market for trading opportunities."""
    ticker = mkt.get("ticker", "")
    status = mkt.get("status", "")
    if status != "open":
        return None

    yes_bid_dollars = float(mkt.get("yes_bid_dollars", 0) or 0)
    yes_ask_dollars = float(mkt.get("yes_ask_dollars", 0) or 0)
    last_price = float(mkt.get("last_price_dollars", 0) or 0)
    volume_24h = float(mkt.get("volume_24h_fp", 0) or 0)

    # Skip markets with no liquidity
    if yes_bid_dollars == 0 and yes_ask_dollars == 0:
        return None

    # Yes bid/ask in cents
    yes_bid = int(round(yes_bid_dollars * 100))
    yes_ask = int(round(yes_ask_dollars * 100))
    last_cents = int(round(last_price * 100))

    # Spread in cents
    spread = yes_ask - yes_bid

    # Days to close
    close_time_str = mkt.get("close_time", "")
    days_to_close = None
    if close_time_str:
        try:
            close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            delta = close_time - datetime.now(timezone.utc)
            days_to_close = max(0, delta.total_seconds() / 86400)
        except:
            pass

    result = {
        "ticker": ticker,
        "event": mkt.get("event_ticker", ""),
        "title": mkt.get("yes_sub_title", ""),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "last_price": last_cents,
        "spread": spread,
        "volume_24h": volume_24h,
        "days_to_close": days_to_close,
    }
    return result


def scan_near_zero(markets_data: list, ceiling: int = 8) -> list:
    """Find markets priced at or below ceiling cents."""
    opps = []
    for m in markets_data:
        if not m or m.get("yes_bid", 0) <= ceiling or m.get("yes_ask", 0) <= ceiling:
            opps.append(m)
    opps.sort(key=lambda x: x.get("yes_ask", 0))
    return opps[:20]


def scan_liquid_markets(markets_data: list, min_volume: float = 5000) -> list:
    """Find markets with significant volume."""
    liquid = []
    for m in markets_data:
        if m and m.get("volume_24h", 0) >= min_volume:
            liquid.append(m)
    liquid.sort(key=lambda x: x.get("volume_24h", 0), reverse=True)
    return liquid[:15]


def scan_tight_spread(markets_data: list, max_spread: int = 3) -> list:
    """Find markets with tight spreads."""
    tight = []
    for m in markets_data:
        if m and 0 < m.get("spread", 999) <= max_spread:
            tight.append(m)
    tight.sort(key=lambda x: (x.get("spread", 999), -x.get("volume_24h", 0)))
    return tight[:15]


def scan_ending_soon(markets_data: list, max_hours: int = 24) -> list:
    """Find markets closing within the time window."""
    soon = []
    for m in markets_data:
        dtc = m.get("days_to_close")
        if dtc is not None and 0 < dtc <= max_hours / 24:
            soon.append(m)
    soon.sort(key=lambda x: x.get("days_to_close", 999))
    return soon[:15]


def main():
    print("=" * 70)
    print("  KALSHI MARKET SCANNER (Unauthenticated)")
    print(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    print("\nFetching markets from Kalshi... (this may take a minute)")
    raw_markets = fetch_markets_sample(status="open")
    print(f"Fetched {len(raw_markets)} markets")

    # Analyze all markets
    print("\nAnalyzing markets...")
    analyzed = []
    for mkt in raw_markets:
        result = analyze_market(mkt)
        if result:
            analyzed.append(result)
    print(f"Analyzed {len(analyzed)} liquid markets")

    if not analyzed:
        print("No liquid market data found. Demo API may return null prices.")
        return

    # Near-zero scan
    print("\n" + "=" * 70)
    print("  NEAR-ZERO MARKETS (price <= 8 cents)")
    print("=" * 70)
    near_zero = scan_near_zero(analyzed)
    if near_zero:
        for m in near_zero:
            print(f"  {m['ticker']:55s} bid={m['yes_bid']:3d}c ask={m['yes_ask']:3d}c "
                  f"spread={m['spread']:2d}c vol={m['volume_24h']:8.0f} "
                  f"days={m['days_to_close']:.1f}")
    else:
        print("  No near-zero markets found")

    # Liquid markets
    print("\n" + "=" * 70)
    print("  MOST LIQUID MARKETS by 24h Volume")
    print("=" * 70)
    liquid = scan_liquid_markets(analyzed)
    if liquid:
        for m in liquid:
            print(f"  {m['ticker']:55s} bid={m['yes_bid']:3d}c ask={m['yes_ask']:3d}c "
                  f"spread={m['spread']:2d}c vol={m['volume_24h']:8.0f} "
                  f"days={m['days_to_close']:.1f}")
    else:
        print("  No liquid markets found")

    # Tight spread
    print("\n" + "=" * 70)
    print("  TIGHTEST SPREADS (max 3 cents)")
    print("=" * 70)
    tight = scan_tight_spread(analyzed)
    if tight:
        for m in tight:
            print(f"  {m['ticker']:55s} bid={m['yes_bid']:3d}c ask={m['yes_ask']:3d}c "
                  f"spread={m['spread']:2d}c vol={m['volume_24h']:8.0f} "
                  f"days={m['days_to_close']:.1f}")
    else:
        print("  No tight spread markets found")

    # Ending soon
    print("\n" + "=" * 70)
    print("  MARKETS CLOSING WITHIN 24 HOURS")
    print("=" * 70)
    soon = scan_ending_soon(analyzed)
    if soon:
        for m in soon:
            print(f"  {m['ticker']:55s} bid={m['yes_bid']:3d}c ask={m['yes_ask']:3d}c "
                  f"spread={m['spread']:2d}c vol={m['volume_24h']:8.0f} "
                  f"closing in {m['days_to_close']*24:.1f}h")
    else:
        print("  No markets closing soon")

    print(f"\n{'='*70}")
    print(f"  NOTE: Kalshi auth is failing (key likely revoked)")
    print(f"        Regenerate at: https://kalshi.com/account/profile")
    print(f"        Then update .env with new KALSHI_API_KEY_ID and private key PEM")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
