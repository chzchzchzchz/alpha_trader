"""
Wallet analyzer — scans Kalshi trade history to identify profitable patterns.

Three strategies from the viral post, evaluated honestly:

1. Category Specialists
   Real.  A trader might be sharp on crypto markets but random on politics.
   Aggregate per-category win rate across all trades to find specialists.

2. Near-Zero Accumulation
   Real.  Buying YES at 2–8¢ weeks before resolution.  Expected value is
   positive if the true probability is higher than the price implies.
   We scan for markets trading below a threshold where smart money is buying.

3. Oracle / Speed Arbitrage
   Real but difficult.  Requires watching external data sources (sports APIs,
   news, Polymarket) and trading before Kalshi prices update.  We implement
   the detection side: flag markets whose price lags a correlated signal.

NOTE: Kalshi does NOT publicly expose individual wallet histories the way
Polymarket does on-chain.  What IS available:
  - Public trade tape (anonymous fills via /markets/trades)
  - Your own fills via /portfolio/fills
  - Orderbook depth per market

The "wallet scanning" in the viral post applies to Polymarket (on-chain).
For Kalshi we focus on market-level patterns rather than individual traders.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("trading")


@dataclass
class MarketStats:
    ticker: str
    category: str
    title: str
    yes_price: float  # 0.0–1.0
    volume_24h: int
    open_interest: int
    close_time: datetime | None
    trades: list[dict] = field(default_factory=list)

    @property
    def days_to_close(self) -> float | None:
        if self.close_time is None:
            return None
        delta = self.close_time - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds() / 86400)


@dataclass
class NearZeroOpportunity:
    ticker: str
    title: str
    yes_price: float
    buy_side: str   # 'yes' or 'no'
    smart_money_volume: int
    days_to_close: float | None
    score: float    # higher = more interesting


class WalletAnalyzer:
    """
    Analyzes Kalshi market data to surface trading opportunities.
    """

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def fetch_all_markets(self, status: str = "open") -> list[MarketStats]:
        """Page through all open markets and return MarketStats."""
        markets: list[MarketStats] = []
        cursor = None

        while True:
            resp = self.client.get_markets(limit=200, cursor=cursor, status=status)
            for m in resp.get("markets", []):
                close_str = m.get("close_time")
                close_dt = None
                if close_str:
                    try:
                        close_dt = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                yes_bid = m.get("yes_bid", 0)
                yes_ask = m.get("yes_ask", 100)
                yes_mid = (yes_bid + yes_ask) / 2 / 100  # convert cents → fraction

                markets.append(MarketStats(
                    ticker=m["ticker"],
                    category=m.get("category", "unknown"),
                    title=m.get("title", ""),
                    yes_price=yes_mid,
                    volume_24h=m.get("volume_24h", 0),
                    open_interest=m.get("open_interest", 0),
                    close_time=close_dt,
                ))

            cursor = resp.get("cursor")
            if not cursor:
                break

        logger.info("Fetched %d markets", len(markets))
        return markets

    def fetch_recent_trades(self, ticker: str, limit: int = 100) -> list[dict]:
        try:
            resp = self.client.get_trades(ticker, limit=limit)
            return resp.get("trades", [])
        except Exception as e:
            logger.debug("Trade fetch failed for %s: %s", ticker, e)
            return []

    # ------------------------------------------------------------------
    # Strategy 1: Near-Zero Accumulation
    # ------------------------------------------------------------------

    def find_near_zero_opportunities(
        self,
        markets: list[MarketStats],
        price_ceiling: float = 0.08,
        min_volume: int = 50,
        min_days_to_close: float = 3.0,
        max_days_to_close: float = 60.0,
    ) -> list[NearZeroOpportunity]:
        """
        Find markets where YES is cheap (< price_ceiling) but there's meaningful
        buying volume — suggesting informed traders think it's underpriced.

        Also checks the NO side: if NO > (1 - price_ceiling), YES is cheap.
        """
        opportunities: list[NearZeroOpportunity] = []

        for m in markets:
            days = m.days_to_close
            if days is None:
                continue
            if not (min_days_to_close <= days <= max_days_to_close):
                continue
            if m.volume_24h < min_volume:
                continue

            # Check YES side
            if m.yes_price <= price_ceiling:
                trades = self.fetch_recent_trades(m.ticker, limit=50)
                yes_buys = sum(t.get("count", 0) for t in trades
                               if t.get("yes_price", 100) <= price_ceiling * 100 + 2
                               and t.get("taker_side") == "yes")
                score = self._near_zero_score(m.yes_price, yes_buys, days, m.volume_24h)
                if yes_buys > 0:
                    opportunities.append(NearZeroOpportunity(
                        ticker=m.ticker,
                        title=m.title,
                        yes_price=m.yes_price,
                        buy_side="yes",
                        smart_money_volume=yes_buys,
                        days_to_close=days,
                        score=score,
                    ))

            # Check NO side (same logic, NO = 1 - YES)
            no_price = 1.0 - m.yes_price
            if no_price <= price_ceiling:
                trades = self.fetch_recent_trades(m.ticker, limit=50)
                no_buys = sum(t.get("count", 0) for t in trades
                              if t.get("yes_price", 0) >= (1 - price_ceiling) * 100 - 2
                              and t.get("taker_side") == "no")
                score = self._near_zero_score(no_price, no_buys, days, m.volume_24h)
                if no_buys > 0:
                    opportunities.append(NearZeroOpportunity(
                        ticker=m.ticker,
                        title=m.title,
                        yes_price=m.yes_price,
                        buy_side="no",
                        smart_money_volume=no_buys,
                        days_to_close=days,
                        score=score,
                    ))

        opportunities.sort(key=lambda o: o.score, reverse=True)
        logger.info("Found %d near-zero opportunities", len(opportunities))
        return opportunities

    @staticmethod
    def _near_zero_score(price: float, smart_vol: int, days: float, vol_24h: int) -> float:
        """
        Heuristic score.  Rewards:
        - lower price (higher potential payout)
        - higher smart money volume relative to 24h volume
        - reasonable time horizon (not too short, not too long)
        """
        payout_ratio = (1.0 / price) if price > 0 else 0
        vol_ratio = smart_vol / max(vol_24h, 1)
        time_factor = 1.0 / (1.0 + abs(days - 14) / 14)  # peaks at 14 days
        return payout_ratio * vol_ratio * time_factor

    # ------------------------------------------------------------------
    # Strategy 2: Category Specialist Detection
    # ------------------------------------------------------------------

    def detect_category_patterns(
        self, markets: list[MarketStats]
    ) -> dict[str, dict]:
        """
        Groups markets by category and computes volume-weighted price drift
        as a proxy for whether a category has price discovery efficiency.

        Returns per-category stats useful for filtering which categories to trade.
        """
        category_data: dict[str, list[float]] = defaultdict(list)

        for m in markets:
            if m.volume_24h > 0:
                category_data[m.category].append(m.yes_price)

        stats = {}
        for cat, prices in category_data.items():
            if len(prices) < 3:
                continue
            avg = sum(prices) / len(prices)
            # Markets near 0 or 1 indicate resolved or near-resolved events
            # Markets near 0.5 are uncertain — more room for edge
            near_50 = [p for p in prices if 0.3 <= p <= 0.7]
            stats[cat] = {
                "market_count": len(prices),
                "avg_price": avg,
                "contested_markets": len(near_50),
                "near_zero_markets": sum(1 for p in prices if p < 0.10),
                "near_one_markets": sum(1 for p in prices if p > 0.90),
            }

        return stats

    # ------------------------------------------------------------------
    # Strategy 3: Lagging Price Detection (Oracle Following)
    # ------------------------------------------------------------------

    def find_stale_prices(
        self,
        markets: list[MarketStats],
        external_signals: dict[str, float],
        staleness_threshold: float = 0.10,
    ) -> list[dict]:
        """
        Compare Kalshi market prices against external probability estimates.
        If the gap exceeds staleness_threshold, the market may be stale.

        external_signals: {ticker -> estimated_true_probability}
          Caller provides these from e.g. Polymarket, news sentiment, sports APIs.

        Returns list of {ticker, kalshi_price, signal_price, gap, suggested_side}
        """
        stale: list[dict] = []

        for m in markets:
            if m.ticker not in external_signals:
                continue
            signal_p = external_signals[m.ticker]
            gap = signal_p - m.yes_price

            if abs(gap) >= staleness_threshold:
                stale.append({
                    "ticker": m.ticker,
                    "title": m.title,
                    "kalshi_price": m.yes_price,
                    "signal_price": signal_p,
                    "gap": gap,
                    "suggested_side": "yes" if gap > 0 else "no",
                    "suggested_action": "buy",
                })

        stale.sort(key=lambda x: abs(x["gap"]), reverse=True)
        return stale
