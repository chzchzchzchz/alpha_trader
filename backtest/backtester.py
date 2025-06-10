import numpy as np
from typing import Dict
from core.logger import get_logger

class Backtester:
    def __init__(self, data_handler, cfg):
        self.data   = data_handler
        self.cfg    = cfg
        self.logger = get_logger()

    def run(self, strategy) -> Dict[str, float]:
        pnl_trades = []
        wins       = 0
        total      = 0
        initial_eq = self.cfg.capital.initial_equity

        bars_needed = self.cfg.data.history_days * 390

        for symbol in strategy.get_symbols():
            df = self.data.get_bars(symbol, timeframe="1Min", limit=bars_needed)
            if df.empty or len(df) < 2:
                continue

            for i in range(len(df)-1):
                subset = df.iloc[:i+1].copy()
                # hack so strategy sees only up to this bar
                setattr(self.data, "_last_df", subset)

                sig = strategy.generate_signal()
                if not sig.get("should_trade"):
                    continue

                entry = subset["close"].iloc[-1]
                exitp = df["close"].iloc[i+1]
                pnl   = (exitp - entry) if sig["side"]=="buy" else (entry - exitp)

                pnl_trades.append(pnl)
                wins      += (1 if pnl>0 else 0)
                total     += 1

            # cleanup hack
            if hasattr(self.data, "_last_df"):
                delattr(self.data, "_last_df")

        if total == 0:
            return {"sharpe":0.0, "win_rate":0.0, "drawdown":0.0}

        arr      = np.array(pnl_trades)
        mean     = arr.mean()
        std      = arr.std(ddof=1) if len(arr)>1 else 0.0
        sharpe   = (mean/std)*np.sqrt(252*390) if std>0 else 0.0
        win_rate = wins/total

        cum      = np.cumsum(arr) + initial_eq
        peak     = np.maximum.accumulate(cum)
        max_dd   = ((peak - cum)/peak).max()

        return {
            "sharpe":   float(sharpe),
            "win_rate": float(win_rate),
            "drawdown": float(max_dd),
        }
