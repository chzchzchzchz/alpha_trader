from core.logger import get_logger
import math

class TradeExecutor:
    def __init__(self, broker, perf_tracker, risk_per_trade=0.01):
        self.broker = broker
        self.perf_tracker = perf_tracker
        self.logger = get_logger()
        self.risk_per_trade = risk_per_trade

    def execute_trade(self, signal, strategy_name):
        symbol = signal['symbol']
        side = signal['side']
        price = signal.get('current_price')
        if price is None:
            price = self.broker.get_latest_price(symbol)
            if price is None:
                self.logger.error(f'No price for {symbol}')
                return False
        account = self.perf_tracker.get_account_snapshot()
        risk_amt = account['equity'] * self.risk_per_trade
        qty = max(1, math.floor(risk_amt / price))
        order_id = self.broker.submit_order(symbol, qty, side)
        if order_id:
            self.perf_tracker.record_trade(strategy_name, symbol, side, qty, price, 0.0)
            return True
        return False
