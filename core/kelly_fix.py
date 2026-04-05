"""
Kelly Sizer - Fixed API with sizing() method.
Works with the unified main.py pipeline.
"""
from __future__ import annotations

class KellySizer:
    def __init__(self, fraction: float = 0.25):
        self.fraction = fraction

    def sizing(self, sig_prob: float = 0.5, yes_price: float = 50, no_price: float = 50):
        """Simple sizing: given signal probability and market prices, return portfolio fraction."""
        if yes_price <= 0 or no_price <= 0:
            return 0.0
        implied_yes = yes_price / 100.0
        implied_no = no_price / 100.0
        edge_yes = (sig_prob - implied_yes) / max(implied_yes, 0.01)
        edge_no = ((1 - sig_prob) - implied_no) / max(implied_no, 0.01)
        edge = max(edge_yes, edge_no)
        if edge <= 0:
            return 0.0
        size = edge * self.fraction
        return max(0, min(0.5, size))

    def kelly_fraction(self, win_rate: float, avg_win: float, avg_loss: float):
        b = avg_win / avg_loss if avg_loss > 0 else 0
        if b == 0: return 0.0
        kelly = (b * win_rate - (1 - win_rate)) / b
        return max(0, kelly * self.fraction)

    def size_contracts(self, win_rate: float, avg_win: float, avg_loss: float, bankroll: float = 10000):
        kf = self.kelly_fraction(win_rate, avg_win, avg_loss)
        return max(0, int(bankroll * kf / 50))

    def size_usdc(self, win_rate: float, avg_win: float, avg_loss: float, bankroll: float = 10000):
        kf = self.kelly_fraction(win_rate, avg_win, avg_loss)
        return max(0, bankroll * kf)

    def describe(self, win_rate: float, avg_win: float, avg_loss: float, bankroll: float = 10000):
        kf = self.kelly_fraction(win_rate, avg_win, avg_loss)
        contracts = self.size_contracts(win_rate, avg_win, avg_loss, bankroll)
        usdc = self.size_usdc(win_rate, avg_win, avg_loss, bankroll)
        return {"pct": round(kf*100, 2), "contracts": contracts, "usdc": round(usdc, 2)}
