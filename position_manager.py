#!/usr/bin/env python3
"""
Position Manager — auto-exit engine for open positions.
Monitors all open trades, evaluates exit conditions using strategy-specific logic
or fallback generic rules, and executes sells.
"""
import os, sys, time, sqlite3, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/position_manager.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POSMAN] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("posman")

# Strategy registry — imports will happen lazily to avoid circular dependencies
STRATEGY_CLASSES = {
    "near_zero": ("kalshi.strategies.near_zero", "NearZeroStrategy"),
    "category_specialist": ("kalshi.strategies.category_specialist", "CategorySpecialistStrategy"),
    "convergence": ("kalshi.strategies.convergence", "ConvergenceStrategy"),
    "late_window": ("kalshi.strategies.late_window", "LateWindowStrategy"),
    "flash_crash": ("kalshi.strategies.flash_crash", "FlashCrashStrategy"),
    "longshot": ("kalshi.strategies.longshot", "LongshotStrategy"),
}

def load_strategy_instance(strategy_name, client, analyzer):
    """Lazy-load strategy class and return instance."""
    if strategy_name in STRATEGY_CLASSES:
        module_name, class_name = STRATEGY_CLASSES[strategy_name]
        try:
            mod = __import__(module_name, fromlist=[class_name])
            cls = getattr(mod, class_name)
            # Most strategies take (client, analyzer) in __init__
            if strategy_name in ['late_window', 'flash_crash']:
                return cls(client)  # these may only need client
            return cls(client, analyzer)
        except Exception as e:
            log.error(f"Failed to load strategy {strategy_name}: {e}")
    return None

def get_open_positions(conn):
    """Return list of open trade rows."""
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM trades WHERE status='open' ORDER BY ts ASC")
    rows = cur.fetchall()
    return [dict(row) for row in rows]

def get_current_market_data(client, tickers):
    """Fetch current market mids for given tickers."""
    try:
        markets = client.get_markets(limit=100)
        mids = {}
        for m in markets.get('markets', []):
            t = m.get('ticker')
            if t in tickers:
                yes_bid = m.get('yes_bid_dollars')
                yes_ask = m.get('yes_ask_dollars')
                if yes_bid is not None and yes_ask is not None:
                    mids[t] = (float(yes_bid) + float(yes_ask)) / 2
        return mids
    except Exception as e:
        log.error(f"Fetch markets failed: {e}")
        return {}

def check_generic_exit(position, current_mid):
    """Generic exit: take profit at 2x entry, stop loss at -50%."""
    side = position['side']
    entry_cents = position['price_cents'] / 100.0
    current = current_mid
    if side == 'no':
        current = 1 - current
    # Compute PnL factor
    if side == 'yes':
        pnl_factor = (current - entry_cents) / entry_cents if entry_cents > 0 else 0
    else:
        pnl_factor = (entry_cents - current) / (1 - entry_cents) if (1 - entry_cents) > 0 else 0
    take_profit = pnl_factor >= 2.0  # 2x
    stop_loss = pnl_factor <= -0.5   # -50%
    return take_profit or stop_loss, pnl_factor

def run_cycle():
    log.info("=== Position manager cycle ===")
    client = KalshiClient(
        key_id=os.getenv("KALSHI_API_KEY_ID"),
        private_key_path=os.get.expanduser(os.getenv("KALSHI_API_KEY_FILE", "~/.kalshi/private_key.pem")),
        demo=os.getenv("KALSHI_DEMO", "true").lower() == "true",
    )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    positions = get_open_positions(conn)
    if not positions:
        log.info("No open positions")
        conn.close()
        return

    tickers = [p['ticker'] for p in positions]
    mids = get_current_market_data(client, tickers)
    if not mids:
        log.warning("No market data fetched, skipping exit checks")
        conn.close()
        return

    # Organize positions by ticker for quick lookup, and by strategy
    positions_by_ticker = {p['ticker']: p for p in positions}
    positions_by_strategy = {}
    for p in positions:
        strat = p.get('strategy', 'unknown')
        positions_by_strategy.setdefault(strat, []).append(p)

    # First, let each strategy evaluate its own positions via check_exits if available
    exits_identified = []
    for strat_name, pos_list in positions_by_strategy.items():
        strat_obj = load_strategy_instance(strat_name, client, None)
        if strat_obj and hasattr(strat_obj, 'check_exits'):
            try:
                # Build markets_by_ticker dict limited to these tickers
                markets_subset = {t: mids[t] for t in [p['ticker'] for p in pos_list] if t in mids}
                closed_tickers = strat_obj.check_exits(markets_subset)
                for t in closed_tickers:
                    exits_identified.append(t)
                    log.info(f"Strategy {strat_name} signals exit for {t}")
            except Exception as e:
                log.error(f"Strategy {strat_name} check_exits failed: {e}")

    # For positions not handled by strategy, use generic exit
    for p in positions:
        ticker = p['ticker']
        if ticker in exits_identified:
            continue
        mid = mids.get(ticker)
        if mid is None:
            continue
        should_exit, pnl_factor = check_generic_exit(p, mid)
        if should_exit:
            exits_identified.append(ticker)
            reason = "take_profit" if pnl_factor >= 2.0 else "stop_loss"
            log.info(f"Generic exit {ticker}: {reason} (pnl_factor={pnl_factor:.2f})")

    # Execute sells for all identified exits
    for ticker in exits_identified:
        p = positions_by_ticker.get(ticker)
        if not p:
            continue
        try:
            # Market sell
            resp = client.place_order(
                ticker=ticker,
                action='sell',
                side=p['side'],
                count=p['contracts'] if 'contracts' in p else 1,
                type='market',
            )
            order_id = resp.get('order', {}).get('order_id')
            if order_id:
                # Update trade record
                now = int(time.time())
                conn.execute(
                    "UPDATE trades SET status='closed', exit_ts=?, exit_price_cents=? WHERE ticker=? AND status='open'",
                    (now, int(mids[ticker] * 100) if mids.get(ticker) else None, ticker)
                )
                conn.commit()
                log.info(f"Closed {ticker} via sell order {order_id}")
        except Exception as e:
            log.error(f"Sell order failed for {ticker}: {e}")

    conn.close()
    log.info("Cycle complete")

if __name__ == "__main__":
    try:
        run_cycle()
    except Exception as e:
        log.error(f"Position manager crashed: {e}", exc_info=True)
        sys.exit(1)