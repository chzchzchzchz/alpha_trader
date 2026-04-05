"""
Kalshi order executor — thin wrapper that runs all active strategies
in sequence and reports results.
"""
from __future__ import annotations

import logging
from typing import Any

from core.metrics import metrics

logger = logging.getLogger("trading")


class KalshiExecutor:
    def __init__(self, client, strategies: list):
        self.client = client
        self.strategies = strategies
        self._trades_today = 0
        self._pnl_today = 0.0

    def run_cycle(self, markets, external_signals: dict[str, float] | None = None) -> None:
        markets_by_ticker = {m.ticker: m for m in markets}

        for strategy in self.strategies:
            name = type(strategy).__name__

            # --- Near-Zero ---
            if hasattr(strategy, "run_scan"):
                try:
                    signals = strategy.run_scan()
                    for sig in signals:
                        ok = strategy.execute_signal(sig)
                        metrics.inc("kalshi_orders_total", labels={"strategy": name, "side": sig["side"]})
                        if ok:
                            metrics.inc("kalshi_fills_total", labels={"strategy": name})
                            self._trades_today += 1
                except Exception as e:
                    logger.error("%s scan error: %s", name, e)

                if hasattr(strategy, "check_exits"):
                    try:
                        closed = strategy.check_exits(
                            {t: {"yes_bid": int(m.yes_price * 100) - 1,
                                 "yes_ask": int(m.yes_price * 100) + 1}
                             for t, m in markets_by_ticker.items()}
                        )
                        for t in closed:
                            metrics.inc("kalshi_exits_total", labels={"strategy": name})
                    except Exception as e:
                        logger.error("%s exit error: %s", name, e)

            # --- Category Specialist ---
            if hasattr(strategy, "generate_signals"):
                try:
                    signals = strategy.generate_signals(markets)
                    for sig in signals:
                        resp = self.client.place_order(
                            ticker=sig["ticker"],
                            action=sig["action"],
                            side=sig["side"],
                            count=sig["contracts"],
                            order_type="limit",
                            yes_price=sig["price_cents"] if sig["side"] == "yes" else None,
                            no_price=sig["price_cents"] if sig["side"] == "no" else None,
                        )
                        if resp.get("order"):
                            metrics.inc("kalshi_fills_total", labels={"strategy": name})
                            self._trades_today += 1
                except Exception as e:
                    logger.error("%s signal error: %s", name, e)

            # --- Oracle Follow ---
            if hasattr(strategy, "find_arbitrage_signals") and external_signals:
                try:
                    signals = strategy.find_arbitrage_signals(markets, external_signals)
                    for sig in signals:
                        ok = strategy.execute_signal(sig)
                        if ok:
                            metrics.inc("kalshi_fills_total", labels={"strategy": name})
                            self._trades_today += 1
                    strategy.close_expired_positions()
                except Exception as e:
                    logger.error("%s oracle error: %s", name, e)

        metrics.set("kalshi_trades_today", self._trades_today)
        logger.info("Cycle complete — %d trades today", self._trades_today)
