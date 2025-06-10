from strategies.base_strategy import BaseStrategy

class OpeningRangeBreakoutStrategy(BaseStrategy):
    def __init__(self, data_handler, config):
        super().__init__('opening_range_breakout', data_handler, config)
        self.symbols = config.get('symbols',['SPY','QQQ','IWM'])
        self.range_minutes = 15

    def get_symbols(self):
        return self.symbols

    def generate_signal(self):
        # very simple 15 min high breakout
        for s in self.symbols:
            df = self.data_handler.get_bars(s, limit=self.range_minutes)
            if df.empty or len(df)<self.range_minutes:
                continue
            rng_high = df['high'].iloc[:-1].max()
            last_close = df['close'].iloc[-1]
            if last_close > rng_high:
                return {'symbol':s,'side':'buy','should_trade':True,'current_price':last_close}
        return {'should_trade':False}
