from datetime import datetime, time
from core.logger import get_logger

class TradingScheduler:
    def __init__(self, cfg):
        self.cfg = cfg
        self.logger = get_logger()

    def _str_to_time(self, s):
        h, m = map(int, s.split(':'))
        return time(h, m)

    def should_run(self, now):
        open_t = self._str_to_time(self.cfg.market_open)
        close_t = self._str_to_time(self.cfg.market_close)
        return open_t <= now.time() <= close_t
