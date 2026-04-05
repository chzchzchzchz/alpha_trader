from collections import defaultdict
from datetime import datetime, timezone
from core.logger import get_logger


class PerformanceTracker:
    def __init__(self, initial_equity: float = 100000.0):
        self.logger = get_logger()
        self.trades = defaultdict(list)
        self.equity = initial_equity
        self._initial_equity = initial_equity
        # date -> realized PnL for that day
        self._daily_pnl: dict[str, float] = {}

    def record_trade(self, strategy: str, symbol: str, side: str,
                     qty: int, price: float, pnl: float) -> None:
        self.trades[strategy].append({
            'timestamp': datetime.now(timezone.utc),
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': price,
            'pnl': pnl,
        })
        # Update equity on realized PnL (closing trades have non-zero pnl)
        if pnl != 0.0:
            self.equity += pnl

    def get_metrics(self, strategy: str) -> dict:
        trades = self.trades.get(strategy, [])
        closed = [t for t in trades if t['pnl'] != 0.0]
        if not closed:
            return {'sharpe': 0.0, 'win_rate': 0.0, 'drawdown': 0.0, 'total_pnl': 0.0}

        wins = [t for t in closed if t['pnl'] > 0]
        win_rate = len(wins) / len(closed)
        pnl_series = [t['pnl'] for t in closed]
        avg = sum(pnl_series) / len(pnl_series)
        variance = sum((x - avg) ** 2 for x in pnl_series) / len(pnl_series)
        std = variance ** 0.5
        sharpe = avg / std if std else 0.0

        running = self._initial_equity
        peak = running
        max_dd = 0.0
        for p in pnl_series:
            running += p
            if running > peak:
                peak = running
            dd = (peak - running) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return {
            'sharpe': sharpe,
            'win_rate': win_rate,
            'drawdown': max_dd,
            'total_pnl': sum(pnl_series),
        }

    def update_daily_stats(self) -> None:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        daily_total = 0.0
        for trades in self.trades.values():
            for t in trades:
                if t['timestamp'].strftime('%Y-%m-%d') == today and t['pnl'] != 0.0:
                    daily_total += t['pnl']
        self._daily_pnl[today] = daily_total
        self.logger.debug(f'Daily PnL {today}: {daily_total:.2f}')

    def should_kill(self, strategy: str, cfg) -> bool:
        m = self.get_metrics(strategy)
        closed_count = sum(1 for t in self.trades.get(strategy, []) if t['pnl'] != 0.0)
        if closed_count < cfg['min_trades_for_evaluation']:
            return False
        return (
            m['sharpe'] < cfg['sharpe_kill_threshold']
            or m['drawdown'] > cfg['max_drawdown_kill_threshold']
        )

    def get_account_snapshot(self) -> dict:
        return {
            'equity': self.equity,
            'initial_equity': self._initial_equity,
            'total_pnl': self.equity - self._initial_equity,
            'daily_pnl': self._daily_pnl,
        }
