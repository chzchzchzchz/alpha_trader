"""
5-Gate Risk Engine.

Based on OctagonAI's Kalshi trading bot architecture.
Every trade must pass all five gates before execution.

Gate 1: Kelly criterion — does the trade have positive expected value?
Gate 2: Liquidity — is there enough market depth to fill without slippage?
Gate 3: Correlation — are we already heavily exposed to this outcome?
Gate 4: Concentration — does this breach per-market or per-category limits?
Gate 5: Drawdown — are we within daily/total drawdown limits?

Reference: https://github.com/OctagonAI/kalshi-deep-trading-bot
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("trading")


@dataclass
class RiskConfig:
    # Gate 1: Kelly
    min_kelly_fraction: float = 0.005     # need at least 0.5% Kelly to trade
    kelly_multiplier: float = 0.25        # quarter-Kelly
    # Gate 2: Liquidity
    min_market_volume_24h: int = 20       # minimum contracts traded in 24h
    max_slippage_frac: float = 0.03       # max acceptable slippage
    # Gate 3: Correlation
    max_correlated_exposure_usdc: float = 200.0  # max across correlated markets
    # Gate 4: Concentration
    max_single_market_usdc: float = 100.0
    max_category_usdc: float = 300.0
    max_total_open_usdc: float = 1000.0
    # Gate 5: Drawdown
    max_daily_loss_usdc: float = 100.0
    max_total_drawdown_frac: float = 0.20    # 20% of initial capital


@dataclass
class RiskState:
    initial_capital: float
    current_capital: float
    daily_pnl: float = 0.0
    # market_id -> USDC exposure
    market_exposure: dict[str, float] = field(default_factory=dict)
    # category -> USDC exposure
    category_exposure: dict[str, float] = field(default_factory=dict)
    # keyword set -> USDC exposure (for correlation grouping)
    correlation_groups: dict[str, float] = field(default_factory=dict)


@dataclass
class GateResult:
    gate: int
    name: str
    passed: bool
    reason: str = ""

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"Gate {self.gate} ({self.name}): {status}" + (f" — {self.reason}" if self.reason else "")


class RiskEngine:
    def __init__(self, config: RiskConfig | None = None, initial_capital: float = 500.0):
        self.cfg = config or RiskConfig()
        self.state = RiskState(
            initial_capital=initial_capital,
            current_capital=initial_capital,
        )

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def check_trade(
        self,
        market_id: str,
        category: str,
        entry_price: float,      # fraction 0-1
        win_rate: float,
        usdc_size: float,
        volume_24h: int,
        correlation_key: str = "",  # e.g. "bitcoin" or "trump_election"
    ) -> tuple[bool, list[GateResult]]:
        """
        Run all 5 gates.  Returns (approved: bool, gate_results: list).
        """
        gates = [
            self._gate1_kelly(win_rate, entry_price, usdc_size),
            self._gate2_liquidity(volume_24h, usdc_size, entry_price),
            self._gate3_correlation(correlation_key, usdc_size),
            self._gate4_concentration(market_id, category, usdc_size),
            self._gate5_drawdown(usdc_size),
        ]

        approved = all(g.passed for g in gates)
        if not approved:
            failed = [g for g in gates if not g.passed]
            logger.debug("Trade rejected — %s", "; ".join(str(g) for g in failed))
        return approved, gates

    def record_trade(self, market_id: str, category: str,
                     usdc_size: float, correlation_key: str = "") -> None:
        self.state.market_exposure[market_id] = (
            self.state.market_exposure.get(market_id, 0.0) + usdc_size
        )
        self.state.category_exposure[category] = (
            self.state.category_exposure.get(category, 0.0) + usdc_size
        )
        if correlation_key:
            self.state.correlation_groups[correlation_key] = (
                self.state.correlation_groups.get(correlation_key, 0.0) + usdc_size
            )

    def record_pnl(self, pnl: float) -> None:
        self.state.daily_pnl += pnl
        self.state.current_capital += pnl

    def close_position(self, market_id: str, category: str,
                       usdc_size: float, correlation_key: str = "") -> None:
        self.state.market_exposure[market_id] = max(
            0.0, self.state.market_exposure.get(market_id, 0.0) - usdc_size
        )
        self.state.category_exposure[category] = max(
            0.0, self.state.category_exposure.get(category, 0.0) - usdc_size
        )
        if correlation_key:
            self.state.correlation_groups[correlation_key] = max(
                0.0, self.state.correlation_groups.get(correlation_key, 0.0) - usdc_size
            )

    def reset_daily(self) -> None:
        self.state.daily_pnl = 0.0

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    def _gate1_kelly(self, win_rate: float, entry_price: float,
                     usdc_size: float) -> GateResult:
        """Has positive expected value above minimum threshold."""
        if entry_price <= 0 or entry_price >= 1:
            return GateResult(1, "kelly", False, f"invalid price {entry_price}")

        avg_win  = 1.0 - entry_price   # profit if correct
        avg_loss = entry_price          # loss if wrong
        b        = avg_win / avg_loss
        p        = win_rate
        q        = 1.0 - p
        f_star   = max(0.0, (b * p - q) / b)

        if f_star < self.cfg.min_kelly_fraction:
            return GateResult(
                1, "kelly", False,
                f"f*={f_star:.4f} < min={self.cfg.min_kelly_fraction:.4f} (WR={win_rate:.2f})"
            )
        return GateResult(1, "kelly", True, f"f*={f_star:.4f}")

    def _gate2_liquidity(self, volume_24h: int, usdc_size: float,
                          entry_price: float) -> GateResult:
        """Enough market depth to absorb the trade."""
        if volume_24h < self.cfg.min_market_volume_24h:
            return GateResult(
                2, "liquidity", False,
                f"volume_24h={volume_24h} < min={self.cfg.min_market_volume_24h}"
            )
        contracts = usdc_size / max(entry_price, 0.01)
        if volume_24h > 0 and contracts / volume_24h > self.cfg.max_slippage_frac * 10:
            return GateResult(
                2, "liquidity", False,
                f"trade_size/volume={contracts/volume_24h:.2f} too large"
            )
        return GateResult(2, "liquidity", True)

    def _gate3_correlation(self, correlation_key: str,
                            usdc_size: float) -> GateResult:
        """Not over-exposed to correlated outcomes."""
        if not correlation_key:
            return GateResult(3, "correlation", True, "no correlation key")
        current = self.state.correlation_groups.get(correlation_key, 0.0)
        if current + usdc_size > self.cfg.max_correlated_exposure_usdc:
            return GateResult(
                3, "correlation", False,
                f"correlated exposure ${current+usdc_size:.2f} > max ${self.cfg.max_correlated_exposure_usdc:.2f}"
            )
        return GateResult(3, "correlation", True)

    def _gate4_concentration(self, market_id: str, category: str,
                              usdc_size: float) -> GateResult:
        """Not breaching per-market, per-category, or total limits."""
        mkt_exp = self.state.market_exposure.get(market_id, 0.0) + usdc_size
        if mkt_exp > self.cfg.max_single_market_usdc:
            return GateResult(
                4, "concentration", False,
                f"market exposure ${mkt_exp:.2f} > max ${self.cfg.max_single_market_usdc:.2f}"
            )
        cat_exp = self.state.category_exposure.get(category, 0.0) + usdc_size
        if cat_exp > self.cfg.max_category_usdc:
            return GateResult(
                4, "concentration", False,
                f"category '{category}' exposure ${cat_exp:.2f} > max ${self.cfg.max_category_usdc:.2f}"
            )
        total = sum(self.state.market_exposure.values()) + usdc_size
        if total > self.cfg.max_total_open_usdc:
            return GateResult(
                4, "concentration", False,
                f"total open ${total:.2f} > max ${self.cfg.max_total_open_usdc:.2f}"
            )
        return GateResult(4, "concentration", True)

    def _gate5_drawdown(self, usdc_size: float) -> GateResult:
        """Within daily and total drawdown limits."""
        if self.state.daily_pnl <= -self.cfg.max_daily_loss_usdc:
            return GateResult(
                5, "drawdown", False,
                f"daily loss ${abs(self.state.daily_pnl):.2f} ≥ limit ${self.cfg.max_daily_loss_usdc:.2f}"
            )
        dd_frac = (self.state.initial_capital - self.state.current_capital) / self.state.initial_capital
        if dd_frac >= self.cfg.max_total_drawdown_frac:
            return GateResult(
                5, "drawdown", False,
                f"total drawdown {dd_frac:.1%} ≥ limit {self.cfg.max_total_drawdown_frac:.1%}"
            )
        return GateResult(5, "drawdown", True)
