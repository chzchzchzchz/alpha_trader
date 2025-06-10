from strategies.base_strategy import BaseStrategy
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

class GapFillStrategy(BaseStrategy):
    def __init__(self, data_handler, config):
        super().__init__('gap_fill', data_handler, config)
        self.symbols = config.get('symbols', ['SPY','QQQ','IWM'])
        self.threshold = 0.005

    def get_symbols(self):
        return self.symbols

    def generate_signal(self):
        for symbol in self.symbols:
            cur = self.data_handler.get_latest_price(symbol)
            prev = self.data_handler.get_previous_close(symbol)
            if cur is None or prev is None:
                continue
            gap = (cur - prev)/prev
            if abs(gap) >= self.threshold:
                side = 'sell' if gap>0 else 'buy'
                return {'symbol':symbol,'side':side,'should_trade':True,'current_price':cur}
        return {'should_trade':False}
