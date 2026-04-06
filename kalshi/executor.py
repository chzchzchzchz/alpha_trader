"""
Kalshi order executor — thin wrapper that runs all active strategies
in sequence and reports results.
"""
from __future__ import annotations

import logging

from core.metrics import metrics

logger = logging.getLogger("trading")


class KalshiExecutor:
    def __init__(self, client, strategies: list):
        self.client = client
        self.strategies = strategies
        self._trades_today = 0
        self._pnl_today = 0.0

    def run_cycle(self, markets, external_signals=None):
        markets_by_ticker = {m.ticker: m for m in markets}

        for strategy in self.strategies:
            name = type(strategy).__name__

            # Pattern A: strategy has execute_signal(signal) 
            # -> convergence, late_window, longshot, flash_crash, near_zero
            if hasattr(strategy, "execute_signal"):
                try:
                    signals = []
                    if hasattr(strategy, "generate_signals"):
                        signals = strategy.generate_signals(markets)
                    elif hasattr(strategy, "run_scan"):
                        signals = strategy.run_scan()

                    for sig in signals:
                        ok = strategy.execute_signal(sig)
                        if ok:
                            side = sig.get("side", "unknown")
                            metrics.inc("kalshi_fills_total", labels={"strategy": name, "side": side})
                            self._trades_today += 1
                except Exception as e:
                    logger.error("%s error: %s", name, e)

            # Pattern B: strategy generates signal objects (ticker, action, side, contracts, price)
            # -> category_specialist
            elif hasattr(strategy, "generate_signals"):
                try:
                    signals = strategy.generate_signals(markets)
                    for sig in signals:
                        yes_p = sig.get("yes_price")
                        no_p = sig.get("no_price")
                        resp = self.client.place_order(
                            ticker=sig["ticker"],
                            action=sig.get("action", "buy"),
                            side=sig.get("side", "yes"),
                            count=sig.get("contracts", 1),
                            yes_price=yes_p,
                            no_price=no_p,
                            expiration_type=sig.get("expiration_type", "GTC"),
                        )
                        if resp.get("order"):
                            metrics.inc("kalshi_fills_total",
                                        labels={"strategy": name, "side": sig.get("side", "unknown")})
                            self._trades_today += 1
                except Exception as e:
                    logger.error("%s error: %s", name, e)

            # Exit management for ALL strategies
            if hasattr(strategy, "check_exits") and callable(getattr(strategy, "check_exits")):
                try:
                    mark_prices = {}
                    for t, m in markets_by_ticker.items():
                        mark_prices[t] = {
                            "yes_bid": getattr(m, "yes_bid", None),
                            "yes_ask": getattr(m, "yes_ask", None),
                        }
                    closed = strategy.check_exits(mark_prices)
                    for _ in closed:
                        metrics.inc("kalshi_exits_total", labels={"strategy": name})
                except Exception as e:
                    logger.error("%s exit error: %s", name, e)

        metrics.set("kalshi_trades_today", self._trades_today)

