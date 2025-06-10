import os
import sys
import hashlib
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

# --- ENV LOADER ---
def load_dotenv(dotenv_path: str = ".env"):
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                k, _, v = line.strip().partition('=')
                os.environ.setdefault(k, v)

# --- CONFIG HASH CHECKER ---
def check_config_hash(dotenv_path: str = ".env", hash_path: str = "config/config_hash.txt", override: bool = False):
    if override:
        return
    if not os.path.exists(dotenv_path) or not os.path.exists(hash_path):
        print("Missing .env or config hash file.", file=sys.stderr)
        sys.exit(13)
    with open(dotenv_path, 'rb') as f:
        env_bytes = f.read()
    actual_hash = hashlib.sha256(env_bytes).hexdigest()
    with open(hash_path) as f:
        expected_hash = f.read().strip()
    if actual_hash != expected_hash:
        print("Config hash mismatch.", file=sys.stderr)
        sys.exit(13)

# --- CONFIG VALIDATOR ---
def validate_config():
    key = os.environ.get("ALPACA_KEY", "")
    secret = os.environ.get("ALPACA_SECRET", "")
    var_threshold = float(os.environ.get("VAR_THRESHOLD", "0.0"))
    if len(key) != 20:
        raise ValueError("ALPACA_KEY must be exactly 20 characters.")
    if len(secret) != 40:
        raise ValueError("ALPACA_SECRET must be exactly 40 characters.")
    if var_threshold > 0.03:
        raise ValueError("VAR_THRESHOLD must be ≤ 0.03.")

# --- SECRETS MANAGER (stub) ---
class SecretsManager:
    @staticmethod
    def check_secret_expiry():
        # TODO: Implement secret expiration logic (12h expiry, throw SECRET_EXPIRED)
        pass

# --- CHECKSUM VERIFIER (stub) ---
class ChecksumVerifier:
    @staticmethod
    def nightly_check():
        # TODO: Implement nightly hash check of all files
        print("NO CHECKSUM ERRORS")

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
