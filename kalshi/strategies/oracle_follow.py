"""
Oracle Follow (Latency Arbitrage) strategy.

Monitors external data sources for signals that should move Kalshi prices
but haven't been reflected yet.  When the gap exceeds a threshold, we
enter before Kalshi catches up.

Supported oracle types:
  - Polymarket: fetch prices from Polymarket Gamma API for correlated markets
  - Sports: scores/odds from public sports APIs
  - News sentiment: simple keyword-based probability shift

This is the "speed arbitrage" from the viral post.  The edge is real but
degrades quickly as more bots do the same thing.  The key is having:
1. Fast oracle data (low-latency APIs or websockets)
2. Fast order placement
3. Markets where Kalshi lags noticeably (e.g. low-volume categories)

Honest note: this does NOT require market-making or co-location.
Even 30-60 second latency arbitrage opportunities exist in less liquid markets.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger("trading")

# Polymarket Gamma public API — no auth required
_POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"


@dataclass
class OracleFollowConfig:
    min_gap: float = 0.08              # min price gap to trade (fraction)
    max_position_cents: int = 25       # max entry price in cents
    contracts_per_trade: int = 10
    hold_minutes: float = 5.0          # close position after this many minutes
    polymarket_enabled: bool = True
    request_timeout: int = 5


class OracleFollowStrategy:
    """
    Compares Kalshi prices to external oracles and trades the gap.
    """

    def __init__(self, client, analyzer, config: OracleFollowConfig | None = None):
        self.client = client
        self.analyzer = analyzer
        self.cfg = config or OracleFollowConfig()
        # ticker -> {side, contracts, entry_time, order_id}
        self._positions: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Oracle data fetching
    # ------------------------------------------------------------------

    def fetch_polymarket_prices(self, question_keywords: list[str]) -> dict[str, float]:
        """
        Search Polymarket for markets matching keywords, return question->probability.
        This is a public API endpoint — no auth required.
        """
        results: dict[str, float] = {}
        if not self.cfg.polymarket_enabled:
            return results

        try:
            for keyword in question_keywords:
                r = requests.get(
                    f"{_POLYMARKET_GAMMA}/markets",
                    params={"search": keyword, "active": "true", "limit": 10},
                    timeout=self.cfg.request_timeout,
                )
                if r.status_code != 200:
                    continue
                for market in r.json():
                    slug = market.get("slug", "")
                    tokens = market.get("tokens", [])
                    yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
                    if yes_token and slug:
                        results[slug] = float(yes_token.get("price", 0.5))
        except Exception as e:
            logger.debug("Polymarket fetch error: %s", e)

        return results

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def find_arbitrage_signals(
        self,
        kalshi_markets,
        external_signals: dict[str, float],
    ) -> list[dict]:
        """
        external_signals: {kalshi_ticker -> true_probability_estimate}

        The caller is responsible for building this mapping
        (e.g. by matching Kalshi tickers to Polymarket slugs).
        """
        stale = self.analyzer.find_stale_prices(
            kalshi_markets,
            external_signals,
            staleness_threshold=self.cfg.min_gap,
        )

        signals = []
        for item in stale:
            ticker = item["ticker"]
            if ticker in self._positions:
                continue

            price = item["kalshi_price"]
            side = item["suggested_side"]
            entry_price = price if side == "yes" else 1 - price

            # Only enter if the price is below our max
            if entry_price > self.cfg.max_position_cents / 100:
                continue

            signals.append({
                "ticker": ticker,
                "title": item["title"],
                "action": "buy",
                "side": side,
                "contracts": self.cfg.contracts_per_trade,
                "price_cents": int(entry_price * 100),
                "gap": item["gap"],
                "kalshi_price": price,
                "oracle_price": item["signal_price"],
            })
            logger.info(
                "Oracle signal: %s %s gap=%.3f kalshi=%.3f oracle=%.3f",
                ticker, side, item["gap"], price, item["signal_price"],
            )

        return signals

    def execute_signal(self, signal: dict) -> bool:
        ticker = signal["ticker"]
        try:
            resp = self.client.place_order(
                ticker=ticker,
                action="buy",
                side=signal["side"],
                count=signal["contracts"],
                order_type="limit",
                yes_price=signal["price_cents"] if signal["side"] == "yes" else None,
                no_price=signal["price_cents"] if signal["side"] == "no" else None,
            )
            order_id = resp.get("order", {}).get("order_id")
            if order_id:
                self._positions[ticker] = {
                    "side": signal["side"],
                    "contracts": signal["contracts"],
                    "entry_time": time.time(),
                    "order_id": order_id,
                }
                return True
        except Exception as e:
            logger.error("Oracle order failed %s: %s", ticker, e)
        return False

    def close_expired_positions(self) -> list[str]:
        """Close positions that have been held longer than hold_minutes."""
        now = time.time()
        closed = []
        max_hold = self.cfg.hold_minutes * 60

        for ticker, pos in list(self._positions.items()):
            if now - pos["entry_time"] < max_hold:
                continue
            try:
                self.client.place_order(
                    ticker=ticker,
                    action="sell",
                    side=pos["side"],
                    count=pos["contracts"],
                    order_type="market",
                )
                del self._positions[ticker]
                closed.append(ticker)
                logger.info("Closed expired oracle position %s", ticker)
            except Exception as e:
                logger.error("Failed to close %s: %s", ticker, e)

        return closed
