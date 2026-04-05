"""
Fractional Kelly position sizer.

Kelly criterion: f* = (bp - q) / b
  b = odds received on the bet (avg_win / avg_loss)
  p = probability of winning
  q = 1 - p

We always use fractional Kelly (default 0.25x) to reduce variance.
Full Kelly maximizes log wealth but creates extreme drawdowns in practice.

Research consensus for prediction markets: 0.25x Kelly.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("trading")


class KellySizer:
    def __init__(self, fraction: float = 0.25):
        """
        fraction: Kelly multiplier (0.25 = quarter-Kelly, recommended)
        """
        if not 0 < fraction <= 1.0:
            raise ValueError(f"Kelly fraction must be (0, 1], got {fraction}")
        self.fraction = fraction

    def kelly_fraction(self, win_rate: float, avg_win: float,
                       avg_loss: float) -> float:
        """
        Returns the optimal fraction of bankroll to bet.

        win_rate: probability of winning (0-1)
        avg_win:  average profit per winning trade (positive)
        avg_loss: average loss per losing trade (positive magnitude)
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0.0
        b = avg_win / avg_loss        # odds ratio
        p = win_rate
        q = 1.0 - p
        f_star = (b * p - q) / b     # Kelly formula
        f_star = max(0.0, f_star)    # never bet negative (edge < 0)
        return f_star * self.fraction

    def size_contracts(self, win_rate: float, avg_win: float,
                       avg_loss: float, bankroll: float,
                       contract_price: float) -> int:
        """
        Returns number of contracts to buy.
        contract_price: price per contract in dollars (e.g. 0.08 = 8¢)
        """
        frac = self.kelly_fraction(win_rate, avg_win, avg_loss)
        dollar_bet = bankroll * frac
        contracts = int(dollar_bet / max(contract_price, 0.01))
        return max(0, contracts)

    def size_usdc(self, win_rate: float, avg_win: float,
                  avg_loss: float, bankroll: float,
                  base_amount: float = 10.0) -> float:
        """
        Returns USDC amount to bet.
        Falls back to base_amount if Kelly says 0 (no edge detected).
        """
        frac = self.kelly_fraction(win_rate, avg_win, avg_loss)
        if frac <= 0:
            logger.debug("Kelly says no edge (WR=%.2f) — using base amount", win_rate)
            return base_amount
        return bankroll * frac

    def describe(self, win_rate: float, avg_win: float,
                 avg_loss: float, bankroll: float) -> str:
        frac = self.kelly_fraction(win_rate, avg_win, avg_loss)
        full = frac / self.fraction
        return (f"Kelly: full={full:.3f} → {self.fraction}x={frac:.3f} "
                f"→ ${bankroll * frac:.2f} of ${bankroll:.2f} bankroll")
