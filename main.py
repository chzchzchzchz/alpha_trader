#!/usr/bin/env python3
import os, sys, time, signal
from datetime import datetime, timezone

from core.config           import Config, load_dotenv, check_config_hash, validate_config, SecretsManager, ChecksumVerifier
from core.logger           import setup_logger
from core.broker           import AlpacaBroker
from core.data_handler     import DataHandler
from core.strategy_manager import StrategyManager
from core.executor         import TradeExecutor
from core.scheduler        import TradingScheduler
from core.performance_tracker import PerformanceTracker
from backtest.backtester   import Backtester

class TradingSystem:
    def __init__(self, cfg_file='config.yaml'):
        self.cfg          = Config(cfg_file)
        self.logger       = setup_logger(self.cfg.logging)
        self.broker       = AlpacaBroker(self.cfg.alpaca)
        self.data_handler = DataHandler(self.cfg)
        self.perf         = PerformanceTracker()
        self.executor     = TradeExecutor(self.broker, self.perf, self.cfg.capital.risk_per_trade)
        self.manager      = StrategyManager(self.cfg.strategies, self.data_handler, self.perf)
        self.scheduler    = TradingScheduler(self.cfg.schedule)
        self.running      = True
        signal.signal(signal.SIGINT,  self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, *args):
        self.running = False

    def run_backtest(self):
        self.logger.info("=== Starting Backtests ===")
        backtester = Backtester(self.data_handler, self.cfg)
        for name in self.cfg.strategies.enabled:
            strat = self.manager.get_strategy(name)
            if not strat:
                self.logger.warning(f"{name} not found, skipping.")
                continue
            stats = backtester.run(strat)
            self.logger.info(
                f"[{name}] Sharpe: {stats['sharpe']:.2f} | "
                f"Win rate: {stats['win_rate']:.2%} | "
                f"Drawdown: {stats['drawdown']:.2%}"
            )
        self.logger.info("=== Backtests Complete ===")

    def run_live(self):
        self.logger.info("=== Entering Live Loop ===")
        while self.running:
            now = datetime.now(timezone.utc)
            if not self.scheduler.should_run(now):
                time.sleep(self.cfg.schedule.polling_interval)
                continue
            for name in self.cfg.strategies.enabled:
                strat = self.manager.get_strategy(name)
                if not strat or self.manager.should_kill_strategy(name):
                    continue
                sig = strat.generate_signal()
                if sig.get("should_trade"):
                    self.executor.execute_trade(sig, name)
            time.sleep(self.cfg.schedule.polling_interval)

def main():
    cfg = sys.argv[1] if len(sys.argv)>1 else 'config.yaml'
    system = TradingSystem(cfg)
    if system.cfg.mode == 'backtest':
        system.run_backtest()
    else:
        system.run_live()

if __name__ == "__main__":
    # Load .env
    load_dotenv()
    # Check config hash unless --override is present
    override = "--override" in sys.argv
    check_config_hash(override=override)
    # Validate config
    try:
        validate_config()
    except Exception as e:
        print(f"Config validation failed: {e}", file=sys.stderr)
        sys.exit(1)
    # Check secret expiry (stub)
    SecretsManager.check_secret_expiry()
    # Nightly checksum verification (stub)
    ChecksumVerifier.nightly_check()
    main()
