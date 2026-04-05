"""
Arbitrage detector.

Finds three types of risk-free (or near risk-free) opportunities:

1. CROSS-PLATFORM ARB
   Buy YES on Polymarket + Buy NO on Kalshi (or vice versa) for the same event.
   Cost = poly_yes + kalshi_no  (or  kalshi_yes + poly_no)
   Profit = $1.00 - cost  (guaranteed at resolution)
   Example: YES @ 42¢ on Poly + NO @ 57¢ on Kalshi = $0.99 cost → $0.01 profit

2. BUNDLE ARB (single platform)
   On Kalshi or Polymarket: if YES + NO < $1.00 on the same market,
   buying both guarantees $1.00 payout for < $1.00 cost.
   This happens rarely but does occur in thin books.

3. PRICE LAG ARB
   One platform is significantly lagging the other on price discovery.
   Not risk-free but high-probability directional trade.

Research: $40M extracted in arb profits Apr 2024-Apr 2025.
Most common opportunity is bundle arb during low-liquidity periods.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("trading")

ArbType = Literal["cross_platform", "bundle_kalshi", "bundle_poly", "price_lag"]


@dataclass
class ArbOpportunity:
    arb_type: ArbType
    expected_profit_frac: float   # profit as fraction of total cost
    expected_profit_usdc: float   # profit in USD per $1 wagered
    # Cross-platform arb fields
    kalshi_ticker: str = ""
    kalshi_action: str = ""       # "yes" or "no"
    kalshi_price: float = 0.0
    poly_token_id: str = ""
    poly_action: str = ""         # "YES" or "NO"
    poly_price: float = 0.0
    # Shared
    total_cost: float = 0.0
    payout: float = 1.0
    match_score: float = 0.0
    title: str = ""

    @property
    def roi(self) -> float:
        return (self.payout - self.total_cost) / self.total_cost if self.total_cost else 0.0


class ArbDetector:
    def __init__(
        self,
        min_profit_frac: float = 0.005,   # 0.5% minimum profit to bother
        min_match_score: float = 0.60,    # minimum fuzzy match confidence
    ):
        self.min_profit_frac = min_profit_frac
        self.min_match_score = min_match_score

    # ------------------------------------------------------------------
    # Cross-platform arb
    # ------------------------------------------------------------------

    def find_cross_platform_arb(self, matched_pairs: list) -> list[ArbOpportunity]:
        """
        Check each matched pair for cross-platform arbitrage.

        For each matched pair:
          Strategy A: buy YES on Kalshi + NO on Polymarket
          Strategy B: buy NO on Kalshi + YES on Polymarket
        Both pay $1 at resolution; we want total cost < $1.
        """
        opportunities: list[ArbOpportunity] = []

        for pair in matched_pairs:
            if pair.match_score < self.min_match_score:
                continue

            kalshi_yes = pair.kalshi_yes_price
            kalshi_no  = 1.0 - kalshi_yes
            poly_yes   = pair.poly_yes_price
            poly_no    = 1.0 - poly_yes

            # Strategy A: YES on Kalshi + NO on Poly
            cost_a = kalshi_yes + poly_no
            if cost_a < 1.0:
                profit = 1.0 - cost_a
                if profit / cost_a >= self.min_profit_frac:
                    opportunities.append(ArbOpportunity(
                        arb_type="cross_platform",
                        expected_profit_frac=profit / cost_a,
                        expected_profit_usdc=profit,
                        kalshi_ticker=pair.kalshi_ticker,
                        kalshi_action="yes",
                        kalshi_price=kalshi_yes,
                        poly_token_id=pair.poly_token_id_no,
                        poly_action="NO",
                        poly_price=poly_no,
                        total_cost=cost_a,
                        payout=1.0,
                        match_score=pair.match_score,
                        title=pair.kalshi_title,
                    ))

            # Strategy B: NO on Kalshi + YES on Poly
            cost_b = kalshi_no + poly_yes
            if cost_b < 1.0:
                profit = 1.0 - cost_b
                if profit / cost_b >= self.min_profit_frac:
                    opportunities.append(ArbOpportunity(
                        arb_type="cross_platform",
                        expected_profit_frac=profit / cost_b,
                        expected_profit_usdc=profit,
                        kalshi_ticker=pair.kalshi_ticker,
                        kalshi_action="no",
                        kalshi_price=kalshi_no,
                        poly_token_id=pair.poly_token_id_yes,
                        poly_action="YES",
                        poly_price=poly_yes,
                        total_cost=cost_b,
                        payout=1.0,
                        match_score=pair.match_score,
                        title=pair.kalshi_title,
                    ))

        opportunities.sort(key=lambda o: o.expected_profit_frac, reverse=True)
        logger.info("Cross-platform arb: %d opportunities found", len(opportunities))
        return opportunities

    # ------------------------------------------------------------------
    # Bundle arb (single platform)
    # ------------------------------------------------------------------

    def find_kalshi_bundle_arb(self, markets: list) -> list[ArbOpportunity]:
        """
        Kalshi: YES + NO should always sum to ~$1.
        If YES_ask + NO_ask < $1, buying both is risk-free.
        """
        opportunities = []
        for m in markets:
            # We need ask prices, not mid.  Use yes_price as a proxy for ask.
            # In practice, query the orderbook for true ask prices.
            yes_price = m.yes_price       # mid approximation
            no_price  = 1.0 - yes_price
            cost      = yes_price + no_price   # always ~1.0 at mid
            # Bundle arb requires ask(YES) + ask(NO) < 1.0
            # At mid this is always ~1.0, so we need spread data.
            # Flag markets where the spread is wide enough to create opportunity.
            # Typical Kalshi spread: 2-4¢.  If spread is 6¢+, bundle arb may exist.
            spread_proxy = abs(yes_price - 0.5) * 2  # wider away from 50¢
            if spread_proxy > 0.06:
                logger.debug(
                    "Wide spread candidate: %s yes=%.3f (spread_proxy=%.3f)",
                    m.ticker, yes_price, spread_proxy
                )
        return opportunities  # real detection needs live orderbook ask prices

    def find_poly_bundle_arb(self, poly_markets: list[dict],
                              poly_client) -> list[ArbOpportunity]:
        """
        Polymarket: check live orderbook ask prices for bundle arb.
        """
        opportunities = []
        for market in poly_markets:
            tokens = market.get("tokens", [])
            yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_token  = next((t for t in tokens if t.get("outcome") == "No"),  None)
            if not yes_token or not no_token:
                continue

            try:
                yes_book = poly_client.get_orderbook(yes_token.get("token_id", ""))
                no_book  = poly_client.get_orderbook(no_token.get("token_id", ""))
                yes_ask  = self._best_ask(yes_book)
                no_ask   = self._best_ask(no_book)
                if yes_ask and no_ask:
                    cost = yes_ask + no_ask
                    if cost < 1.0:
                        profit = 1.0 - cost
                        if profit / cost >= self.min_profit_frac:
                            opportunities.append(ArbOpportunity(
                                arb_type="bundle_poly",
                                expected_profit_frac=profit / cost,
                                expected_profit_usdc=profit,
                                poly_token_id=yes_token.get("token_id", ""),
                                poly_price=yes_ask,
                                total_cost=cost,
                                payout=1.0,
                                title=market.get("question", ""),
                            ))
            except Exception:
                pass

        opportunities.sort(key=lambda o: o.expected_profit_frac, reverse=True)
        return opportunities

    # ------------------------------------------------------------------
    # Price lag (directional, not risk-free)
    # ------------------------------------------------------------------

    def find_price_lag(
        self, matched_pairs: list,
        lag_threshold: float = 0.05,
    ) -> list[ArbOpportunity]:
        """
        Find markets where one platform is lagging the other by > lag_threshold.
        NOT risk-free — assumes the lagging platform will converge.
        """
        opportunities = []
        for pair in matched_pairs:
            if pair.match_score < self.min_match_score:
                continue
            gap = pair.kalshi_yes_price - pair.poly_yes_price
            if abs(gap) >= lag_threshold:
                # Trade the lagging platform toward the leading platform's price
                if gap > 0:
                    # Kalshi is higher — sell YES on Kalshi (or buy NO)
                    # OR buy YES on Polymarket (cheaper)
                    opportunities.append(ArbOpportunity(
                        arb_type="price_lag",
                        expected_profit_frac=abs(gap),
                        expected_profit_usdc=abs(gap),
                        kalshi_ticker=pair.kalshi_ticker,
                        kalshi_action="no",
                        kalshi_price=1.0 - pair.kalshi_yes_price,
                        poly_token_id=pair.poly_token_id_yes,
                        poly_action="YES",
                        poly_price=pair.poly_yes_price,
                        total_cost=pair.poly_yes_price,
                        match_score=pair.match_score,
                        title=pair.kalshi_title,
                    ))
                else:
                    # Polymarket is higher — buy YES on Kalshi
                    opportunities.append(ArbOpportunity(
                        arb_type="price_lag",
                        expected_profit_frac=abs(gap),
                        expected_profit_usdc=abs(gap),
                        kalshi_ticker=pair.kalshi_ticker,
                        kalshi_action="yes",
                        kalshi_price=pair.kalshi_yes_price,
                        poly_token_id=pair.poly_token_id_no,
                        poly_action="NO",
                        poly_price=1.0 - pair.poly_yes_price,
                        total_cost=pair.kalshi_yes_price,
                        match_score=pair.match_score,
                        title=pair.kalshi_title,
                    ))

        opportunities.sort(key=lambda o: o.expected_profit_frac, reverse=True)
        logger.info("Price lag opportunities: %d (threshold=%.2f)", len(opportunities), lag_threshold)
        return opportunities

    @staticmethod
    def _best_ask(orderbook: dict) -> float | None:
        asks = orderbook.get("asks") or []
        if not asks:
            return None
        return float(asks[0].get("price", asks[0].get("p", 0)))
