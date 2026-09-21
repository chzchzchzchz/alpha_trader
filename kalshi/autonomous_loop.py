#!/usr/bin/env python3
"""
Autonomous Trading Loop — Ralph Loop PRD implementation.

Continuous cycle:
- Reconciliation
- Auto-sales
- Market fetch + signal generation
- Capital allocation with risk manager
- Order placement
- Logging and metrics
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from kalshi.client import KalshiClient
from kalshi.wallet_analyzer import WalletAnalyzer
from kalshi.orchestrator import StrategyOrchestrator
from kalshi.auto_sales import AutoSalesEngine
from kalshi.reconciliation import Reconciliation
from kalshi.risk_manager import RiskManager
from core.panic_switch import PanicSwitch, KillSwitch

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

METRICS_LOG = LOG_DIR / "metrics.jsonl"

DB_PATH = Path(os.getenv("ALPHA_TRADER_DB", BASE_DIR / "data" / "alpha_trader.db"))
DB_PATH.parent.mkdir(exist_ok=True)

KALSHI_DEMO = os.getenv("KALSHI_DEMO", "true").lower() == "true"
CYCLE_INTERVAL = int(os.getenv("CYCLE_INTERVAL", "60"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER", "5"))
CIRCUIT_BREAKER_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "300"))

# ── Logging Setup ─────────────────────────────────────────────────────────────

logger = logging.getLogger("autonomy")
logger.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logger.addHandler(ch)

fh = RotatingFileHandler(
    LOG_DIR / "autonomous_loop.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(filename)s:%(lineno)d] %(message)s"))
logger.addHandler(fh)

# ── Circuit Breaker ────────────────────────────────────────────────────────────

class CircuitBreaker:
    def __init__(self, threshold: int, timeout: int):
        self.threshold = threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure = 0.0
        self.open = False

    def record_success(self):
        self.failures = 0
        self.open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            self.open = True
            logger.warning("Circuit breaker opened after %d failures", self.failures)

    def check(self) -> bool:
        if self.open:
            elapsed = time.time() - self.last_failure
            if elapsed >= self.timeout:
                self.open = False
                self.failures = 0
                logger.info("Circuit breaker half-open after %ds", elapsed)
                return True
            return False
        return True

circuit = CircuitBreaker(CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT)
kill_switch = KillSwitch(failure_threshold=5, window_seconds=60)
panic_switch = PanicSwitch(None, None)  # initialized after DB Conn

# ── Shutdown Handling ──────────────────────────────────────────────────────────

shutdown_flag = False
def signal_handler(sig, frame):
    global shutdown_flag
    logger.info("Received signal %d, finishing current cycle then shutting down", sig)
    shutdown_flag = True
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ── Database Initialization ────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        strategy TEXT NOT NULL,
        ticker TEXT NOT NULL,
        side TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        contracts INTEGER NOT NULL,
        order_id TEXT,
        status TEXT,
        demo INTEGER DEFAULT 1,
        closing_trade TEXT,
        exit_ts INTEGER,
        exit_price_cents INTEGER,
        exit_status TEXT,
        pnl_cents INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
    CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
    CREATE INDEX IF NOT EXISTS idx_trades_open ON trades(exit_ts);

    CREATE TABLE IF NOT EXISTS positions (
        ticker TEXT PRIMARY KEY,
        strategy TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price_cents INTEGER NOT NULL,
        contracts INTEGER NOT NULL,
        entry_ts INTEGER NOT NULL,
        order_id TEXT,
        status TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        strategy TEXT NOT NULL,
        ticker TEXT NOT NULL,
        side TEXT NOT NULL,
        price REAL NOT NULL,
        score REAL NOT NULL,
        edge REAL NOT NULL
    );
    """)
    conn.commit()

# ── Main Cycle ─────────────────────────────────────────────────────────────────

