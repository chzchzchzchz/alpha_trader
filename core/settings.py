"""
Settings loader — reads config.yaml and merges with environment variables.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expand_env(value: str) -> str:
    """Substitute ${VAR} placeholders with environment variable values."""
    def replacer(m):
        var = m.group(1)
        result = os.getenv(var, "")
        if not result:
            raise ValueError(f"Required environment variable '{var}' is not set")
        return result
    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _resolve(obj):
    """Recursively resolve ${VAR} in dicts/lists/strings."""
    if isinstance(obj, dict):
        return {k: _resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v) for v in obj]
    if isinstance(obj, str):
        return _expand_env(obj)
    return obj


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AlpacaSettings:
    key: str
    secret: str
    base_url: str
    data_url: str


@dataclass
class CapitalSettings:
    initial_equity: float
    max_position_size: float
    risk_per_trade: float


@dataclass
class PerformanceTrackingSettings:
    min_trades_for_evaluation: int
    sharpe_kill_threshold: float
    max_drawdown_kill_threshold: float
    lookback_period_days: int


@dataclass
class StrategiesSettings:
    enabled: List[str]
    performance_tracking: PerformanceTrackingSettings


@dataclass
class ScheduleSettings:
    timezone: str
    market_open: str
    market_close: str
    polling_interval: int
    trading_windows: dict = field(default_factory=dict)


@dataclass
class LoggingSettings:
    level: str
    file: str
    max_file_size: int
    backup_count: int


@dataclass
class DataSettings:
    symbols: List[str]
    timeframes: List[str]
    history_days: int


@dataclass
class Settings:
    env: str
    mode: str
    alpaca: AlpacaSettings
    capital: CapitalSettings
    strategies: StrategiesSettings
    schedule: ScheduleSettings
    logging: LoggingSettings
    data: DataSettings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_settings: Optional[Settings] = None


def load_dotenv(path: str = ".env") -> None:
    """Load a .env file into os.environ (simple parser, no external deps)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def get_settings(config_path: str = "config.yaml") -> Settings:
    """Load and cache settings from YAML + environment."""
    global _settings
    if _settings is not None:
        return _settings

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(path.read_text())
    raw = _resolve(raw)

    alp = raw.get("alpaca", {})
    cap = raw.get("capital", {})
    strat_raw = raw.get("strategies", {})
    perf_raw = strat_raw.get("performance_tracking", {})
    sched_raw = raw.get("schedule", {})
    log_raw = raw.get("logging", {})
    data_raw = raw.get("data", {})

    _settings = Settings(
        env=os.getenv("ENV", "development"),
        mode=raw.get("mode", "backtest"),
        alpaca=AlpacaSettings(
            key=alp["key"],
            secret=alp["secret"],
            base_url=alp.get("base_url", "https://paper-api.alpaca.markets"),
            data_url=alp.get("data_url", "https://data.alpaca.markets"),
        ),
        capital=CapitalSettings(
            initial_equity=float(cap.get("initial_equity", 100000)),
            max_position_size=float(cap.get("max_position_size", 0.05)),
            risk_per_trade=float(cap.get("risk_per_trade", 0.01)),
        ),
        strategies=StrategiesSettings(
            enabled=strat_raw.get("enabled", []),
            performance_tracking=PerformanceTrackingSettings(
                min_trades_for_evaluation=int(perf_raw.get("min_trades_for_evaluation", 10)),
                sharpe_kill_threshold=float(perf_raw.get("sharpe_kill_threshold", -0.5)),
                max_drawdown_kill_threshold=float(perf_raw.get("max_drawdown_kill_threshold", 0.15)),
                lookback_period_days=int(perf_raw.get("lookback_period_days", 30)),
            ),
        ),
        schedule=ScheduleSettings(
            timezone=sched_raw.get("timezone", "America/New_York"),
            market_open=sched_raw.get("market_open", "09:30"),
            market_close=sched_raw.get("market_close", "16:00"),
            polling_interval=int(sched_raw.get("polling_interval", 30)),
            trading_windows=sched_raw.get("trading_windows", {}),
        ),
        logging=LoggingSettings(
            level=log_raw.get("level", "INFO"),
            file=log_raw.get("file", "logs/trading.log"),
            max_file_size=int(log_raw.get("max_file_size", 10485760)),
            backup_count=int(log_raw.get("backup_count", 5)),
        ),
        data=DataSettings(
            symbols=data_raw.get("symbols", []),
            timeframes=data_raw.get("timeframes", ["1Min"]),
            history_days=int(data_raw.get("history_days", 30)),
        ),
    )
    return _settings
