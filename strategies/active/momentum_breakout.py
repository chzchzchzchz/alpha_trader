from strategies.base_strategy import BaseStrategy

class MomentumBreakoutStrategy(BaseStrategy):
    def __init__(self, data_handler, config):
        super().__init__('momentum_breakout', data_handler, config)
        self.symbols = config.get('symbols',['SPY','QQQ','IWM'])

    def get_symbols(self):
        return self.symbols

    def generate_signal(self):
        for s in self.symbols:
            df = self.data_handler.get_bars(s, limit=20)
            if df.empty:
                continue
            high = df['high'].max()
            last = df['close'].iloc[-1]
            if last >= high:
                return {'symbol':s,'side':'buy','should_trade':True,'current_price':last}
        return {'should_trade':False}
