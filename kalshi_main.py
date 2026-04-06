#!/usr/bin/env python3
"""
Kalshi Bot — main entry point.

Usage:
    python kalshi_main.py              # live trading
    python kalshi_main.py --scan       # dry-run scan, print opportunities, no orders
    python kalshi_main.py --profile    # show category performance profile and exit

Environment variables required:
    KALSHI_API_KEY_ID      your Kalshi API key ID
    KALSHI_API_KEY_FILE    path to your RSA private key PEM file

Optional:
    ENV=production         set to production to use real money endpoint
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
from kalshi.strategies.near_zero import NearZeroStrategy, NearZeroConfig
from kalshi.strategies.category_specialist import CategorySpecialistStrategy, CategorySpecialistConfig
from kalshi.strategies.convergence import ConvergenceStrategy, ConvergenceConfig
from kalshi.strategies.late_window import LateWindowStrategy, LateWindowConfig
from kalshi.strategies.flash_crash import FlashCrashStrategy
from kalshi.strategies.longshot import LongshotStrategy, LongshotConfig


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
                val = os.getenv(m.group(1), "")
                if not val:
                    raise ValueError(f"Environment variable '{m.group(1)}' not set")
                return val
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
    strategies = []
    strat_cfg = cfg.get("strategies", {})

    if strat_cfg.get("near_zero", {}).get("enabled", True):
        nz = strat_cfg["near_zero"]
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

    if strat_cfg.get("category_specialist", {}).get("enabled", True):
        cs = strat_cfg["category_specialist"]
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

    if strat_cfg.get("convergence", {}).get("enabled", True):
        cv = strat_cfg["convergence"]
        strategies.append(ConvergenceStrategy(
            client, analyzer,
            capital=cap_cfg.get("initial_balance", 500),
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

    if strat_cfg.get("late_window", {}).get("enabled", True):
        lw = strat_cfg["late_window"]
        strategies.append(LateWindowStrategy(
            client, analyzer,
            config=LateWindowConfig(
                snipe_window_seconds=lw.get("snipe_window_seconds", 90.0),
                snipe_threshold=lw.get("snipe_threshold", 93),
                max_open=lw.get("max_open", 3),
                trade_size_usdc=lw.get("trade_size_usdc", 10.0),
            ),
        ))

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
            print(f"  {s['ticker']:40s}  {s['side'].upper()} @ {s['price_cents']}c  "
                  f"score={s['score']:.2f}  contracts={s['contracts']}")

    # Late-window
    lw_cfg = cfg.get("strategies", {}).get("late_window", {})
    if lw_cfg.get("enabled", True):
        lw = LateWindowStrategy(client, analyzer,
            config=LateWindowConfig(
                snipe_window_seconds=lw_cfg.get("snipe_window_seconds", 90.0),
                snipe_threshold=lw_cfg.get("snipe_threshold", 93),
            ),
        )
        lw_signals = lw.run_scan()
        print(f"\n--- Late-Window Signals ({len(lw_signals)}) ---")
        for s in lw_signals[:10]:
            print(f"  {s['ticker']:40s}  {s['side'].upper()} @ {s['price_cents']}c  "
                  f"mode={s['mode']}  closes_in={s.get('seconds_to_close',0):.0f}s")

    # Category stats
    print("\n--- Category Stats ---")
    cat_stats = analyzer.detect_category_patterns(markets)
    for cat, stats in sorted(cat_stats.items(), key=lambda x: x[1]["market_count"], reverse=True)[:10]:
        print(f"  {cat:20s}  markets={stats['market_count']:3d}  "
              f"contested={stats['contested_markets']:3d}  near_zero={stats['near_zero_markets']:3d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi trading bot")
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
    logger.info("Kalshi bot starting — %s mode", mode)
    print(f"\nKalshi Bot [{mode}]")

    if args.scan:
        run_scan_mode(client, analyzer, cfg)
        return

    strategies = build_strategies(cfg, client, analyzer)
    logger.info("Loaded %d strategies", len(strategies))

    # Refresh category profile at startup
    for s in strategies:
        if hasattr(s, "refresh_performance_profile"):
            s.refresh_performance_profile()

    if args.profile:
        for s in strategies:
            if hasattr(s, "_category_perf"):
                print("\n--- Category Performance Profile ---")
                for cat, perf in sorted(s._category_perf.items(),
                                        key=lambda x: x[1].win_rate, reverse=True):
                    if perf.trade_count >= 3:
                        print(f"  {cat:20s}  WR={perf.win_rate:.1%}  "
                              f"trades={perf.trade_count}  pnl=${perf.total_pnl:.2f}")
        return

    executor = KalshiExecutor(client, strategies)

    # Metrics server
    try:
        MetricsServer(port=8001).start()
        logger.info("Metrics on :8001/metrics")
    except Exception as e:
        logger.warning("Metrics server failed to start: %s", e)

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

    logger.info("Main loop started — polling every %ds", interval)

    while running:
        now = time.time()

        # Periodic category profile refresh
        if now - last_refresh > refresh_interval:
            for s in strategies:
                if hasattr(s, "refresh_performance_profile"):
                    s.refresh_performance_profile()
            last_refresh = now

        # Daily loss circuit breaker
        if daily_loss >= max_daily_loss:
            logger.warning("Daily loss limit $%.2f reached — pausing", max_daily_loss)
            time.sleep(interval)
            continue

        try:
            markets = analyzer.fetch_all_markets()
            executor.run_cycle(markets, external_signals=None)
            metrics.set("markets_scanned", len(markets))
        except Exception as e:
            logger.error("Cycle error: %s", e, exc_info=True)

        time.sleep(interval)

    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
