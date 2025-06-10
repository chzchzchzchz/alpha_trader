import os
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class AlpacaConfig:
    key: str
    secret: str
    base_url: str
    data_url: str

@dataclass
class CapitalConfig:
    initial_equity: float
    max_position_size: float
    risk_per_trade: float

@dataclass
class StrategyConfig:
    enabled: List[str]
    performance_tracking: Dict[str, Any]

@dataclass
class ScheduleConfig:
    timezone: str
    market_open: str
    market_close: str
    polling_interval: int
    trading_windows: Dict[str, List[str]]

@dataclass
class LoggingConfig:
    level: str
    file: str
    max_file_size: int
    backup_count: int

@dataclass
class DataConfig:
    symbols: List[str]
    timeframes: List[str]
    history_days: int

class Config:
    def __init__(self, config_path: str):
        self.path = Path(config_path)
        self._load()

    def _sub_env(self, value: str) -> str:
        if value.startswith('${') and value.endswith('}'):
            env_key = value[2:-1]
            return os.getenv(env_key, '')
        return value

    def _load(self):
        with open(self.path, 'r') as f:
            data = yaml.safe_load(f)

        # Substitute env variables
        data['alpaca']['key'] = self._sub_env(data['alpaca']['key'])
        data['alpaca']['secret'] = self._sub_env(data['alpaca']['secret'])

        self.alpaca = AlpacaConfig(**data['alpaca'])
        self.capital = CapitalConfig(**data['capital'])
        self.strategies = StrategyConfig(**data['strategies'])
        self.schedule = ScheduleConfig(**data['schedule'])
        self.logging = LoggingConfig(**data['logging'])
        self.data = DataConfig(**data['data'])
        self.mode = data['mode']

        if not self.alpaca.key or not self.alpaca.secret:
            raise ValueError('Alpaca credentials not set in environment variables')

        Path(self.logging.file).parent.mkdir(parents=True, exist_ok=True)

    def get_trading_window(self, strategy: str):
        tw = self.schedule.trading_windows.get(strategy)
        if tw:
            return tw[0], tw[1]
        return self.schedule.market_open, self.schedule.market_close
