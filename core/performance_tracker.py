from collections import defaultdict
from datetime import datetime, timezone
from core.logger import get_logger

class PerformanceTracker:
    def __init__(self):
        self.logger = get_logger()
        self.trades = defaultdict(list)
        self.equity = 100000.0

    def record_trade(self, strategy, symbol, side, qty, price, pnl):
        self.trades[strategy].append({
            'timestamp': datetime.now(timezone.utc),
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': price,
            'pnl': pnl
        })

    def get_metrics(self, strategy):
        trades = self.trades.get(strategy, [])
        if not trades:
            return {'sharpe': 0, 'win_rate': 0, 'drawdown': 0}
        wins = [t for t in trades if t['pnl'] > 0]
        win_rate = len(wins)/len(trades)
        pnl_series = [t['pnl'] for t in trades]
        avg = sum(pnl_series)/len(pnl_series)
        std = (sum((x-avg)**2 for x in pnl_series)/len(pnl_series))**0.5 if len(trades)>1 else 0
        sharpe = avg/std if std else 0
        max_draw = min(0, min(pnl_series))
        return {'sharpe': sharpe, 'win_rate': win_rate, 'drawdown': abs(max_draw)/self.equity}

    def update_daily_stats(self):
        pass

    def should_kill(self, strategy, cfg):
        m = self.get_metrics(strategy)
        return (m['sharpe'] < cfg['sharpe_kill_threshold'] or
                m['win_rate'] < 0.5 or
                m['drawdown'] > cfg['max_drawdown_kill_threshold'])

    def get_account_snapshot(self):
        # simple stub
        return {'equity': self.equity}
