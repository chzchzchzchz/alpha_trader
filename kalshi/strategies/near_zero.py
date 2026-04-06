"""
Near-Zero Accumulation strategy.

Buys YES (or NO) contracts at very low prices when smart-money volume
is accumulating.  Expected value is positive if true probability > price.

Entry: YES price < 8¢ with meaningful buying volume
Exit:  price hits 3× entry, OR 7 days before close, OR stop at -60% of entry
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("trading")


@dataclass
class NearZeroConfig:
    price_ceiling: float = 0.08       # max entry price (fraction)
    min_volume_24h: int = 50           # minimum 24h market volume
    min_days_to_close: float = 5.0
    max_days_to_close: float = 45.0
    target_multiplier: float = 3.0    # take profit at 3× entry
    stop_loss_frac: float = 0.60      # stop if position down 60%
    max_contracts: int = 20           # max contracts per position
    min_smart_money_vol: int = 5      # min smart-money contracts to enter


class NearZeroStrategy:
    """
    Scans for near-zero markets with accumulation and opens positions.
    Manages exits based on price targets and time decay.
    """

    def __init__(self, client, analyzer, config: NearZeroConfig | None = None):
        self.client = client
        self.analyzer = analyzer
        self.cfg = config or NearZeroConfig()
        # ticker -> {side, entry_price, contracts, order_id}
        self._positions: dict[str, dict] = {}

    def run_scan(self) -> list[dict]:
        """Find new opportunities and return entry signals."""
        markets = self.analyzer.fetch_all_markets()
        opps = self.analyzer.find_near_zero_opportunities(
            markets,
            price_ceiling=self.cfg.price_ceiling,
            min_volume=self.cfg.min_volume_24h,
            min_days_to_close=self.cfg.min_days_to_close,
            max_days_to_close=self.cfg.max_days_to_close,
        )

        signals = []
        for opp in opps:
            if opp.ticker in self._positions:
                continue  # already in position
            if opp.smart_money_volume < self.cfg.min_smart_money_vol:
                continue

            contracts = min(
                self.cfg.max_contracts,
                max(1, int(opp.smart_money_volume * 0.1)),
            )
            signals.append({
                "ticker": opp.ticker,
                "title": opp.title,
                "action": "buy",
                "side": opp.buy_side,
                "contracts": contracts,
                "entry_price": opp.yes_price if opp.buy_side == "yes" else 1 - opp.yes_price,
                "score": opp.score,
                "days_to_close": opp.days_to_close,
            })
            logger.info(
                "NearZero signal: %s %s @ %.3f score=%.4f",
                opp.ticker, opp.buy_side, opp.yes_price, opp.score,
            )

        return signals

    def execute_signal(self, signal: dict) -> bool:
        """Place order for a near-zero signal."""
        price_cents = int(signal["entry_price"] * 100)
        try:
            resp = self.client.place_order(
                ticker=signal["ticker"],
                action="buy",
                side=signal["side"],
                count=signal["contracts"],
                type="limit",
                yes_price=price_cents if signal["side"] == "yes" else None,
                no_price=price_cents if signal["side"] == "no" else None,
            )
            order_id = resp.get("order", {}).get("order_id")
            if order_id:
                self._positions[signal["ticker"]] = {
                    "side": signal["side"],
                    "entry_price": signal["entry_price"],
                    "contracts": signal["contracts"],
                    "order_id": order_id,
                }
                logger.info("Opened position %s %s", signal["ticker"], order_id)
                return True
        except Exception as e:
            logger.error("Order failed for %s: %s", signal["ticker"], e)
        return False

    def check_exits(self, markets_by_ticker: dict[str, dict]) -> list[str]:
        """Check open positions for exit conditions. Returns list of closed tickers."""
        closed = []
        for ticker, pos in list(self._positions.items()):
            market = markets_by_ticker.get(ticker)
            if market is None:
                continue

            yes_mid = (market.get("yes_bid", 0) + market.get("yes_ask", 100)) / 2 / 100
            current = yes_mid if pos["side"] == "yes" else 1 - yes_mid
            entry = pos["entry_price"]

            take_profit = entry * self.cfg.target_multiplier
            stop_loss = entry * (1 - self.cfg.stop_loss_frac)

            should_exit = current >= take_profit or current <= stop_loss
            if should_exit:
                reason = "take_profit" if current >= take_profit else "stop_loss"
                try:
                    self.client.place_order(
                        ticker=ticker,
                        action="sell",
                        side=pos["side"],
                        count=pos["contracts"],
                        type="market",
                    )
                    pnl = (current - entry) * pos["contracts"] * 100
                    logger.info("Closed %s (%s) pnl=%.2f", ticker, reason, pnl)
                    del self._positions[ticker]
                    closed.append(ticker)
                except Exception as e:
                    logger.error("Exit order failed for %s: %s", ticker, e)

        return closed
