from strategies.base_strategy import BaseStrategy
import numpy as np

class MeanReversionStrategy(BaseStrategy):
    def __init__(self, data_handler, config):
        super().__init__('mean_reversion', data_handler, config)
        self.symbols = config.get('symbols',['SPY','QQQ','IWM'])

    def get_symbols(self):
        return self.symbols

    def generate_signal(self):
        for symbol in self.symbols:
            df = self.data_handler.get_bars(symbol, limit=30)
            if df.empty: 
                continue
            mean = df['close'].mean()
            last = df['close'].iloc[-1]
            dev = (last - mean)/mean
            if dev < -0.01:
                return {'symbol':symbol,'side':'buy','should_trade':True,'current_price':last}
            elif dev > 0.01:
                return {'symbol':symbol,'side':'sell','should_trade':True,'current_price':last}
        return {'should_trade':False}
