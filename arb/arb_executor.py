"""
Arbitrage executor.

Simultaneously executes both legs of an arbitrage opportunity.
Speed matters — use market orders, not limit orders.

For cross-platform arb, both legs must fill for the trade to be risk-free.
If one leg fails, we try to cancel or reverse the other.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from core.metrics import metrics

logger = logging.getLogger("trading")


@dataclass
class ArbResult:
    opportunity_id: str
    kalshi_filled: bool
    poly_filled: bool
    actual_cost: float
    expected_profit_usdc: float
    realized_pnl: float = 0.0
    error: str = ""

    @property
    def both_legs_filled(self) -> bool:
        return self.kalshi_filled and self.poly_filled


class ArbExecutor:
    def __init__(
        self,
        kalshi_client,
        poly_client,
        max_usdc_per_arb: float = 100.0,
        min_profit_usdc: float = 0.10,
        dry_run: bool = True,
    ):
        self.kalshi  = kalshi_client
        self.poly    = poly_client
        self.max_usdc = max_usdc_per_arb
        self.min_profit = min_profit_usdc
        self.dry_run = dry_run
        self._daily_pnl: float = 0.0

    def execute(self, opp, contracts: int = 10) -> ArbResult:
        """
        Execute both legs of a cross-platform arb opportunity.

        contracts: number of $1-payout contracts to buy on each side.
                   Cost = contracts * (yes_price + no_price)
        """
        result_id = f"{opp.kalshi_ticker}_{int(time.time())}"
        total_cost = opp.total_cost * contracts
        expected   = (1.0 - opp.total_cost) * contracts

        if total_cost > self.max_usdc:
            logger.info("Arb capped at $%.2f (opportunity cost=$%.2f)", self.max_usdc, total_cost)
            contracts = max(1, int(self.max_usdc / opp.total_cost))
            total_cost = opp.total_cost * contracts
            expected   = (1.0 - opp.total_cost) * contracts

        if expected < self.min_profit:
            logger.debug("Skipping arb — expected profit $%.4f < min $%.4f",
                         expected, self.min_profit)
            return ArbResult(result_id, False, False, total_cost, expected,
                             error="below min profit threshold")

        logger.info(
            "ARB [%s] %s %s @ %.3f + POLY %s @ %.3f  cost=%.3f exp_profit=$%.4f x%d",
            opp.arb_type, opp.kalshi_ticker, opp.kalshi_action.upper(), opp.kalshi_price,
            opp.poly_action, opp.poly_price, opp.total_cost, expected, contracts,
        )

        if self.dry_run:
            logger.info("[DRY RUN] Would execute arb for $%.4f profit", expected)
            metrics.inc("arb_dry_run_total", labels={"type": opp.arb_type})
            return ArbResult(result_id, True, True, total_cost, expected,
                             realized_pnl=expected)

        kalshi_ok = False
        poly_ok   = False
        kalshi_err = ""
        poly_err   = ""

        # Execute both legs concurrently to minimize slippage
        def run_kalshi():
            nonlocal kalshi_ok, kalshi_err
            try:
                resp = self.kalshi.place_order(
                    ticker=opp.kalshi_ticker,
                    action="buy",
                    side=opp.kalshi_action,
                    count=contracts,
                    order_type="market",
                )
                kalshi_ok = bool(resp.get("order"))
            except Exception as e:
                kalshi_err = str(e)

        def run_poly():
            nonlocal poly_ok, poly_err
            try:
                resp = self.poly.place_market_order(
                    token_id=opp.poly_token_id,
                    side=opp.poly_action,
                    amount_usdc=opp.poly_price * contracts,
                )
                poly_ok = bool(resp)
            except Exception as e:
                poly_err = str(e)

        t_kalshi = threading.Thread(target=run_kalshi, daemon=True)
        t_poly   = threading.Thread(target=run_poly,   daemon=True)
        t_kalshi.start()
        t_poly.start()
        t_kalshi.join(timeout=5.0)
        t_poly.join(timeout=5.0)

        # If one leg failed, try to reverse the filled leg
        if kalshi_ok and not poly_ok:
            logger.error("Poly leg failed (%s) — attempting Kalshi reversal", poly_err)
            try:
                self.kalshi.place_order(
                    ticker=opp.kalshi_ticker,
                    action="sell",
                    side=opp.kalshi_action,
                    count=contracts,
                    order_type="market",
                )
            except Exception as e:
                logger.error("Kalshi reversal failed: %s — MANUAL ACTION REQUIRED", e)

        if poly_ok and not kalshi_ok:
            logger.error("Kalshi leg failed (%s) — attempting Poly reversal", kalshi_err)
            try:
                self.poly.place_market_order(
                    token_id=opp.poly_token_id,
                    side="SELL" if opp.poly_action == "YES" else "BUY",
                    amount_usdc=opp.poly_price * contracts,
                )
            except Exception as e:
                logger.error("Poly reversal failed: %s — MANUAL ACTION REQUIRED", e)

        pnl = expected if (kalshi_ok and poly_ok) else 0.0
        self._daily_pnl += pnl

        metrics.inc("arb_attempts_total", labels={"type": opp.arb_type})
        if kalshi_ok and poly_ok:
            metrics.inc("arb_success_total", labels={"type": opp.arb_type})
            metrics.inc("arb_pnl_total", value=pnl)

        error_msg = " | ".join(filter(None, [kalshi_err, poly_err]))
        return ArbResult(
            opportunity_id=result_id,
            kalshi_filled=kalshi_ok,
            poly_filled=poly_ok,
            actual_cost=total_cost,
            expected_profit_usdc=expected,
            realized_pnl=pnl,
            error=error_msg,
        )

    def run_scan_and_execute(
        self,
        kalshi_markets: list,
        poly_markets: list,
        matcher,
        detector,
        contracts_per_arb: int = 5,
    ) -> list[ArbResult]:
        """
        Full pipeline: match → detect → execute.
        """
        pairs = matcher.match(kalshi_markets, poly_markets)
        all_opps = detector.find_cross_platform_arb(pairs)
        all_opps += detector.find_price_lag(pairs)

        results = []
        for opp in all_opps:
            result = self.execute(opp, contracts=contracts_per_arb)
            if result.both_legs_filled:
                logger.info("Arb filled: $%.4f profit", result.realized_pnl)
            results.append(result)

        metrics.set("arb_daily_pnl", self._daily_pnl)
        return results
