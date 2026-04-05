"""
TradingSystem — wires together all components and drives the main event loop.
"""
from __future__ import annotations

import time
import logging
from datetime import datetime, timezone

from core.broker import AlpacaBroker
from core.data_handler import DataHandler
from core.executor import TradeExecutor
from core.logger import setup_logger
from core.metrics import metrics
from core.performance_tracker import PerformanceTracker
from core.scheduler import TradingScheduler
from core.strategy_manager import StrategyManager
from backtest.backtester import Backtester

logger = logging.getLogger("trading")


class TradingSystem:
    def __init__(self, settings):
        self.settings = settings
        self._running = False

        setup_logger(settings.logging)

        self.perf_tracker = PerformanceTracker(settings.capital.initial_equity)
        self.data_handler = DataHandler(settings)
        self.broker = AlpacaBroker(settings.alpaca)
        self.executor = TradeExecutor(
            broker=self.broker,
            perf_tracker=self.perf_tracker,
            risk_per_trade=settings.capital.risk_per_trade,
        )
        self.strategy_manager = StrategyManager(
            strategy_cfg=settings.strategies,
            data_handler=self.data_handler,
            perf_tracker=self.perf_tracker,
        )
        self.scheduler = TradingScheduler(settings.schedule)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_live(self) -> None:
        self._running = True
        interval = self.settings.schedule.polling_interval
        logger.info("Live trading started — polling every %ds", interval)

        while self._running:
            now = datetime.now(timezone.utc)
            if not self.scheduler.should_run(now):
                time.sleep(interval)
                continue

            if not self.broker.is_market_open():
                logger.debug("Market closed — waiting")
                time.sleep(interval)
                continue

            self._run_cycle(now)
            time.sleep(interval)

    def run_backtest(self) -> None:
        logger.info("Backtest started")
        backtester = Backtester(self.data_handler, self.settings)
        results: dict[str, dict] = {}

        for name, strategy in self.strategy_manager.strategies.items():
            result = backtester.run(strategy)
            results[name] = result
            logger.info(
                "Backtest %s — sharpe=%.2f win_rate=%.1f%% drawdown=%.1f%%",
                name,
                result["sharpe"],
                result["win_rate"] * 100,
                result["drawdown"] * 100,
            )
            metrics.set(f"backtest_sharpe", result["sharpe"], labels={"strategy": name})
            metrics.set(f"backtest_win_rate", result["win_rate"], labels={"strategy": name})
            metrics.set(f"backtest_drawdown", result["drawdown"], labels={"strategy": name})

        return results

    def stop(self) -> None:
        self._running = False
        logger.info("TradingSystem stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_cycle(self, now: datetime) -> None:
        for name, strategy in self.strategy_manager.strategies.items():
            if self.strategy_manager.should_kill_strategy(name):
                logger.warning("Strategy %s killed by risk manager", name)
                continue

            try:
                signal = strategy.generate_signal()
            except Exception as e:
                logger.error("Strategy %s signal error: %s", name, e, exc_info=True)
                metrics.inc("strategy_errors_total", labels={"strategy": name})
                continue

            if not signal or not signal.get("should_trade"):
                continue

            success = self.executor.execute_trade(signal, name)
            metrics.inc(
                "trades_total",
                labels={"strategy": name, "side": signal.get("side", "unknown")},
            )
            if success:
                metrics.inc("trades_filled_total", labels={"strategy": name})

        self.perf_tracker.update_daily_stats()
        equity = self.perf_tracker.get_account_snapshot()["equity"]
        metrics.set("equity", equity)
