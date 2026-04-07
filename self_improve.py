#!/usr/bin/env python3
"""Self-Improvement Agent — ALWAYS running
Every 5 minutes:
1. Re-evaluates all strategy performance
2. Auto-enables profitable strategies, auto-disables losers
3. Adjusts entry thresholds based on fill rates
4. Writes learnings to DB so Research and Executor can adapt

Runs as independent daemon. Never stops.
"""
import os, sys, time, sqlite3, json, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/self_improve.log")
CONFIG_PATH = os.path.expanduser("~/alpha_trader/data/strategy_config.json")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SELF-IMPROVE] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("self_improve")

# Default strategy configurations
DEFAULT_STRATEGIES = {
    "near_zero_no": {
        "name": "Near-Zero NO",
        "enabled": True,
        "params": {"max_yes_ask": 15, "min_volume": 5, "max_entry_cents": 15},
        "performance": {"total_trades": 0, "total_pnl": 0, "last_wr": 0, "last_check": 0},
    },
    "near_zero_yes": {
        "name": "Near-Zero YES",
        "enabled": True,
        "params": {"max_yes_ask": 15, "min_volume": 10, "max_entry_cents": 15},
        "performance": {"total_trades": 0, "total_pnl": 0, "last_wr": 0, "last_check": 0},
    },
    "overpriced_short": {
        "name": "Overpriced Short (buy NO at 85c+)",
        "enabled": True,
        "params": {"min_yes_bid": 85, "max_entry_cents": 30},
        "performance": {"total_trades": 0, "total_pnl": 0, "last_wr": 0, "last_check": 0},
    },
    "momentum_yes": {
        "name": "Momentum YES",
        "enabled": False,  # Disabled until proven
        "params": {"min_bid": 20, "max_ask": 50, "min_volume": 100},
        "performance": {"total_trades": 0, "total_pnl": 0, "last_wr": 0, "last_check": 0},
    },
}


