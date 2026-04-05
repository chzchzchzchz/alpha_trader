import math
from core.logger import get_logger


class TradeExecutor:
    def __init__(self, broker, perf_tracker, risk_per_trade: float = 0.01):
        self.broker = broker
        self.perf_tracker = perf_tracker
        self.logger = get_logger()
        self.risk_per_trade = risk_per_trade
        # symbol -> (side, qty, entry_price)
        self._open_positions: dict = {}

    def execute_trade(self, signal: dict, strategy_name: str) -> bool:
        symbol = signal['symbol']
        side = signal['side']

        price = signal.get('current_price') or self.broker.get_latest_price(symbol)
        if price is None:
            self.logger.error(f'No price available for {symbol}')
            return False

        # Close opposite position first and realize PnL
        if symbol in self._open_positions:
            open_side, open_qty, entry_price = self._open_positions[symbol]
            if open_side != side:
                pnl = (price - entry_price) * open_qty if open_side == 'buy' else (entry_price - price) * open_qty
                close_order = self.broker.submit_order(symbol, open_qty, 'sell' if open_side == 'buy' else 'buy')
                if close_order:
                    self.perf_tracker.record_trade(strategy_name, symbol, open_side, open_qty, price, pnl)
                    self.logger.info(f'Closed {open_side} {open_qty} {symbol} pnl={pnl:.2f}')
                del self._open_positions[symbol]

        account = self.perf_tracker.get_account_snapshot()
        risk_amt = account['equity'] * self.risk_per_trade
        qty = max(1, math.floor(risk_amt / price))

        order_id = self.broker.submit_order(symbol, qty, side)
        if order_id:
            self._open_positions[symbol] = (side, qty, price)
            self.perf_tracker.record_trade(strategy_name, symbol, side, qty, price, 0.0)
            return True
        return False
