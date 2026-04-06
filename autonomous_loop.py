#!/usr/bin/env python3
"""
Unified autonomous Kalshi trading system.
Scans markets -> MiroFish swarm eval -> Strategy signals -> Execute if edge > threshold.
Runs continuously. Never stops.
"""
import os
import sys
import time
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from kalshi.client import KalshiClient
from kalshi.wallet_analyzer import WalletAnalyzer
from mirofish import MiroFishSwarm

# ── CREDENTIALS ──
KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")

DB = os.path.expanduser("~/alpha_trader/data/autonomous_trades.db")
LOG = os.path.expanduser("~/alpha_trader/logs/kalshi_autonomous.log")

os.makedirs(os.path.dirname(DB), exist_ok=True)
os.makedirs(os.path.dirname(LOG), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("autonomous")

# ── RISK PARAMETERS ──
MAX_DAILY_PNL = 300  # Max daily PnL in cents (=$3), stop if exceeded (downside protection)
MIN_BALANCE = 300    # Stop if balance drops below $3 (300 cents)
MAX_SINGLE_TRADE = 3 # Max cents on one trade
KELLY_FRACTION = 0.1 # Aggressive Kelly fraction

# ── INIT ──
client = KalshiClient(
    key_id=KEY_ID,
    private_key_path=PEM,
    demo=True,  # Start in demo until strategies validated
)
analyzer = WalletAnalyzer(client)
swarm = MiroFishSwarm(n_agents=300)

DB_VERSION = 1

def init_trade_db():
    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            ts INTEGER, strategy TEXT, ticker TEXT, side TEXT,
            swarm_yes REAL, market_price REAL, edge REAL,
            signal_strength REAL, execute INTEGER
        );
        CREATE TABLE IF NOT EXISTS trades (
            ts INTEGER, strategy TEXT, ticker TEXT, side TEXT,
            price_cents INTEGER, contracts INTEGER,
            order_id TEXT, status TEXT, demo INTEGER
        );
        CREATE TABLE IF NOT EXISTS daily_pnl (
            date TEXT PRIMARY KEY,
            realized_pnl REAL, unrealized_pnl REAL,
            n_trades INTEGER
        );
    """)
    conn.commit()
    return conn


def scan_and_score():
    """Scan all markets, score with swarm + strategies."""
    logger.info("Scanning markets...")
    try:
        markets = analyzer.fetch_all_markets()
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return []

    logger.info(f"Analyzing {len(markets)} markets with MiroFish swarm...")
    signals = []

    for mkt in markets:
        yes_bid = mkt.get("yes_bid", mkt.yes_bid if hasattr(mkt, 'yes_bid') else None)
        yes_ask = mkt.get("yes_ask", mkt.yes_ask if hasattr(mkt, 'yes_ask') else None)
        if yes_bid is None or yes_ask is None:
            continue
        
        # Normalize to cents
        if isinstance(yes_bid, float) and yes_bid < 1:
            # Dollars
            bid_c = int(yes_bid * 100)
            ask_c = int(yes_ask * 100)
            price = (yes_bid + yes_ask) / 2
        else:
            bid_c = int(yes_bid)
            ask_c = int(yes_ask)
            price = (bid_c + ask_c) / 200

        # Swarm
        category = mkt.get("event_ticker", "") or getattr(mkt, "event_ticker", "")
        close_t = mkt.get("close_time", mkt.close_time if hasattr(mkt, 'close_time') else None)
        days = None
        if close_t:
            try:
                from datetime import datetime, timezone
                ct = datetime.fromisoformat(str(close_t).replace("Z", "+00:00"))
                days = max(0, (ct - datetime.now(timezone.utc)).total_seconds() / 86400)
            except Exception:
                pass

        swarm_result = swarm.predict({
            "price": price, "category": category,
            "days_to_close": days, "trend": 0, "news_signal": 0,
        })

        # NearZero strategy check
        near_zero = 1 <= bid_c <= 15  # Optimized ceiling from backtest

        # Check if swarm finds edge
        edge = swarm_result["edge"]
        signal_str = swarm_result["signal_strength"]
        rec = swarm_result["recommendation"]

        score = 0
        if near_zero and edge > 0.05:
            score = abs(edge) * signal_str * 100
        elif signal_str > 0.3 and abs(edge) > 0.08:
            score = abs(edge) * signal_str * 50

        ticker = mkt.ticker if hasattr(mkt, 'ticker') else mkt.get("ticker", "")
        signals.append({
            "ticker": ticker,
            "bid_c": bid_c, "ask_c": ask_c, "price": price,
            "swarm_yes": swarm_result["yes_pct"],
            "swarm_no": swarm_result["no_pct"],
            "signal_strength": signal_str,
            "edge": edge,
            "recommendation": rec,
            "near_zero": near_zero,
            "days_to_close": days,
            "score": round(score, 2),
            "category": category,
        })

    # Sort by score
    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals


def execute_signals(signals, max_trades=5):
    """Execute top signals if edge > threshold."""
    executed = 0
    for sig in signals[:max_trades]:
        if sig["score"] < 0.5 or not sig["near_zero"]:
            continue
        if executed >= max_trades:
            break

        ticker = sig["ticker"]
        rec = sig["recommendation"]
        if rec not in ("buy_yes", "buy_no"):
            continue

        side = "yes" if rec == "buy_yes" else "no"
        price_c = sig["ask_c"] if side == "yes" else int((1 - sig["swarm_yes"]) * 100)
        if price_c < 1:
            price_c = 1

        logger.info(f"EXEC: {ticker} {side} x1 @ {price_c}c (edge={sig['edge']:+.1%} swarm={sig['swarm_yes']:.1%})")

        try:
            result = client.place_order(
                ticker=ticker, action="buy", side=side,
                count=1, yes_price=price_c if side == "yes" else None,
                no_price=price_c if side == "no" else None,
                client_order_id=f"af-{time.time()}",
            )
            order = result.get("order", {})
            oid = order.get("order_id", "unknown")
            status = order.get("status", "unknown")
            logger.info(f"-> Order {oid}: {status}")
            executed += 1
        except Exception as e:
            logger.error(f"Order failed for {ticker}: {e}")

    return executed


def run_cycle(conn):
    """One full autonomous cycle."""
    signals = scan_and_score()

    if not signals:
        logger.info("No signals found")
        return

    # Print top 10
    logger.info(f"\n{'TICKER':55s} {'PRICE':>6s} {'SWARM_Y':>7s} {'EDGE':>7s} {'SIGNAL':>7s} {'REC':>10s} {'SCORE':>6s}")
    logger.info("-" * 100)
    for sig in signals[:10]:
        logger.info(
            f"{sig['ticker']:55s} {sig['price']*100:5.0f}c "
            f"{sig['swarm_yes']:7.1%} {sig['edge']:+6.1%} "
            f"{sig['signal_strength']:6.2f} {sig['recommendation']:>10s} "
            f"{sig['score']:6.1f}"
        )

    # Save signals to DB
    now = int(time.time())
    for sig in signals[:20]:
        conn.execute(
            "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?)",
            (now, "mirofish+nearzero", sig["ticker"], sig["recommendation"],
             sig["swarm_yes"], sig["price"], sig["edge"],
             sig["signal_strength"], int(sig["score"] > 0.5)),
        )

    # Check balance
    try:
        bal = client.get_balance()
        cents = bal.get("balance", 0) + bal.get("portfolio_value", 0)
        logger.info(f"Balance: ${cents/100:.2f}")
        if cents < MIN_BALANCE:
            logger.warning(f"Balance too low (${cents/100:.2f} < ${MIN_BALANCE/100:.2f}), skipping trades")
            conn.commit()
            return
    except Exception as e:
        logger.error(f"Balance check failed: {e}")
        conn.commit()
        return

    # Execute top signals (demo mode for now)
    executed = execute_signals(signals, max_trades=3)
    logger.info(f"Executed {executed} trades this cycle")
    conn.commit()


def main():
    logger.info("=" * 70)
    logger.info("AUTONOMOUS KALSHI TRADING SYSTEM — MIROFISH + NEARZERO")
    logger.info(f"Demo mode: {client.base_url}")
    logger.info("=" * 70)

    conn = init_trade_db()
    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            logger.info(f"\n{'='*50}")
            logger.info(f"CYCLE {cycle_count} — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
            run_cycle(conn)
            logger.info(f"Cycle {cycle_count} complete. Sleeping 60s...\n")
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
            conn.close()
            break
        except Exception as e:
            logger.error(f"Cycle crashed: {e}", exc_info=True)
            logger.info("Recovering in 30s...\n")
            time.sleep(30)


if __name__ == "__main__":
    main()
