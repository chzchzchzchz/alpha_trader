from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import pandas as pd
from core.logger import get_logger

class BaseStrategy(ABC):
    def __init__(self, name, data_handler, config):
        self.name = name
        self.data_handler = data_handler
        self.config = config
        self.logger = get_logger()
        self.last_signal_time = None

    @abstractmethod
    def generate_signal(self) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_symbols(self) -> List[str]:
        pass

    def should_trade_now(self) -> bool:
        return True
