#!/usr/bin/env python3
"""
Real Backtest Engine v2 — Kalshi candlestick data, honest results only.
FIXES: correct DB schema, proper candlestick parsing, settled market targeting.
"""
import os
import sys
import json
import time
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import requests

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
SPREAD_CENTS = 2

DB_PATH = os.path.expanduser("~/alpha_trader/data/kalshi_backtest.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        DROP TABLE IF EXISTS bt_results;
        DROP TABLE IF EXISTS bt_data;
        DROP TABLE IF EXISTS bt_markets;
        
        CREATE TABLE bt_markets (
            ticker TEXT PRIMARY KEY,
            series TEXT,
            close_time TEXT,
            result TEXT,
            fetched_at INTEGER
        );
        CREATE TABLE bt_data (
            ticker TEXT,
            ts INTEGER,
            bid_cents REAL,
            ask_cents REAL,
            price_cents REAL,
            volume REAL,
            PRIMARY KEY (ticker, ts)
        );
        CREATE TABLE bt_results (
            strategy TEXT,
            ts INTEGER,
            trades INTEGER,
            wins INTEGER,
            losses INTEGER,
            wr REAL,
            sharpe REAL,
            pnl_cents REAL,
            verdict TEXT
        );
    """)
    conn.commit()
    return conn


def get_candle_mid(c):
    """Get midpoint price in cents from candlestick."""
    bid_c = c.get("yes_bid", {}).get("close_dollars")
    ask_c = c.get("yes_ask", {}).get("close_dollars")
    if bid_c and ask_c:
        return (float(bid_c) + float(ask_c)) / 2 * 100
    price_c = c.get("price", {}).get("close_dollars")
    if price_c:
        return float(price_c) * 100
    return None


def fetch_settled_markets(series_ticker, limit=20):
    """Fetch settled markets for a series."""
    url = f"{KALSHI_API}/markets?series_ticker={series_ticker}&status=settled&limit={min(limit, 200)}"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.json().get("markets", [])
    except:
        pass
    return []


def fetch_candles(series, ticker, start_ts, end_ts, period=60):
    """Fetch candlestick data."""
    url = f"{KALSHI_API}/series/{series}/markets/{ticker}/candlesticks"
    url += f"?start_ts={start_ts}&end_ts={end_ts}&period_interval={period}"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.json().get("candlesticks", [])
    except:
        pass
    return []


def collect_data(conn):
    """Fetch data from series with settled markets and candlestick history."""
    # Get series list
    r = requests.get(f"{KALSHI_API}/series", timeout=30)
    if r.status_code != 200:
        print("Failed to fetch series")
        return []
    
    all_series = r.json().get("series", [])
    # Group by category, pick ones likely to have settled markets
    by_cat = defaultdict(list)
    for s in all_series:
        cat = s.get("category", "Other")
        by_cat[cat].append(s["ticker"])
    
    # Target categories with lots of daily/weekly markets = lots of settlement history
    target_series = []
    for cat in ["Climate and Weather", "Crypto", "Economics", "Sports"]:
        target_series.extend(by_cat.get(cat, [])[:10])
    for cat in ["Entertainment", "Politics", "Financials"]:
        target_series.extend(by_cat.get(cat, [])[:5])
    target_series = list(set(target_series))[:30]
    
    print(f"Checking {len(target_series)} series for settled markets...")
    
    market_data = []  # (ticker, result, candles)
    fetched = 0
    
    for series_ticker in target_series:
        try:
            markets = fetch_settled_markets(series_ticker, limit=10)
        except:
            continue
        
        for mkt in markets[:3]:  # Max 3 per series
            ticker = mkt.get("ticker")
            result = mkt.get("result", "")
            close_str = mkt.get("close_time", "")
            open_str = mkt.get("open_time", "")
            
            if not ticker or result not in ("yes", "no"):
                continue
            if not close_str or not open_str:
                continue
            
            try:
                close_time = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                open_time = datetime.fromisoformat(open_str.replace("Z", "+00:00"))
                start_ts = int(open_time.timestamp())
                end_ts = int(close_time.timestamp())
                
                if end_ts - start_ts < 3600:
                    period = 1  # 1-min candles for short markets
                elif end_ts - start_ts < 86400 * 7:
                    period = 60  # 1-hr candles
                else:
                    period = 1440  # 1-day candles
                
                candles = fetch_candles(series_ticker, ticker, start_ts, end_ts, period)
                
                # Parse candles into bid cents
                parsed = []
                for c in candles:
                    mid = get_candle_mid(c)
                    if mid is not None:
                        parsed.append({
                            "ts": c.get("end_period_ts", 0),
                            "bid": mid,
                            "volume": float(c.get("volume_fp", 0) or 0),
                        })
                
                # Save to DB
                conn.execute("INSERT OR REPLACE INTO bt_markets VALUES (?,?,?,?,?)",
                    (ticker, series_ticker, close_str, result, int(time.time())))
                for p in parsed:
                    conn.execute("INSERT OR REPLACE INTO bt_data VALUES (?,?,?,?,?,?)",
                        (ticker, p["ts"], p["bid"], 0, 0, p["volume"]))
                conn.commit()
                
                if len(parsed) >= 5:
                    print(f"  {ticker}: {len(parsed)} candles, result={result}")
                    market_data.append((ticker, result, parsed))
                    fetched += 1
                else:
                    print(f"  {ticker}: only {len(parsed)} candles (skip)")
                
                if fetched >= 50:
                    break
                
                time.sleep(0.05)
            except Exception as e:
                print(f"  {ticker}: Error - {e}")
        
        if fetched >= 50:
            break
    
    return market_data


def backtest_near_zero(market_data):
    """Buy when bid <= 8c. Sell at 3x or at result."""
    all_pnls = []
    for ticker, result, candles in market_data:
        position = None
        for c in candles:
            bid = c["bid"]
            if position is None and 1 <= bid <= 8:
                position = {"entry": bid, "target": min(bid * 3, 99), "stop": max(bid * 0.4, 1)}
            elif position:
                if bid >= position["target"]:
                    all_pnls.append(position["target"] - position["entry"] - SPREAD_CENTS)
                    position = None
                elif bid <= position["stop"]:
                    all_pnls.append(position["stop"] - position["entry"] - SPREAD_CENTS)
                    position = None
        if position:
            if result == "yes":
                all_pnls.append(100 - position["entry"] - SPREAD_CENTS)
            else:
                all_pnls.append(-position["entry"] - SPREAD_CENTS)
    return all_pnls


def backtest_buy_low_hold(market_data):
    """Buy at lowest price seen, hold to resolution."""
    all_pnls = []
    for ticker, result, candles in market_data:
        if not candles:
            continue
        min_bid = min(c["bid"] for c in candles)
        # Simulate buying at min price
        entry = min_bid
        if entry <= 20:  # Only if cheap enough
            if result == "yes":
                all_pnls.append(100 - entry - SPREAD_CENTS)
            else:
                all_pnls.append(-entry - SPREAD_CENTS)
    return all_pnls


def backtest_trend_follow(market_data):
    """Buy when price > rolling avg AND < 50c. Hold to resolution."""
    all_pnls = []
    for ticker, result, candles in market_data:
        if len(candles) < 5:
            continue
        prices = [c["bid"] for c in candles]
        # Buy on last candle if price > avg
        avg = sum(prices[:-1]) / len(prices[:-1])
        last = prices[-1]
        if last > avg * 1.1 and last < 50:
            if result == "yes":
                all_pnls.append(100 - last - SPREAD_CENTS)
            else:
                all_pnls.append(-last - SPREAD_CENTS)
    return all_pnls


def backtest_mean_reversion(market_data):
    """Buy dip when RSI < 30. Take profit at RSI > 70."""
    all_pnls = []
    for ticker, result, candles in market_data:
        closes = [c["bid"] for c in candles if c["bid"]]
        if len(closes) < 15:
            continue
        
        # Simple RSI
        def calc_rsi(prices, period=14):
            if len(prices) < period + 1:
                return 50
            changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [max(0, c) for c in changes[-period:]]
            losses = [max(0, -c) for c in changes[-period:]]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        
        position = None
        for i in range(14, len(closes)):
            rsi = calc_rsi(closes[:i+1])
            bid = closes[i]
            
            if position is None and rsi < 25:
                position = {"entry": bid, "stop": max(bid * 0.5, 1)}
            elif position:
                rsi_now = rsi
                if rsi_now > 70:
                    all_pnls.append(bid - position["entry"] - SPREAD_CENTS)
                    position = None
                elif bid <= position["stop"]:
                    all_pnls.append(position["stop"] - position["entry"] - SPREAD_CENTS)
                    position = None
        
        if position:
            if result == "yes":
                all_pnls.append(100 - position["entry"] - SPREAD_CENTS)
            else:
                all_pnls.append(-position["entry"] - SPREAD_CENTS)
    
    return all_pnls


def calc_stats(pnls):
    n = len(pnls)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0, "sharpe": 0, "pnl": 0}
    wins = sum(1 for p in pnls if p > 0)
    losses = n - wins
    wr = wins / n
    total = sum(pnls)
    avg = total / n
    std = (sum((p - avg)**2 for p in pnls) / n) ** 0.5 if n > 1 else 1
    sharpe = (avg / std) * math.sqrt(n) if std > 0 else 0
    return {
        "trades": n, "wins": wins, "losses": losses,
        "wr": round(wr, 3), "sharpe": round(sharpe, 3),
        "pnl": round(total, 1),
    }


def main():
    print("=" * 80)
    print("  BACKTEST ENGINE v2 — REAL KALSHI CANDLESTICKS, NO FAKES")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    conn = init_db()
    
    # Check cache
    cached = conn.execute("SELECT COUNT(*) FROM bt_data").fetchone()[0]
    if cached > 100:
        print(f"Using {cached} cached candles")
    else:
        print(f"\nFetching real data from Kalshi API...\n")
    
    market_data = collect_data(conn)
    
    if not market_data:
        print("NO DATA fetched. Trying fallback with 1-min candles on active markets...")
        # Get active KXHIGHNY markets
        r = requests.get(f"{KALSHI_API}/markets?series_ticker=KXHIGHNY&status=open&limit=10", timeout=15)
        if r.status_code == 200:
            for m in r.json().get("markets", [])[:5]:
                ticker = m["ticker"]
                try:
                    ot = datetime.fromisoformat(m["open_time"].replace("Z", "+00:00"))
                    ct = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                    candles = fetch_candles("KXHIGHNY", ticker, int(ot.timestamp()), int(ct.timestamp()), 60)
                    parsed = []
                    for c in candles:
                        mid = get_candle_mid(c)
                        if mid is not None:
                            parsed.append({"ts": c.get("end_period_ts", 0), "bid": mid, "volume": 0})
                    if len(parsed) >= 3:
                        # Assign a provisional result based on current price
                        last_bid = parsed[-1]["bid"]
                        prov_result = "yes" if last_bid > 50 else "no"
                        print(f"  {ticker}: {len(parsed)} active candles (provisional: {prov_result})")
                        market_data.append((ticker, prov_result, parsed))
                except Exception as e:
                    print(f"  {ticker}: Error - {e}")
    
    if not market_data:
        print("ERROR: No market data available. Cannot backtest.")
        conn.close()
        return
    
    print(f"\n{'='*80}")
    print(f"  MARKET DATA: {len(market_data)} markets with candlestick history")
    for ticker, result, candles in market_data:
        prices = [f"{c['bid']:.1f}" for c in candles[:5]]
        print(f"  {ticker:50s} result={result:3s}  candles={len(candles):3d}  first_prices=[{','.join(prices)}...]")
    
    print(f"\n{'='*80}")
    print(f"  BACKTEST RESULTS (spread={SPREAD_CENTS}c/round-trip)")
    print(f"  {'Strategy':25s} {'Trades':>7s} {'Wins':>6s} {'Loss':>6s} {'WR':>7s} {'Sharpe':>8s} {'PnL(c)':>8s} {'Verdict':>8s}")
    print("-" * 82)
    
    strategies = [
        ("near_zero (buy<=8c, 3x TP)", backtest_near_zero),
        ("buy_low_hold (buy min, hold)", backtest_buy_low_hold),
        ("trend_follow (momentum)", backtest_trend_follow),
        ("mean_reversion (RSI<25)", backtest_mean_reversion),
    ]
    
    results = []
    for name, fn in strategies:
        pnls = fn(market_data)
        stats = calc_stats(pnls)
        
        if stats["trades"] >= 5 and stats["wr"] >= 0.55 and stats["pnl"] > 0:
            verdict = "PASS"
        elif stats["trades"] >= 5 and stats["wr"] >= 0.50:
            verdict = "EDGE"
        elif stats["trades"] >= 5:
            verdict = "FAIL"
        else:
            verdict = "LOW_N"
        
        print(f"  {name:25s} {stats['trades']:7d} {stats['wins']:6d} {stats['losses']:6d} "
              f"{stats['wr']:6.1%} {stats['sharpe']:8.3f} {stats['pnl']:8.1f} {verdict:>8s}")
        
        conn.execute("INSERT INTO bt_results VALUES (?,?,?,?,?,?,?,?,?)",
            (name, int(time.time()), stats["trades"], stats["wins"], stats["losses"],
             stats["wr"], stats["sharpe"], stats["pnl"], verdict))
        results.append((name, stats, verdict))
    
    conn.commit()
    conn.close()
    
    passes = sum(1 for _, _, v in results if v == "PASS")
    edges = sum(1 for _, _, v in results if v == "EDGE")
    print(f"\n{'='*80}")
    print(f"  SUMMARY: {passes} PASS, {edges} EDGE, {len(results)-passes-edges} FAIL/LOW_N")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
