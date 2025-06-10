import importlib.util
import inspect
import pathlib
import sys

from core.logger import get_logger
from core.performance_tracker import PerformanceTracker
from strategies.base_strategy import BaseStrategy

class StrategyManager:
    """
    Loads and manages all active trading strategies
    """
    def __init__(self, strategy_cfg, data_handler, perf_tracker: PerformanceTracker):
        self.logger        = get_logger()
        self.data_handler  = data_handler
        self.perf_tracker  = perf_tracker

        # Unpack dataclass
        self.enabled       = strategy_cfg.enabled
        self.perf_settings = strategy_cfg.performance_tracking

        self.strategies = {}
        self._load_active_strategies()

    def _load_active_strategies(self):
        strat_dir = pathlib.Path(__file__).parent.parent / "strategies" / "active"
        sys.path.append(str(strat_dir.parent))

        for file in strat_dir.glob("*.py"):
            name = file.stem
            if name not in self.enabled:
                continue

            spec   = importlib.util.spec_from_file_location(name, file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # find the one concrete BaseStrategy subclass in this module
            candidates = [
                obj for _, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, BaseStrategy)
                   and obj is not BaseStrategy
                   and obj.__module__ == module.__name__
            ]

            if not candidates:
                self.logger.warning(f"No strategy class in {file.name}")
                continue

            cls       = candidates[0]
            instance  = cls(self.data_handler, {})
            self.strategies[name] = instance
            self.logger.info(f"Strategy {name} loaded")

    def get_strategy(self, name):
        return self.strategies.get(name)

    def should_kill_strategy(self, name):
        return self.perf_tracker.should_kill(name, self.perf_settings)

    def update_performance_metrics(self):
        pass
