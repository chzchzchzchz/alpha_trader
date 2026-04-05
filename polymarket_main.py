#!/usr/bin/env python3
"""
Polymarket Bot — unified entry point.

Runs all Polymarket strategies:
  1. Flash crash / mean reversion    (discountry approach)
  2. 7-filter convergence            (dylanpersonguy approach)
  3. Longshot diversification        (Emil-Ka / mispricer approach)
  4. Late-window snipe               (LuciferForge approach)
  5. Copy trading                    (whale wallet following)
  6. LLM-forecasted smart longshots  (yigitcankzl / polyswarm approach)

Usage:
    python polymarket_main.py              # run all strategies (dry-run default)
    python polymarket_main.py --live       # enable real orders
    python polymarket_main.py --scan       # scan and print opportunities only
    python polymarket_main.py --strategy flash_crash  # run one strategy only
    python polymarket_main.py --copy-only  # copy trading only

Required env vars (see core/startup.py for full list):
    POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE  (for live trading)
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                (for alerts)
    OPENROUTER_API_KEY  or  OPENAI_API_KEY              (for LLM forecasting)
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.logger import setup_logger
from core.metrics import MetricsServer, metrics
from core.notifier import make_notifier
from core.startup import validate_environment, start_health_server, update_health
from core.llm_forecaster import LLMForecaster
from core.risk_engine import RiskEngine, RiskConfig

from polymarket.client import PolymarketClient
from polymarket.wallet_scanner import WalletScanner
from polymarket.copy_trader import CopyTrader, CopyTraderConfig
from polymarket.strategies.flash_crash import FlashCrashMonitor, FlashCrashStrategy
from polymarket.strategies.convergence import ConvergenceStrategy, ConvergenceConfig
from polymarket.strategies.longshot import LongshotStrategy, LongshotConfig
from polymarket.strategies.late_window import LateWindowStrategy, LateWindowConfig


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _LogCfg:
    level = "INFO"
    file  = "logs/polymarket.log"
    max_file_size = 10485760
    backup_count  = 5


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

def run_scan(client: PolymarketClient, scanner: WalletScanner,
             forecaster: LLMForecaster) -> None:
    print("\n=== POLYMARKET OPPORTUNITY SCAN ===\n")
    markets = client.get_markets(limit=300)
    print(f"Fetched {len(markets)} markets\n")

    # Convergence
    conv = ConvergenceStrategy(client, capital=500)
    sigs = conv.scan(markets)
    print(f"--- Convergence Signals ({len(sigs)}) ---")
    for s in sigs[:8]:
        print(f"  {s.question[:50]:50s}  {s.side}  price={s.current_price:.3f}  "
              f"score={s.setup_score:.2f}  days={s.days_to_resolution:.1f}")

    # Longshot
    ls = LongshotStrategy(client)
    ls_sigs = ls.scan(markets)
    print(f"\n--- Longshot Opportunities ({len(ls_sigs)}) ---")
    for s in ls_sigs[:10]:
        payout = f"{1/s.market_price:.0f}x" if s.market_price > 0 else "∞"
        print(f"  {s.question[:50]:50s}  {s.side}  @ {s.market_price:.3f}  payout={payout}")

    # Top wallets
    print(f"\n--- Top Wallets ---")
    profiles = scanner.scan_leaderboard(top_n=50)
    for p in profiles[:10]:
        print(f"  {p.address[:14]}...  WR={p.win_rate:.1%}  ROI={p.roi:.1%}  "
              f"trades={p.total_trades}  best_cat={p.best_category or '—'}")

    # LLM spot-check on first convergence signal
    if sigs and forecaster:
        s = sigs[0]
        print(f"\n--- LLM Forecast: {s.question[:50]} ---")
        result = forecaster.estimate(s.question, s.current_price)
        if result:
            print(f"  Market: {s.current_price:.1%}  |  Model (calibrated): {result.calibrated:.1%}  "
                  f"|  Edge: {result.edge:+.1%}")
            for model, est in result.model_estimates.items():
                print(f"    {model.split('/')[-1]:30s}  {est:.1%}")


# ---------------------------------------------------------------------------
# Strategy runner
# ---------------------------------------------------------------------------

class PolymarketBot:
    def __init__(self, client: PolymarketClient, dry_run: bool = True,
                 strategies: list[str] | None = None):
        self.client  = client
        self.dry_run = dry_run
        self.active  = set(strategies or ["flash_crash", "convergence",
                                          "longshot", "late_window",
                                          "copy_trading"])
        self.notifier   = make_notifier()
        self.forecaster = LLMForecaster()
        self.risk       = RiskEngine(RiskConfig(), initial_capital=500.0)
        self.scanner    = WalletScanner(client)

        # Strategies
        self.flash_monitor = FlashCrashMonitor(client)
        self.flash_strat   = FlashCrashStrategy(client, self.flash_monitor)
        self.convergence   = ConvergenceStrategy(client, capital=500.0)
        self.longshot      = LongshotStrategy(
            client,
            probability_estimator=self._llm_estimate if self.forecaster else None,
        )
        self.late_window   = LateWindowStrategy(client)
        self.copy_trader   = CopyTrader(client, self.scanner,
                                         CopyTraderConfig(usdc_per_trade=5.0))

        self._running = False
        self._trades_today = 0
        self._daily_pnl    = 0.0

    def start(self) -> None:
        self._running = True

        # Auto-load top wallets for copy trading
        if "copy_trading" in self.active:
            self.copy_trader.load_top_wallets(top_n=10)

        # Load flash crash watchlist
        if "flash_crash" in self.active:
            self.flash_strat.load_active_markets(limit=50)

        strat_list = list(self.active)
        self.notifier.startup(
            "DRY-RUN" if self.dry_run else "LIVE", strat_list
        )
        update_health("strategies", strat_list)
        update_health("dry_run", self.dry_run)
        logging.getLogger("trading").info(
            "Polymarket bot started — strategies=%s dry_run=%s",
            strat_list, self.dry_run,
        )

    def stop(self) -> None:
        self._running = False
        self.notifier.daily_summary(
            pnl=self._daily_pnl,
            trades=self._trades_today,
            win_rate=0.0,
            equity=500.0 + self._daily_pnl,
        )

    def run_cycle(self) -> None:
        markets = self.client.get_markets(limit=300)
        metrics.set("poly_markets_fetched", len(markets))

        # --- Flash crash ---
        if "flash_crash" in self.active:
            orders = self.flash_strat.run_cycle()
            for oid in orders:
                self._trades_today += 1
                metrics.inc("poly_trades_total", labels={"strategy": "flash_crash"})

        # --- Convergence ---
        if "convergence" in self.active:
            signals = self.convergence.scan(markets)
            for sig in signals[:3]:  # cap to avoid overtrading
                size = self.convergence.position_size_usdc(sig)
                approved, gates = self.risk.check_trade(
                    market_id=sig.market_id,
                    category="poly",
                    entry_price=sig.current_price,
                    win_rate=sig.setup_score,
                    usdc_size=size,
                    volume_24h=int(sig.volume_24h),
                )
                if approved:
                    self.notifier.signal("convergence", sig.question,
                                         sig.current_price - 0.5, sig.current_price, size)
                    if not self.dry_run:
                        try:
                            self.client.place_market_order(sig.token_id, sig.side, size)
                            self.convergence.record_open(sig, size)
                            self._trades_today += 1
                        except Exception as e:
                            self.notifier.error("convergence", str(e))

        # --- Longshot ---
        if "longshot" in self.active:
            ls_sigs = self.longshot.scan(markets)
            for sig in ls_sigs[:10]:
                if not self.dry_run:
                    self.longshot.execute(sig)
                    self._trades_today += 1
                else:
                    logging.getLogger("trading").info(
                        "[DRY-RUN] Longshot: %s %s @ %.3f",
                        sig.question[:40], sig.side, sig.market_price,
                    )
            self.longshot.check_take_profits()

        # --- Late window ---
        if "late_window" in self.active:
            entry_sigs = self.late_window.scan_for_entries(markets)
            trigger_sigs = self.late_window.check_trigger_watchlist()
            for sig in entry_sigs + trigger_sigs:
                if not self.dry_run:
                    self.late_window.execute(sig)
                    self._trades_today += 1
                else:
                    logging.getLogger("trading").info(
                        "[DRY-RUN] LateWindow [%s]: %s @ %.3f %.0fs to close",
                        sig["mode"], sig["title"][:35], sig["price"],
                        sig.get("seconds_to_close", 0),
                    )
            self.late_window.expire_positions()

        # --- Copy trading ---
        if "copy_trading" in self.active:
            copied = self.copy_trader.run_once()
            for trade in copied:
                self._trades_today += 1
                self.notifier.trade(
                    "copy_trading", trade.token_id[:12],
                    trade.side, trade.price, trade.amount_usdc,
                )

        update_health("trades_today", self._trades_today)
        update_health("daily_pnl", self._daily_pnl)
        metrics.set("poly_daily_pnl", self._daily_pnl)
        metrics.set("poly_trades_today", self._trades_today)

    def _llm_estimate(self, question: str) -> float:
        """Probability estimator hook for LongshotStrategy."""
        result = self.forecaster.estimate(question, market_price=0.05)
        return result.calibrated if result else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket trading bot")
    parser.add_argument("--scan",      action="store_true", help="Scan and print only")
    parser.add_argument("--live",      action="store_true", help="Enable real orders")
    parser.add_argument("--strategy",  default=None,
                        choices=["flash_crash", "convergence", "longshot",
                                 "late_window", "copy_trading"],
                        help="Run a single strategy")
    parser.add_argument("--copy-only", action="store_true")
    parser.add_argument("--interval",  type=int, default=30,
                        help="Polling interval in seconds (default 30)")
    args = parser.parse_args()

    setup_logger(_LogCfg())
    logger = logging.getLogger("trading")

    # Validate env — non-fatal for optional vars
    validate_environment(required_groups=["polymarket", "telegram", "llm"],
                         exit_on_failure=False)

    dry_run = not args.live
    client  = PolymarketClient()
    scanner = WalletScanner(client)

    if args.scan:
        forecaster = LLMForecaster()
        run_scan(client, scanner, forecaster)
        return

    # Metrics + health
    try:
        MetricsServer(port=8003).start()
    except Exception as e:
        logger.warning("Metrics server failed: %s", e)
    start_health_server(port=8081)

    active_strategies = None
    if args.strategy:
        active_strategies = [args.strategy]
    elif args.copy_only:
        active_strategies = ["copy_trading"]

    bot = PolymarketBot(client, dry_run=dry_run, strategies=active_strategies)
    bot.start()

    running = True
    def _stop(sig, frame):
        nonlocal running
        running = False
        bot.stop()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    interval = args.interval
    logger.info("Bot running — interval=%ds dry_run=%s", interval, dry_run)

    while running:
        try:
            bot.run_cycle()
        except Exception as e:
            logger.error("Cycle error: %s", e, exc_info=True)
            bot.notifier.error("main_loop", str(e))
        time.sleep(interval)

    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
