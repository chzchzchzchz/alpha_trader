try:
    import yfinance as yf
    import numpy as np
except ImportError:
    pass

class BacktestEngine:
    def __init__(self, slippage=0.001, commission=0.001):
        self.slippage = slippage
        self.commission = commission
    def run_momentum_strategy(self, ticker="SPY", period="1y"):
        try:
            h = yf.Ticker(ticker).history(period=period)
        except:
            return {"error": "yfinance failed"}
        if len(h) < 60:
            return {"error": "Insufficient data"}
        c = h["Close"].values
        ma50 = np.convolve(c, np.ones(50)/50, mode='valid')
        ma10 = np.convolve(c, np.ones(10)/10, mode='valid')
        offset = len(c) - len(ma50)
        pos = 0
        entry = 0
        wins = 0
        losses = 0
        cap = 10000
        for i in range(len(ma50)):
            price = c[i + offset]
            if c[i+offset] > ma50[i] and ma10[i] > ma50[i] and pos == 0:
                pos = 1
                entry = price
            elif c[i+offset] < ma50[i] and ma10[i] < ma50[i] and pos == 1:
                cost = cap * (self.slippage + self.commission)
                ret_ = (price - entry) / entry
                pnl = cap * ret_ - cost
                cap += pnl
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                pos = 0
        if pos == 1:
            price = c[-1]
            pnl = cap * ((price - entry) / entry) - cap * (self.slippage + self.commission)
            cap += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        total = wins + losses
        bm_ret = (c[-1] - c[0]) / c[0]
        total_ret = (cap - 10000) / 10000
        return {
            "ticker": ticker,
            "total_return_pct": round(total_ret * 100, 2),
            "benchmark_return_pct": round(bm_ret * 100, 2),
            "alpha_pct": round((total_ret - bm_ret) * 100, 2),
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": f"{wins/max(total,1)*100:.0f}%",
            "sharpe_ratio": round(total_ret / 0.15 * np.sqrt(1/total+1) if total else 0, 3),
        }
    def run_macro_strategy(self):
        return {"error": "FRED not available", "trades": 0, "win_rate": "N/A"}
