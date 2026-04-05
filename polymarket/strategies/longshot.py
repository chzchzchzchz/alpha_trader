"""
Longshot Diversification Strategy.

Sources:
  - Emil-Ka/polymarket-longshot-bot
  - devacc8/mispricer (adds GFS weather ensemble angle)

Thesis: Prediction markets systematically underprice low-probability events
(longshot bias reversal).  A $1 bet on a 5¢ contract pays $20 if correct.
Spread $1 bets across dozens of contracts — one correct 5¢ outcome offsets
~20 losses.

Two entry modes:
  1. PURE LONGSHOT: price ≤ 5¢, liquidity ≥ $500 USDC, FOK execution
  2. SMART LONGSHOT: price 1¢–15¢ with an independent probability estimate
     showing the market is underpriced by ≥ 8% (the mispricer approach)

The smart mode slots in external probability estimates (weather models,
LLM, news sentiment) — we leave a hook for that.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("trading")


@dataclass
class LongshotConfig:
    # Pure longshot
    max_price: float = 0.05              # ≤5¢ YES price
    min_liquidity_usdc: float = 500.0    # 24h volume floor
    bet_size_usdc: float = 1.0           # $1 fixed bet per contract
    max_positions: int = 50              # max simultaneous longshots
    # Smart longshot (with external model)
    smart_max_price: float = 0.15        # ≤15¢ with external edge
    smart_min_edge: float = 0.08         # need ≥8% probability edge
    smart_bet_multiplier: float = 3.0    # scale up when edge is confirmed
    # Exit
    take_profit_multiplier: float = 5.0  # sell at 5× entry (e.g., 5¢ → 25¢)


@dataclass
class LongshotSignal:
    token_id: str
    question: str
    side: str                 # 'YES' or 'NO'
    market_price: float
    model_probability: float  # 0.0 if no model available
    edge: float               # model_prob - market_price
    bet_size_usdc: float
    mode: str                 # 'pure' or 'smart'


class LongshotStrategy:
    """
    Builds a diversified portfolio of longshot contracts.
    """

    def __init__(self, client, config: LongshotConfig | None = None,
                 probability_estimator: Callable[[str], float] | None = None):
        """
        probability_estimator: optional callable(question: str) -> float
          Returns estimated true probability for a market.
          Can be an LLM call, weather model, etc.
          If None, only pure longshot mode is used.
        """
        self.client   = client
        self.cfg      = config or LongshotConfig()
        self._estimator = probability_estimator
        self._positions: dict[str, LongshotSignal] = {}  # token_id -> signal

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, markets: list[dict]) -> list[LongshotSignal]:
        signals: list[LongshotSignal] = []

        for market in markets:
            if len(self._positions) + len(signals) >= self.cfg.max_positions:
                break

            tokens   = market.get("tokens", [])
            volume   = float(market.get("volume24hr") or market.get("volume", 0))
            question = market.get("question") or market.get("title", "")

            for token in tokens:
                outcome  = token.get("outcome", "")
                price    = float(token.get("price", 1.0))
                token_id = token.get("token_id") or token.get("tokenId", "")
                side     = "YES" if outcome == "Yes" else "NO"

                if token_id in self._positions:
                    continue
                if volume < self.cfg.min_liquidity_usdc:
                    continue

                sig = self._evaluate(token_id, question, side, price, volume)
                if sig:
                    signals.append(sig)

        logger.info("Longshot scan: %d signals", len(signals))
        return signals

    def _evaluate(self, token_id: str, question: str, side: str,
                  price: float, volume: float) -> LongshotSignal | None:
        # Pure mode: just price threshold
        if price <= self.cfg.max_price:
            return LongshotSignal(
                token_id=token_id,
                question=question,
                side=side,
                market_price=price,
                model_probability=0.0,
                edge=0.0,
                bet_size_usdc=self.cfg.bet_size_usdc,
                mode="pure",
            )

        # Smart mode: only if we have an estimator and price is in range
        if self._estimator and price <= self.cfg.smart_max_price:
            try:
                model_prob = self._estimator(question)
                edge = model_prob - price
                if edge >= self.cfg.smart_min_edge:
                    return LongshotSignal(
                        token_id=token_id,
                        question=question,
                        side=side,
                        market_price=price,
                        model_probability=model_prob,
                        edge=edge,
                        bet_size_usdc=self.cfg.bet_size_usdc * self.cfg.smart_bet_multiplier,
                        mode="smart",
                    )
            except Exception as e:
                logger.debug("Estimator error for %s: %s", question[:30], e)

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, signal: LongshotSignal) -> bool:
        try:
            resp = self.client.place_market_order(
                token_id=signal.token_id,
                side="BUY",
                amount_usdc=signal.bet_size_usdc,
            )
            if resp:
                self._positions[signal.token_id] = signal
                logger.info(
                    "Longshot [%s]: %s %s @ %.3f edge=%.3f $%.2f",
                    signal.mode, signal.question[:35], signal.side,
                    signal.market_price, signal.edge, signal.bet_size_usdc,
                )
                return True
        except Exception as e:
            logger.error("Longshot order failed: %s", e)
        return False

    def check_take_profits(self) -> None:
        """Sell positions that hit the take-profit multiplier."""
        for token_id, sig in list(self._positions.items()):
            try:
                current = self.client.get_midpoint(token_id)
                if current and current >= sig.market_price * self.cfg.take_profit_multiplier:
                    self.client.place_market_order(token_id, "SELL", sig.bet_size_usdc)
                    pnl = (current - sig.market_price) / sig.market_price
                    logger.info("Longshot TP: %s %.0f× pnl", sig.question[:30], pnl)
                    del self._positions[token_id]
            except Exception as e:
                logger.debug("TP check error: %s", e)

    @property
    def portfolio_cost(self) -> float:
        return sum(s.bet_size_usdc for s in self._positions.values())
