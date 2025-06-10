from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import alpaca_trade_api as tradeapi
from core.logger import get_logger

class AlpacaBroker:
    def __init__(self, cfg):
        self.logger = get_logger()
        self.api = tradeapi.REST(cfg.key, cfg.secret, base_url=cfg.base_url, api_version='v2')
        try:
            acct = self.api.get_account()
            self.logger.info(f'Alpaca account {acct.account_number} connected')
        except Exception as e:
            self.logger.error(f'Alpaca connection error: {e}')
            raise

    def is_market_open(self) -> bool:
        try:
            return self.api.get_clock().is_open
        except Exception as e:
            self.logger.error(f'Clock error {e}')
            return False

    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            barset = self.api.get_latest_bar(symbol)
            return float(barset.c)
        except Exception as e:
            self.logger.error(f'Price fetch error {symbol} {e}')
            return None

    def submit_order(self, symbol: str, qty: int, side: str) -> Optional[str]:
        try:
            order = self.api.submit_order(symbol=symbol, qty=qty, side=side, type='market', time_in_force='day')
            self.logger.info(f'Order {order.id} {side} {qty} {symbol}')
            return order.id
        except Exception as e:
            self.logger.error(f'Order error {e}')
            return None