def load_config():
    """Load or create strategy configuration."""
    if os.path.exists(CONFIG_PATH):
        try:
            return json.load(open(CONFIG_PATH))
        except:
            pass
    
    # Create default
    cfg = {}
    for name, data in DEFAULT_STRATEGIES.items():
        cfg[name] = {
            "enabled": data["enabled"],
            "params": data["params"],
            "performance": data["performance"],
        }
    
    save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, default=str)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS debate_decisions (
        ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
        bull_score REAL, bull_reasons TEXT,
        bear_score REAL, bear_reasons TEXT,
        consensus_score REAL, verdict TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_adjustments (
        ts INTEGER, strategy TEXT, old_params TEXT, new_params TEXT,
        reason TEXT, decision TEXT
    )""")
    conn.commit()
    return conn


def evaluate_backtest_performance(conn):
    """Check which strategies passed backtests recently."""
    results = {}
    strategies = [
        "near_zero_no", "near_zero_yes", "overpriced_short", "momentum_yes"
    ]
    
    for strat in strategies:
        rows = conn.execute(
            "SELECT wr, pnl, n FROM strategy_performance WHERE strategy = ? ORDER BY ts DESC LIMIT 5",
            (strat,)).fetchall()
        
        if not rows:
            # Try research proposals
            rows = conn.execute(
                "SELECT bt_wr, bt_pnl, bt_markets FROM research_proposals "
                "WHERE strategy = ? ORDER BY ts DESC LIMIT 10",
                (strat,)).fetchall()
            
            if not rows:
                # Try backtest_validation results
                rows = conn.execute(
                    "SELECT win_rate, total_pnl, n_trades FROM bt_results "
                    "WHERE strategy = ? AND verdict='PASS' ORDER BY ts DESC LIMIT 10",
                    (strat,)).fetchall()
        
        if rows:
            avg_wr = sum(r[0] for r in rows) / len(rows)
            avg_pnl = sum(r[1] for r in rows) / len(rows)
            avg_n = sum(r[2] if len(r) > 2 else 0 for r in rows) / len(rows)
            results[strat] = {
                "wr": round(avg_wr, 3),
                "pnl": round(avg_pnl, 1),
                "n": round(avg_n, 1),
                "samples": len(rows),
            }
        else:
            results[strat] = {
                "wr": 0, "pnl": 0, "n": 0, "samples": 0,
                "note": "No backtest data found",
            }
    
    return results


def evaluate_live_performance(conn):
    """Check how strategies performed in live trades."""
    results = {}
    rows = conn.execute(
        "SELECT strategy, COUNT(*), SUM(price_cents), "
        "SUM(CASE WHEN status='executed' THEN 1 ELSE 0 END) "
        "FROM trades GROUP BY strategy").fetchall()
    
    for row in rows:
        strat, total, exposure, filled = row
        results[strat] = {
            "total_orders": total,
            "filled": filled or 0,
            "fill_rate": round((filled or 0) / total, 3) if total else 0,
            "total_exposure_cents": exposure or 0,
        }
    
    return results


def make_adjustments(conn, bt_results, live_results, config):
    """Decide which strategies to enable/disable and how to adjust params."""
    adjustments = []
    
    for strat, cfg_data in config.items():
        bt = bt_results.get(strat, {})
        live = live_results.get(strat, {})
        
        bt_wr = bt.get("wr", 0)
        bt_pnl = bt.get("pnl", 0)
        bt_n = bt.get("n", 0)
        
        fill_rate = live.get("fill_rate", 0)
        
        old_enabled = cfg_data["enabled"]
        new_enabled = old_enabled
        reason = ""
        decision = "No change"
        
        # Rule 1: Backtest WR >= 60% with 5+ samples → Enable
        if bt_n >= 5 and bt_wr >= 0.60 and bt_pnl > 0 and not old_enabled:
            new_enabled = True
            reason = f"BT WR={bt_wr:.0%} PnL={bt_pnl:.0f}c over {bt_n} trades"
            decision = "ENABLED"
            adjustments.append(decision)
            log.info(f"  ✅ ENABLING {strat}: {reason}")
            
            cfg_data["params"] = DEFAULT_STRATEGIES.get(strat, {}).get("params", {})
        
        # Rule 2: Backtest WR < 40% with 5+ samples → Disable
        if bt_n >= 5 and bt_wr < 0.40 and old_enabled:
            # Only disable if we have enough data
            if bt_n >= 10:
                new_enabled = False
                reason = f"BT WR={bt_wr:.0%} PnL={bt_pnl:.0f}c over {bt_n} trades — too poor"
                decision = "DISABLED"
                adjustments.append(decision)
                log.info(f"  ❌ DISABLING {strat}: {reason}")
        
        # Rule 3: Fill rate < 10% → Adjust entry price to be more competitive
        if live.get("total_orders", 0) >= 5 and fill_rate < 0.10 and old_enabled:
            # Increase max_entry_cents by 20%
            current_max = cfg_data["params"].get("max_entry_cents", 15)
            new_max = min(int(current_max * 1.2), 30)  # Cap at 30c
            cfg_data["params"]["max_entry_cents"] = new_max
            reason = f"Fill rate={fill_rate:.0%}, increasing max entry from {current_max}c to {new_max}c"
            decision = "PARAMS ADJUSTED"
            adjustments.append(decision)
            log.info(f"  🔧 ADJUSTING {strat}: {reason}")
        
        # Rule 4: Fill rate > 50% and PnL positive → Keep as-is (good strategy)
        if fill_rate > 0.50 and live.get("total_exposure_cents", 0) > 0:
            log.info(f"  ✅ {strat}: Fill rate={fill_rate:.0%}, exposure={live['total_exposure_cents']}c — KEEP")
        
        # Save adjustment to DB
        if old_enabled != new_enabled or decision != "No change":
            conn.execute("INSERT INTO strategy_adjustments VALUES (?,?,?,?,?)",
                (int(time.time()), strat,
                 json.dumps({"enabled": old_enabled, "params": cfg_data["params"]} if decision != "PARAMS ADJUSTED" else {}),
                 json.dumps({"enabled": new_enabled, "params": cfg_data["params"]}),
                 reason))
            conn.commit()
        
        # Update config in memory
        cfg_data["enabled"] = new_enabled
        cfg_data["performance"] = {
            "last_wr": bt_wr,
            "last_pnl": bt_pnl,
            "last_n": bt_n,
            "last_check": int(time.time()),
        }
    
    return adjustments


def main_loop():
    conn = init_db()
    config = load_config()
    
    log.info("=" * 70)
    log.info("SELF-IMPROVE AGENT — Auto-adjusting strategy parameters")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 70)
    
    cycle = 0
    while True:
        cycle += 1
        log.info(f"\n--- Self-Improve Cycle {cycle} ---")
        
        try:
            # Step 1: Evaluate backtest performance
            bt_results = evaluate_backtest_performance(conn)
            log.info(f"  Backtest Results:")
            for strat, stats in bt_results.items():
                log.info(f"    {strat}: WR={stats['wr']:.0%} PnL={stats['pnl']:+.0f}c N={stats['n']:.0f}")
            
            # Step 2: Evaluate live performance
            live_results = evaluate_live_performance(conn)
            log.info(f"  Live Results:")
            for strat, stats in live_results.items():
                log.info(f"    {strat}: fill_rate={stats['fill_rate']:.0%} orders={stats['total_orders']} exposure={stats['total_exposure_cents']}c")
            
            # Step 3: Make adjustments
            adjustments = make_adjustments(conn, bt_results, live_results, config)
            if adjustments:
                log.info(f"  Made {len(adjustments)} adjustments: {', '.join(adjustments)}")
            else:
                log.info(f"  No adjustments needed")
            
            # Step 4: Save updated config
            save_config(config)
            
            log.info(f"  Strategy config saved")
        except Exception as e:
            log.error(f"  Self-improve error: {e}")
        
        # Run every 5 minutes
        time.sleep(300)


if __name__ == "__main__":
    main_loop()
