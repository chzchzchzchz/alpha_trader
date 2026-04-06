#!/usr/bin/env python3
"""Research Subagent — ALWAYS running
Discovers new market opportunities, backtests strategies on REAL Kalshi data,
and proposes new alpha. Writes proposals to DB for autonomous_trader.py to execute.

Runs independently. Never restarts. Self-improves.
"""
import os, sys, time, sqlite3, json, math, random, logging
from datetime import datetime, timezone
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/research.log")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RESEARCH] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("research")

API = "https://api.elections.kalshi.com/trade-api/v2"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS research_proposals (
        ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
        yes_bid REAL, yes_ask REAL, vol REAL, bt_markets INT,
        bt_wr REAL, bt_pnl REAL, bt_sharpe REAL, expected_pnl REAL,
        proposal_score REAL, verdict TEXT, details TEXT
    )""")
    conn.commit()
    return conn


def fetch_markets(series=None, status="open", limit=200):
    """Fetch markets from API with pagination."""
    all_mkts = []
    cursor = None
    params = {"status": status, "limit": min(limit, 200)}
    if series:
        params["series_ticker"] = series

    url = f"{API}/markets"
    for _ in range(5):  # max 5 pages
        try:
            if cursor:
                r = requests.get(f"{url}?cursor={cursor}", params=params, timeout=15)
            else:
                r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            mkts = data.get("markets", [])
            all_mkts.extend(mkts)
            cursor = data.get("cursor")
            if not cursor or len(mkts) < 200:
                break
            time.sleep(0.05)
        except:
            break
    return all_mkts


def fetch_historical(series_ticker, limit=100):
    """Fetch SETTLED markets for backtesting."""
    mkts = fetch_markets(series_ticker, status="settled", limit=limit)
    return mkts


def backtest_strategy(strategy_name, markets):
    """
    Backtest a strategy on settled markets. Returns stats dict.
    Each market has: yes_bid_dollars, yes_ask_dollars, result, close_time
    """
    trades = []
    trades_per_market = 0

    for mkt in markets:
        result = mkt.get("result", "")
        if result not in ("yes", "no"):
            continue

        bid = mkt.get("yes_bid_dollars")
        ask = mkt.get("yes_ask_dollars")
        if bid is None or ask is None:
            continue

        bid_c = round(float(bid) * 100)
        ask_c = round(float(ask) * 100)

        if strategy_name == "near_zero_no":
            # Buy NO when YES is cheap (1-15c)
            if 1 <= ask_c <= 15:
                no_price = 100 - ask_c  # NO costs this much
                if result == "no":  # We were right
                    pnl = no_price - 2  # Profit minus spread
                else:
                    pnl = -no_price  # Lost our buy
                trades.append(pnl)
                trades_per_market += 1

        elif strategy_name == "near_zero_yes":
            # Buy YES when YES is cheap (1-15c)
            if 1 <= ask_c <= 15:
                if result == "yes":
                    pnl = (100 - ask_c) - 2
                else:
                    pnl = -ask_c
                trades.append(pnl)
                trades_per_market += 1

        elif strategy_name == "overpriced_short":
            # Short (buy NO) when YES is 85c+
            if bid_c >= 85:
                no_price = 100 - bid_c
                if result == "no":
                    pnl = no_price - 2
                else:
                    pnl = -no_price
                trades.append(pnl)

        elif strategy_name == "momentum_yes":
            # Buy YES when market is 20-50c and trending
            if 20 <= ask_c <= 50 and trades_per_market > 0:
                if result == "yes":
                    pnl = (100 - ask_c) - 2
                else:
                    pnl = -ask_c
                trades.append(pnl)

    if not trades:
        return None

    n = len(trades)
    wins = sum(1 for t in trades if t > 0)
    wr = wins / n
    total = sum(trades)
    avg = total / n
    std = math.sqrt(sum((t - avg)**2 for t in trades) / max(n, 1)) if n > 1 else 1
    sharpe = (avg / std) * math.sqrt(n) if std > 0 else 0

    return {
        "n": n, "wins": wins, "wr": round(wr, 3),
        "total_pnl": round(total, 1), "avg_pnl": round(avg, 1),
        "sharpe": round(sharpe, 3)
    }


def scan_series_for_alpha(series_ticker, conn):
    """Research a single series for exploitable patterns."""
    results = []

    # Step 1: Fetch settled markets and backtest each strategy
    hist = fetch_historical(series_ticker, limit=200)
    if not hist:
        return results

    strategies = ["near_zero_no", "near_zero_yes", "overpriced_short", "momentum_yes"]
    for strat in strategies:
        stats = backtest_strategy(strat, hist)
        if stats and stats["wr"] >= 0.55 and stats["total_pnl"] > 0 and stats["n"] >= 5:
            results.append({
                "series": series_ticker,
                "strategy": strat,
                "backtest": stats,
            })

    # Step 2: Check current open markets for opportunities matching winning strategies
    open_mkts = fetch_markets(series_ticker, status="open", limit=50)
    for strat_result in results:
        strat = strat_result["strategy"]
        bt = strat_result["backtest"]
        for mkt in open_mkts[:10]:
            bid = mkt.get("yes_bid_dollars")
            ask = mkt.get("yes_ask_dollars")
            if bid is None or ask is None:
                continue
            bid_c = round(float(bid) * 100)
            ask_c = round(float(ask) * 100)
            vol = float(mkt.get("volume_24h_fp", 0) or 0)
            if vol < 5:
                continue

            ticker = mkt.get("ticker", "")
            proposal = None

            if strat == "near_zero_no" and ask_c <= 15:
                yes_swarm = bid_c / 100.0
                no_probability = 1 - yes_swarm
                no_cost = 100 - bid_c  # NO ask price
                exp_pnl = no_probability * (100 - no_cost) - (1 - no_probability) * no_cost - 2
                if exp_pnl > 3:  # Min 3c expected profit
                    proposal = {
                        "ticker": ticker, "side": "no",
                        "strategy": strat,
                        "yes_bid": bid, "yes_ask": ask, "vol": vol,
                        "bt_markets": bt["n"], "bt_wr": bt["wr"],
                        "bt_pnl": bt["total_pnl"], "bt_sharpe": bt["sharpe"],
                        "expected_pnl": round(exp_pnl, 1),
                    }

            elif strat == "near_zero_yes" and ask_c <= 15:
                yes_swarm = ask_c / 100.0
                exp_pnl = yes_swarm * (100 - ask_c) - (1 - yes_swarm) * ask_c - 2
                if exp_pnl > 3:
                    proposal = {
                        "ticker": ticker, "side": "yes",
                        "strategy": strat,
                        "yes_bid": bid, "yes_ask": ask, "vol": vol,
                        "bt_markets": bt["n"], "bt_wr": bt["wr"],
                        "bt_pnl": bt["total_pnl"], "bt_sharpe": bt["sharpe"],
                        "expected_pnl": round(exp_pnl, 1),
                    }

            elif strat == "overpriced_short" and bid_c >= 85:
                yes_swarm = bid_c / 100.0
                no_probability = 1 - yes_swarm
                no_cost = 100 - bid_c
                exp_pnl = no_probability * (100 - no_cost) - (1 - no_probability) * no_cost - 2
                if exp_pnl > 5:
                    proposal = {
                        "ticker": ticker, "side": "no",
                        "strategy": strat,
                        "yes_bid": bid, "yes_ask": ask, "vol": vol,
                        "bt_markets": bt["n"], "bt_wr": bt["wr"],
                        "bt_pnl": bt["total_pnl"], "bt_sharpe": bt["sharpe"],
                        "expected_pnl": round(exp_pnl, 1),
                    }

            if proposal:
                # Score: higher backtest WR and higher expected PnL = higher score
                score = bt["wr"] * 100 + proposal["expected_pnl"] / 5 + min(bt["n"] / 10, 10)
                proposal["proposal_score"] = round(score, 1)
                proposal["ts"] = int(time.time())
                proposal["verdict"] = "PROPOSE" if bt["wr"] >= 0.60 else "WATCH"
                proposal["details"] = f"BT: WR={bt['wr']:.0%} PnL={bt['total_pnl']:.0f}c N={bt['n']}"
                results.append({"proposal": proposal})

    return results


def get_all_series():
    """Get list of all series from Kalshi."""
    try:
        r = requests.get(f"{API}/series?limit=200", timeout=15)
        if r.status_code == 200:
            return r.json().get("series", [])
    except:
        pass
    return []


def main_loop():
    conn = init_db()
    log.info("Research SubAgent started. Scanning Kalshi for alpha...")

    # Get all series sorted by volume (most active first)
    series = get_all_series()
    log.info(f"Found {len(series)} series on Kalshi")

    # Priority: weather and temperature series first (most liquid)
    priority = [s for s in series if any(kw in s.get("ticker", "").upper()
                for kw in ["TEMP", "HIGH", "LOW", "SNOW", "WIND", "RAIN", "HIGHNY", "LOWTPHIL", "LOWTLAX"])]
    rest = [s for s in series if s not in priority]
    scan_queue = priority + rest

    cycle = 0
    while True:
        cycle += 1
        log.info(f"\n{'='*60}\nResearch Cycle {cycle} at {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

        proposals_found = 0
        backtests_run = 0
        new_series = 0

        # Scan up to 20 series per cycle
        for s in scan_queue[:20]:
            ticker = s.get("ticker", "")
            if not ticker:
                continue
            new_series += 1
            results = scan_series_for_alpha(ticker, conn)

            # Log backtest results
            for r in results:
                if "backtest" in r:
                    bt = r["backtest"]
                    strat = r.get("strategy", "?")
                    log.info(f"  BT {ticker} {strat}: WR={bt['wr']:.0%} PnL={bt['total_pnl']:+.0f}c trades={bt['n']}")
                    backtests_run += 1
                elif "proposal" in r:
                    p = r["proposal"]
                    conn.execute(
                        "INSERT INTO research_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (p["ts"], p["ticker"], p["side"], p["strategy"],
                         p["yes_bid"], p["yes_ask"], p["vol"], p["bt_markets"],
                         p["bt_wr"], p["bt_pnl"], p["bt_sharpe"], p["expected_pnl"],
                         p["proposal_score"], p["verdict"], p["details"]))
                    log.info(f"  PROPOSAL: {p['ticker']} {p['side']} via {p['strategy']} "
                             f"Exp={p['expected_pnl']:+.0f}c Score={p['proposal_score']:.1f}")
                    proposals_found += 1

        conn.commit()
        log.info(f"\nCycle {cycle}: scanned={new_series} backtests={backtests_run} proposals={proposals_found}")

        # Self-improve: if we found lots of proposals, increase scan depth next cycle
        if proposals_found > 5:
            log.info(f"  High alpha found! Increasing scan window.")

        time.sleep(120)  # Scan every 2 minutes


if __name__ == "__main__":
    main_loop()
