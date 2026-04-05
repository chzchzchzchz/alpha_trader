"""
Category Specialist strategy.

Tracks our own fill history to identify which market categories we
(or the strategies we're following) perform best in.  Concentrates
capital in high-win-rate categories, avoids weak ones.

This is the "real" version of the viral post's pattern:
  "one wallet: 91% WR on crypto, 14% on politics — filter to crypto only"

Instead of scanning foreign wallets (not possible on Kalshi), we use our
own performance history and category-level market data to find where we
have an edge.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger("trading")


@dataclass
class CategoryPerf:
    category: str
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    trades: list[dict] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total else 0.0

    @property
    def trade_count(self) -> int:
        return self.wins + self.losses

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trade_count if self.trade_count else 0.0


@dataclass
class CategorySpecialistConfig:
    min_trades_per_category: int = 10     # need this many trades before judging
    min_win_rate: float = 0.55            # must clear this to trade the category
    blacklist_win_rate: float = 0.40      # below this = avoid entirely
    max_categories: int = 5               # trade top-N categories only
    contracts_per_trade: int = 5
    confidence_multiplier: float = 1.5   # scale up in best categories


class CategorySpecialistStrategy:
    """
    Builds per-category performance profiles from fill history,
    then only takes new positions in categories with demonstrated edge.
    """

    def __init__(self, client, analyzer, config: CategorySpecialistConfig | None = None):
        self.client = client
        self.analyzer = analyzer
        self.cfg = config or CategorySpecialistConfig()
        self._category_perf: dict[str, CategoryPerf] = defaultdict(lambda: CategoryPerf(category=""))

    # ------------------------------------------------------------------
    # Profile building
    # ------------------------------------------------------------------

    def refresh_performance_profile(self) -> dict[str, CategoryPerf]:
        """
        Load our fill history and categorize each trade.
        Call this periodically (e.g. at startup and daily).
        """
        try:
            fills_resp = self.client.get_fills(limit=500)
        except Exception as e:
            logger.error("Failed to fetch fills: %s", e)
            return self._category_perf

        fills = fills_resp.get("fills", [])
        self._category_perf.clear()

        for fill in fills:
            ticker = fill.get("market_ticker", "")
            # Determine category from ticker prefix (Kalshi tickers are like INXD-23DEC31-B4000)
            category = self._infer_category(ticker, fill)

            perf = self._category_perf.setdefault(category, CategoryPerf(category=category))
            pnl = fill.get("profit_and_loss", 0.0) or 0.0
            perf.total_pnl += pnl
            perf.trades.append(fill)
            if pnl > 0:
                perf.wins += 1
            elif pnl < 0:
                perf.losses += 1

        logger.info(
            "Performance profile: %d categories, %d total fills",
            len(self._category_perf),
            len(fills),
        )
        return dict(self._category_perf)

    def get_tradeable_categories(self) -> list[str]:
        """Return categories we have edge in, sorted by win rate."""
        eligible = [
            p for p in self._category_perf.values()
            if p.trade_count >= self.cfg.min_trades_per_category
            and p.win_rate >= self.cfg.min_win_rate
        ]
        eligible.sort(key=lambda p: p.win_rate, reverse=True)
        return [p.category for p in eligible[: self.cfg.max_categories]]

    def get_blacklisted_categories(self) -> list[str]:
        return [
            p.category for p in self._category_perf.values()
            if p.trade_count >= self.cfg.min_trades_per_category
            and p.win_rate < self.cfg.blacklist_win_rate
        ]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, markets) -> list[dict]:
        """
        Given a list of MarketStats, return buy signals only for
        markets in categories where we have demonstrated edge.
        """
        tradeable = set(self.get_tradeable_categories())
        blacklisted = set(self.get_blacklisted_categories())

        if not tradeable:
            logger.info("No categories with sufficient edge yet — collecting data")
            return []

        signals = []
        for market in markets:
            cat = market.category
            if cat in blacklisted:
                continue
            if cat not in tradeable:
                continue

            perf = self._category_perf.get(cat)
            win_rate = perf.win_rate if perf else 0.5

            # Simple signal: markets near 50¢ where we have edge
            if not (0.35 <= market.yes_price <= 0.65):
                continue
            if market.volume_24h < 20:
                continue

            # Scale contracts by how good our edge is in this category
            scale = 1 + (win_rate - self.cfg.min_win_rate) * self.cfg.confidence_multiplier
            contracts = max(1, int(self.cfg.contracts_per_trade * scale))

            # Lean toward the side with more volume (momentum proxy)
            side = "yes" if market.yes_price < 0.50 else "no"
            price = market.yes_price if side == "yes" else 1 - market.yes_price

            signals.append({
                "ticker": market.ticker,
                "title": market.title,
                "category": cat,
                "action": "buy",
                "side": side,
                "contracts": contracts,
                "price_cents": int(price * 100),
                "category_win_rate": win_rate,
            })

        logger.info(
            "CategorySpecialist: %d signals from %d tradeable categories",
            len(signals), len(tradeable),
        )
        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_category(ticker: str, fill: dict) -> str:
        """
        Infer category from ticker prefix or fill metadata.
        Kalshi provides a category field in market data; if not present
        we use the ticker prefix as a rough grouping.
        """
        # Use explicit category if fill contains it
        if "category" in fill:
            return fill["category"]
        # Fall back to ticker prefix (first segment before '-')
        return ticker.split("-")[0] if "-" in ticker else ticker[:4]
