#!/usr/bin/env python3
"""
Alpha Trader — Autonomous Kalshi Trading System

10 psychology-based strategies that exploit human behavior on prediction markets.
FIFA UT trading principles applied to Kalshi: snipe lazy makers, buy panic dips,
follow whales, fade overreactions, sleep-never.

Usage:
    python kalshi_main.py              # live trading (continuous loop)
    python kalshi_main.py --scan       # dry-run scan, print opportunities, no orders
    python kalshi_main.py --profile    # show category performance profile and exit

Environment variables required:
    KALSHI_API_KEY_ID      your Kalshi API key ID
    KALSHI_API_KEY_FILE    path to your RSA private key PEM file

Optional:
    KALSHI_DEMO=false      override demo mode from config
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from core.logger import setup_logger
from core.metrics import MetricsServer, metrics
from kalshi.client import KalshiClient
from kalshi.executor import KalshiExecutor
from kalshi.wallet_analyzer import WalletAnalyzer

# ── Original 6 strategies ─────────────────────────────────────────────
from kalshi.strategies.near_zero import NearZeroStrategy, NearZeroConfig
from kalshi.strategies.category_specialist import CategorySpecialistStrategy, CategorySpecialistConfig
from kalshi.strategies.convergence import ConvergenceStrategy, ConvergenceConfig
from kalshi.strategies.late_window import LateWindowStrategy, LateWindowConfig
from kalshi.strategies.flash_crash import FlashCrashStrategy
from kalshi.strategies.longshot import LongshotStrategy, LongshotConfig

# ── 4 NEW psychology-based strategies ─────────────────────────────────
from kalshi.strategies.panic_sniper import PanicSniperStrategy
from kalshi.strategies.time_sniper import TimeOfDaySniperStrategy
from kalshi.strategies.overreaction_reversal import OverreactionReversalStrategy
from kalshi.strategies.smart_money import SmartMoneyFollowerStrategy


def load_config(path: str = "kalshi_config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    raw = yaml.safe_load(p.read_text())

    # Expand ${VAR} references
    import re
    def expand(obj):
        if isinstance(obj, dict):
            return {k: expand(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [expand(v) for v in obj]
        if isinstance(obj, str):
            def sub(m):
                return os.getenv(m.group(1), "")
            return re.sub(r"\$\{([^}]+)\}", sub, obj)
        return obj

    return expand(raw)


def setup_logging(log_cfg: dict) -> None:
    class _Cfg:
        def __init__(self, d):
            self.level = d.get("level", "INFO")
            self.file = d.get("file", "logs/kalshi.log")
            self.max_file_size = d.get("max_file_size", 10485760)
            self.backup_count = d.get("backup_count", 5)
    setup_logger(_Cfg(log_cfg))


def build_strategies(cfg: dict, client: KalshiClient, analyzer: WalletAnalyzer) -> list:
    """Build all 10 trading strategies."""
    strategies = []
    strat_cfg = cfg.get("strategies", {})

    # 1. Near-Zero Accumulation
    nz = strat_cfg.get("near_zero", {})
    if nz.get("enabled", True):
        strategies.append(NearZeroStrategy(
            client, analyzer,
            NearZeroConfig(
                price_ceiling=nz.get("price_ceiling", 0.08),
                min_volume_24h=nz.get("min_volume_24h", 50),
                min_days_to_close=nz.get("min_days_to_close", 5),
                max_days_to_close=nz.get("max_days_to_close", 45),
                target_multiplier=nz.get("target_multiplier", 3.0),
                stop_loss_frac=nz.get("stop_loss_frac", 0.60),
                max_contracts=nz.get("max_contracts", 20),
                min_smart_money_vol=nz.get("min_smart_money_vol", 5),
            ),
        ))
        print("  [OK] 1. NearZero Accumulation")

    # 2. Category Specialist
    cs = strat_cfg.get("category_specialist", {})
    if cs.get("enabled", True):
        strategies.append(CategorySpecialistStrategy(
            client, analyzer,
            CategorySpecialistConfig(
                min_trades_per_category=cs.get("min_trades_per_category", 10),
                min_win_rate=cs.get("min_win_rate", 0.55),
                blacklist_win_rate=cs.get("blacklist_win_rate", 0.40),
                max_categories=cs.get("max_categories", 5),
                contracts_per_trade=cs.get("contracts_per_trade", 5),
                confidence_multiplier=cs.get("confidence_multiplier", 1.5),
            ),
        ))
        print("  [OK] 2. Category Specialist")

    # 3. 7-Filter Convergence
    cv = strat_cfg.get("convergence", {})
    if cv.get("enabled", True):
        strategies.append(ConvergenceStrategy(
            client, analyzer,
            capital=cfg.get("capital", {}).get("initial_balance", 500),
            config=ConvergenceConfig(
                min_price=int(cv.get("min_price", 60)),
                max_price=int(cv.get("max_price", 96)),
                max_days_to_close=cv.get("max_days_to_close", 14.0),
                min_volume=cv.get("min_volume", 500),
                max_spread=cv.get("max_spread", 5),
                max_cluster_fraction=cv.get("max_cluster_fraction", 0.25),
                base_position_pct=cv.get("base_position_pct", 0.005),
                max_contracts=cv.get("max_contracts", 10),
            ),
        ))
        print("  [OK] 3. 7-Filter Convergence")

    # 4. Late-Window Snipe
    lw = strat_cfg.get("late_window", {})
    if lw.get("enabled", True):
        strategies.append(LateWindowStrategy(
            client, analyzer,
            config=LateWindowConfig(
                snipe_window_seconds=lw.get("snipe_window_seconds", 90.0),
                snipe_threshold=lw.get("snipe_threshold", 93),
                max_open=lw.get("max_open", 3),
                trade_size_usdc=lw.get("trade_size_usdc", 10.0),
            ),
        ))
        print("  [OK] 4. Late-Window Snipe")

    # 5. Flash Crash Reversion
    fc = strat_cfg.get("flash_crash", {})
    if fc.get("enabled", True):
        strategies.append(FlashCrashStrategy(client, analyzer))
        print("  [OK] 5. Flash Crash Reversion")

    # 6. Longshot Diversification
    ls = strat_cfg.get("longshot", {})
    if ls.get("enabled", True):
        strategies.append(LongshotStrategy(client, analyzer))
        print("  [OK] 6. Longshot Diversification")

    # ─── NEW Psychology-Based Strategies ───────────────────────────────

    # 7. Panic Sniper - "Buy the Blood"
    ps = strat_cfg.get("panic_sniper", {})
    if ps.get("enabled", True):
        strategies.append(PanicSniperStrategy(client, analyzer, capital=500))
        print("  [OK] 7. Panic Sniper (Buy the Blood)")

    # 8. Time-of-Day Sniper - "3AM Snipe"
    ts = strat_cfg.get("time_sniper", {})
    if ts.get("enabled", True):
        strategies.append(TimeOfDaySniperStrategy(client, analyzer))
        print("  [OK] 8. Time-of-Day Sniper (3AM Snipe)")

    # 9. Overreaction Reversal - "Fade the Headline"
    orr = strat_cfg.get("overreaction_reversal", {})
    if orr.get("enabled", True):
        strategies.append(OverreactionReversalStrategy(client, analyzer, capital=500))
        print("  [OK] 9. Overreaction Reversal (Fade the Headline)")

    # 10. Smart Money Follower - "Follow the Whales"
    sm = strat_cfg.get("smart_money", {})
    if sm.get("enabled", True):
        strategies.append(SmartMoneyFollowerStrategy(client, analyzer))
        print("  [OK] 10. Smart Money Follower (Follow the Whales)")

    return strategies


def run_scan_mode(client: KalshiClient, analyzer: WalletAnalyzer, cfg: dict) -> None:
    """Print opportunities without placing orders."""
    print("\n=== KALSHI OPPORTUNITY SCAN ===\n")

    markets = analyzer.fetch_all_markets()
    print(f"Scanned {len(markets)} open markets\n")

    # Near-zero
    nz_cfg = cfg.get("strategies", {}).get("near_zero", {})
    opps = analyzer.find_near_zero_opportunities(
        markets,
        price_ceiling=nz_cfg.get("price_ceiling", 0.08),
        min_volume=nz_cfg.get("min_volume_24h", 50),
    )
    print(f"--- Near-Zero Opportunities ({len(opps)}) ---")
    for o in opps[:10]:
        print(f"  {o.ticker:40s}  {o.buy_side.upper()} @ {o.yes_price:.3f}  "
              f"score={o.score:.4f}  days={o.days_to_close:.1f}  smart_vol={o.smart_money_volume}")

    # Convergence (7-filter)
    cv_cfg = cfg.get("strategies", {}).get("convergence", {})
    if cv_cfg.get("enabled", True):
        cv = ConvergenceStrategy(client, analyzer,
            capital=cfg.get("capital", {}).get("initial_balance", 500),
            config=ConvergenceConfig(
                min_price=int(cv_cfg.get("min_price", 60)),
                max_price=int(cv_cfg.get("max_price", 96)),
                max_days_to_close=cv_cfg.get("max_days_to_close", 14.0),
                min_volume=cv_cfg.get("min_volume", 500),
                max_spread=cv_cfg.get("max_spread", 5),
            ),
        )
        cv_signals = cv.run_scan()
        print(f"\n--- Convergence Signals ({len(cv_signals)}) ---")
        for s in cv_signals[:10]:
            print(f"  {s['ticker']:40s}  {s['side'].upper()} @ {s['price']}  "
                  f"score={s['score']:.2f}  contracts={s['contracts']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpha Trader — Autonomous Kalshi Trading System")
    parser.add_argument("--scan", action="store_true", help="Dry-run scan only")
    parser.add_argument("--profile", action="store_true", help="Show performance profile and exit")
    parser.add_argument("--config", default="kalshi_config.yaml", help="Config file path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.get("logging", {}))
    logger = logging.getLogger("trading")

    kalshi_cfg = cfg.get("kalshi", {})
    demo = kalshi_cfg.get("demo", True)
    if os.getenv("KALSHI_DEMO", "").lower() == "false":
        demo = False

    client = KalshiClient(
        key_id=kalshi_cfg.get("key_id"),
        private_key_path=kalshi_cfg.get("key_file"),
        demo=demo,
    )
    analyzer = WalletAnalyzer(client)

    mode = "DEMO" if demo else "LIVE"
    logger.info("Alpha Trader starting — %s mode — 10 strategies", mode)
    print(f"\n{'='*60}")
    print(f"  Alpha Trader [{mode}] — 10 Psychology-Based Strategies")
    print(f"{'='*60}")

    if args.scan:
        run_scan_mode(client, analyzer, cfg)
        return

    strategies = build_strategies(cfg, client, analyzer)
    logger.info("Loaded %d strategies", len(strategies))
    print(f"\n  Loaded {len(strategies)} strategies")

    executor = KalshiExecutor(client, strategies)

    # Metrics server
    try:
        MetricsServer(port=8001).start()
        logger.info("Metrics on :8001/metrics")
    except Exception as e:
        logger.warning("Metrics server failed: %s", e)

    running = True
    def _stop(sig, frame):
        nonlocal running
        logger.info("Shutting down...")
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    interval = cfg.get("schedule", {}).get("polling_interval", 60)
    refresh_interval = cfg.get("schedule", {}).get("category_refresh_interval", 3600)
    last_refresh = 0.0

    cap_cfg = cfg.get("capital", {})
    max_daily_loss = cap_cfg.get("max_daily_loss", 50)
    daily_loss = 0.0

    logger.info("Main loop — polling every %ds", interval)
    print(f"\n  Main loop: polling every {interval}s")
    print(f"  Daily loss circuit breaker: ${max_daily_loss}")
    print(f"  Press Ctrl+C to stop\n")

    cycle_count = 0
    while running:
        now = time.time()
        cycle_count += 1

        # Periodic category profile refresh
        if now - last_refresh > refresh_interval:
            for s in strategies:
                if hasattr(s, "refresh_performance_profile"):
                    s.refresh_performance_profile()
            last_refresh = now

        # Daily loss circuit breaker
        if daily_loss >= max_daily_loss:
            logger.warning("Daily loss limit $%.2f reached — pausing", daily_loss)
            print(f"\n  [CIRCUIT BREAKER] Daily loss ${daily_loss:.2f} — pausing\n")
            time.sleep(interval)
            continue

        try:
            markets = analyzer.fetch_all_markets()
            executor.run_cycle(markets, external_signals=None)
            metrics.set("markets_scanned", len(markets))
            metrics.set("cycle_count", cycle_count)

            # Status line every cycle
            total_positions = sum(s.active_positions() for s in strategies if hasattr(s, "active_positions"))
            print(f"  [Cycle {cycle_count}] Markets: {len(markets)} | Positions: {total_positions} | P&L: ${daily_loss:.2f}", flush=True)

        except Exception as e:
            logger.error("Cycle error: %s", e, exc_info=True)
            print(f"\n  [ERROR] {e}\n", flush=True)

        time.sleep(interval)

    logger.info("Shutdown complete after %d cycles", cycle_count)
    print(f"\n  Shutdown complete — {cycle_count} cycles executed")


if __name__ == "__main__":
    main()