def run_cycle(
    client: KalshiClient,
    analyzer: WalletAnalyzer,
    orchestrator: StrategyOrchestrator,
    auto_sales: AutoSalesEngine,
    recon: Reconciliation,
    conn: sqlite3.Connection,
    metrics_log: str,
) -> dict:
    start = time.time()
    metrics = {"start_ts": int(start), "success": False}

    try:
        # 1. Reconciliation
        recon_result = recon.reconcile_all()
        metrics["reconciliation"] = {
            "balance": recon_result.get("balance_cents", 0),
            "positions": recon_result.get("positions_count", 0),
            "mismatches": len(recon_result.get("missing_local", [])) + len(recon_result.get("missing_remote", [])) + len(recon_result.get("amount_discrepancies", [])),
        }

        # 2. Auto-sales
        exit_signals = auto_sales.scan_positions()
        metrics["exit_signals"] = len(exit_signals)
        executed_exits = auto_sales.execute_exits(exit_signals)
        metrics["executed_exits"] = executed_exits

        # 3. Fetch markets
        markets = analyzer.fetch_all_markets()
        metrics["markets_fetched"] = len(markets)

        # 4. Generate signals
        signals = orchestrator.generate_signals(markets)
        metrics["raw_signals"] = len(signals)

        # Filter out tickers we already hold (avoid doubling)
        cur = conn.cursor()
        cur.execute("SELECT ticker FROM positions WHERE status != 'closed'")
        held = {row[0] for row in cur.fetchall()}
        signals = [s for s in signals if s.ticker not in held]
        metrics["signals_after_filter"] = len(signals)

        # Log signals to DB
        for sig in signals[:20]:
            cur.execute("""
                INSERT INTO signals (ts, strategy, ticker, side, price, score, edge)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (int(time.time()), sig.strategy, sig.ticker, sig.side, sig.price, sig.score, sig.edge))
        conn.commit()

        # 5. Allocate capital with risk manager
        risk = RiskManager(orchestrator)
        allocations = orchestrator.allocate_capital(signals, orchestrator.capital, risk_manager=risk)
        metrics["allocations"] = len(allocations)

        # 6. Place orders
        executed = 0
        for ticker, alloc in allocations.items():
            if alloc["side"] == "yes":
                price_cents = int(alloc["price"] * 100)
            else:
                price_cents = int((1.0 - alloc["price"]) * 100)
            price_cents = max(1, price_cents)
            for attempt in range(MAX_RETRIES):
                try:
                    resp = client.place_order(
                        ticker=ticker,
                        action="buy",
                        side=alloc["side"],
                        count=alloc["contracts"],
                        type="limit",
                        yes_price=price_cents if alloc["side"] == "yes" else None,
                        no_price=price_cents if alloc["side"] == "no" else None,
                        client_order_id=f"ord-{int(time.time())}-{hash(ticker)%10000}",
                    )
                    order = resp.get("order", {})
                    oid = order.get("order_id", "unknown")
                    status = order.get("status", "unknown")
                    cur.execute("""
                        INSERT INTO trades (ts, strategy, ticker, side, price_cents, contracts, order_id, status, demo)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(time.time()),
                        alloc["strategy"],
                        ticker,
                        alloc["side"],
                        price_cents,
                        alloc["contracts"],
                        oid,
                        status,
                        1 if KALSHI_DEMO else 0,
                    ))
                    cur.execute("""
                        INSERT OR REPLACE INTO positions
                        (ticker, strategy, side, entry_price_cents, contracts, entry_ts, order_id, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ticker,
                        alloc["strategy"],
                        alloc["side"],
                        price_cents,
                        alloc["contracts"],
                        int(time.time()),
                        oid,
                        status,
                    ))
                    executed += 1
                    logger.info("Order: %s %s %d @ %d¢ oid=%s", ticker, alloc["side"], alloc["contracts"], price_cents, oid)
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        logger.error("Failed to place order for %s after %d attempts: %s", ticker, MAX_RETRIES, e)
                        circuit.record_failure()
                    else:
                        time.sleep(2 ** attempt)
        conn.commit()
        metrics["executed_orders"] = executed

        # 7. Count open positions
        cur.execute("SELECT COUNT(*) FROM positions WHERE status != 'closed'")
        metrics["open_positions"] = cur.fetchone()[0]

        metrics["success"] = True
        circuit.record_success()

    except Exception as e:
        logger.exception("Cycle failed with unhandled exception")
        circuit.record_failure()
        metrics["error"] = str(e)

    finally:
        metrics["cycle_time"] = time.time() - start
        metrics["end_ts"] = int(time.time())
        # Write metrics to log file (JSON lines)
        try:
            with open(metrics_log, 'a') as f:
                f.write(json.dumps(metrics) + '\n')
        except Exception:
            pass
        return metrics


def main():
    logger.info("=== ALPHA TRADER AUTONOMOUS LOOP STARTING ===")
    logger.info("Demo mode: %s", KALSHI_DEMO)
    logger.info("Cycle interval: %d seconds", CYCLE_INTERVAL)
    logger.info("DB: %s", DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    logger.info("Database initialized")

    client = KalshiClient(demo=KALSHI_DEMO)
    analyzer = WalletAnalyzer(client)
    swarm = None
    orchestrator = StrategyOrchestrator(
        client=client,
        analyzer=analyzer,
        swarm=swarm,
        capital=float(os.getenv("CAPITAL", "500.0")),
    )
    auto_sales = AutoSalesEngine(client, conn, orchestrator)
    recon = Reconciliation(client, conn)

    # Initialize panic switch with real client/DB
    panic_switch.client = client
    panic_switch.db_conn = conn

    logger.info("Loaded %d strategies: %s", len(orchestrator.strategies), list(orchestrator.strategies.keys()))

    cycle_count = 0
    while not shutdown_flag:
        # Check kill switch first
        if kill_switch.should_halt():
            logger.critical("Kill switch engaged — exiting")
            break

        # Check panic file
        panic_switch.check_trigger()
        if panic_switch.is_triggered():
            logger.warning("Panic mode active — no new orders will be placed")
            # Keep running exits/reconciliation? For now, break
            break

        if not circuit.check():
            logger.warning("Circuit breaker OPEN — sleeping %ds", CIRCUIT_BREAKER_TIMEOUT)
            time.sleep(CIRCUIT_BREAKER_TIMEOUT)
            continue

        cycle_count += 1
        logger.info("=== CYCLE %d START ===", cycle_count)

        try:
            metrics = run_cycle(client, analyzer, orchestrator, auto_sales, recon, conn, METRICS_LOG)
        except Exception as e:
            logger.exception("Cycle crashed")
            metrics = {"success": False, "error": str(e), "cycle_time": 0}
            kill_switch.record_failure()

        if metrics["success"]:
            logger.info(
                "Cycle %d OK: markets=%d signals=%d allocated=%d executed=%d open=%d exits=%d time=%.2fs",
                cycle_count,
                metrics.get("markets_fetched", 0),
                metrics.get("raw_signals", 0),
                metrics.get("allocations", 0),
                metrics.get("executed_orders", 0),
                metrics.get("open_positions", 0),
                metrics.get("executed_exits", 0),
                metrics["cycle_time"],
            )
            circuit.record_success()
            kill_switch.record_success()
        else:
            logger.error("Cycle %d FAILED: %s", cycle_count, metrics.get("error", "unknown"))
            circuit.record_failure()
            kill_switch.record_failure()

        elapsed = metrics["cycle_time"]
        sleep_time = max(1, CYCLE_INTERVAL - elapsed)
        logger.debug("Sleeping %.1f seconds", sleep_time)
        time.sleep(sleep_time)

    logger.info("Shutdown requested — exiting cleanly")
    conn.close()
    logger.info("Database closed")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — exiting")
    except Exception as e:
        logger.exception("Fatal error in main loop")
        sys.exit(1)
