#!/usr/bin/env python3
"""
Arbitrage + Copy Trading main entry point.

Runs three parallel strategies:
  1. Cross-platform arb (Kalshi ↔ Polymarket)
  2. Polymarket copy trading (follow profitable wallets)
  3. Kalshi near-zero accumulation + category specialist

Usage:
    python arb_main.py               # run all strategies
    python arb_main.py --scan        # dry-run scan only, print opportunities
    python arb_main.py --arb-only    # arbitrage only
    python arb_main.py --copy-only   # copy trading only

Required env vars:
    KALSHI_API_KEY_ID      Kalshi key ID
    KALSHI_API_KEY_FILE    path to Kalshi RSA private key PEM
    POLY_API_KEY           Polymarket API key
    POLY_API_SECRET        Polymarket API secret
    POLY_API_PASSPHRASE    Polymarket API passphrase

Polymarket credentials derived from your Polygon wallet via py-clob-client:
    pip install py-clob-client
    python -c "from py_clob_client.clob_types import ApiCreds; ..."
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.logger import setup_logger
from core.metrics import MetricsServer, metrics
from core.risk_engine import RiskEngine, RiskConfig
from core.kelly_sizer import KellySizer

from kalshi.client import KalshiClient
from kalshi.wallet_analyzer import WalletAnalyzer
from kalshi.strategies.near_zero import NearZeroStrategy, NearZeroConfig
from kalshi.strategies.category_specialist import CategorySpecialistStrategy, CategorySpecialistConfig
from kalshi.executor import KalshiExecutor

from polymarket.client import PolymarketClient
from polymarket.wallet_scanner import WalletScanner
from polymarket.copy_trader import CopyTrader, CopyTraderConfig

from arb.market_matcher import MarketMatcher
from arb.arb_detector import ArbDetector
from arb.arb_executor import ArbExecutor


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

class _LogCfg:
    level = "INFO"
    file  = "logs/arb.log"
    max_file_size = 10485760
    backup_count  = 5


def _setup():
    setup_logger(_LogCfg())
    return logging.getLogger("trading")


# ---------------------------------------------------------------------------
# Strategy runners
# ---------------------------------------------------------------------------

def run_arb_cycle(arb_exec: ArbExecutor, kalshi_client, poly_client,
                  matcher: MarketMatcher, detector: ArbDetector) -> None:
    logger = logging.getLogger("trading")
    try:
        from kalshi.wallet_analyzer import WalletAnalyzer as KWA
        analyzer = KWA(kalshi_client)
        kalshi_markets = analyzer.fetch_all_markets()

        poly_markets = poly_client.get_markets(limit=200)

        results = arb_exec.run_scan_and_execute(
            kalshi_markets, poly_markets, matcher, detector, contracts_per_arb=5
        )
        filled = [r for r in results if r.both_legs_filled]
        logger.info("Arb cycle: %d opportunities, %d filled, $%.4f pnl",
                    len(results), len(filled),
                    sum(r.realized_pnl for r in filled))
    except Exception as e:
        logger.error("Arb cycle error: %s", e, exc_info=True)


def run_copy_cycle(copy_trader: CopyTrader) -> None:
    copy_trader.run_once()


def run_kalshi_cycle(kalshi_exec: KalshiExecutor, analyzer) -> None:
    logger = logging.getLogger("trading")
    try:
        markets = analyzer.fetch_all_markets()
        kalshi_exec.run_cycle(markets)
    except Exception as e:
        logger.error("Kalshi cycle error: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

def run_scan(kalshi_client, poly_client) -> None:
    from kalshi.wallet_analyzer import WalletAnalyzer as KWA
    analyzer = KWA(kalshi_client)
    scanner  = WalletScanner(poly_client)
    matcher  = MarketMatcher(min_similarity=0.50)
    detector = ArbDetector(min_profit_frac=0.005)

    print("\n=== CROSS-PLATFORM ARB SCAN ===\n")
    kalshi_markets = analyzer.fetch_all_markets()
    poly_markets   = poly_client.get_markets(limit=500)
    pairs = matcher.match(kalshi_markets, poly_markets)
    arb_opps = detector.find_cross_platform_arb(pairs)
    lag_opps = detector.find_price_lag(pairs)

    print(f"Matched {len(pairs)} market pairs\n")

    print(f"--- Cross-Platform Arb ({len(arb_opps)}) ---")
    for o in arb_opps[:10]:
        print(f"  {o.title[:45]:45s}  ROI={o.roi:.2%}  "
              f"Kalshi {o.kalshi_action.upper()} @ {o.kalshi_price:.3f}  "
              f"Poly {o.poly_action} @ {o.poly_price:.3f}  "
              f"match={o.match_score:.2f}")

    print(f"\n--- Price Lag ({len(lag_opps)}) ---")
    for o in lag_opps[:10]:
        print(f"  {o.title[:45]:45s}  gap={o.expected_profit_frac:.3f}  "
              f"match={o.match_score:.2f}")

    print("\n=== POLYMARKET TOP WALLETS ===\n")
    profiles = scanner.scan_leaderboard(top_n=100)
    print(f"Found {len(profiles)} viable wallets\n")
    for p in profiles[:15]:
        print(f"  {p.address[:12]}...  WR={p.win_rate:.1%}  "
              f"ROI={p.roi:.1%}  trades={p.total_trades}  "
              f"best={p.best_category or '—'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Arb + copy trading bot")
    parser.add_argument("--scan",      action="store_true", help="Dry-run scan only")
    parser.add_argument("--arb-only",  action="store_true", help="Run arb only")
    parser.add_argument("--copy-only", action="store_true", help="Run copy trading only")
    parser.add_argument("--dry-run",   action="store_true", default=True,
                        help="Dry-run mode (default on)")
    parser.add_argument("--live",      action="store_true",
                        help="Enable live order execution (disables dry-run)")
    args = parser.parse_args()

    logger = _setup()
    dry_run = not args.live

    if dry_run:
        logger.info("DRY-RUN mode — no real orders will be placed")
    else:
        logger.warning("LIVE mode — real money at risk")

    # Clients
    demo_kalshi = os.getenv("KALSHI_DEMO", "true").lower() != "false"
    kalshi  = KalshiClient(demo=demo_kalshi)
    poly    = PolymarketClient()

    if args.scan:
        run_scan(kalshi, poly)
        return

    # Metrics
    try:
        MetricsServer(port=8002).start()
        logger.info("Metrics on :8002/metrics")
    except Exception as e:
        logger.warning("Metrics server failed: %s", e)

    # Arb components
    matcher  = MarketMatcher(min_similarity=0.50)
    detector = ArbDetector(min_profit_frac=0.005)
    arb_exec = ArbExecutor(kalshi, poly, max_usdc_per_arb=100.0,
                            min_profit_usdc=0.10, dry_run=dry_run)

    # Kalshi components
    k_analyzer = WalletAnalyzer(kalshi)
    kalshi_strategies = [
        NearZeroStrategy(kalshi, k_analyzer, NearZeroConfig()),
        CategorySpecialistStrategy(kalshi, k_analyzer, CategorySpecialistConfig()),
    ]
    kalshi_exec = KalshiExecutor(kalshi, kalshi_strategies)

    # Copy trader
    scanner = WalletScanner(poly)
    copy_cfg = CopyTraderConfig(usdc_per_trade=5.0, dry_run=True) if dry_run else CopyTraderConfig()

    # Patch dry_run into config
    copy_cfg_real = CopyTraderConfig(
        usdc_per_trade=5.0 if dry_run else 10.0,
        max_trade_usdc=20.0 if dry_run else 50.0,
    )
    copy_trader = CopyTrader(poly, scanner, copy_cfg_real)
    copy_trader.load_top_wallets(top_n=10)

    # Graceful shutdown
    running = True
    def _stop(sig, frame):
        nonlocal running
        logger.info("Shutdown signal received")
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    ARB_INTERVAL  = 120   # arb scan every 2 minutes
    COPY_INTERVAL = 10    # copy check every 10 seconds
    KALSHI_INTERVAL = 60  # Kalshi strategies every minute

    last_arb    = 0.0
    last_copy   = 0.0
    last_kalshi = 0.0

    logger.info("Bot started — arb=%s copy=%s kalshi=%s",
                not args.copy_only, not args.arb_only, True)

    while running:
        now = time.time()

        if not args.copy_only and now - last_arb >= ARB_INTERVAL:
            run_arb_cycle(arb_exec, kalshi, poly, matcher, detector)
            last_arb = now

        if not args.arb_only and now - last_copy >= COPY_INTERVAL:
            run_copy_cycle(copy_trader)
            last_copy = now

        if now - last_kalshi >= KALSHI_INTERVAL:
            run_kalshi_cycle(kalshi_exec, k_analyzer)
            last_kalshi = now

        time.sleep(1)

    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
