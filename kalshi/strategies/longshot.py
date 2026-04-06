"""
Longshot Diversification - Kalshi native.

Buy cheap Yes/No contracts at 1-5¢ across many markets.
One correct 5¢ outcome offsets ~20 losses.
Diversify: 1-2 per category, max 10 total open.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")

_MIN_PRICE = 0.01
_MAX_PRICE = 0.05
_SIZE = 1.0
_MAX_CONTRACTS = 1
_MAX_PER_CAT = 2
_MAX_OPEN = 50
_MIN_DAYS = 1
_MAX_DAYS = 30


@dataclass
class LongshotPos:
    ticker: str
    side: str
    entry: float
    category: str


class LongshotStrategy:
    def __init__(self, client, analyzer):
        self.client = client
        self.analyzer = analyzer
        self._positions: dict[str, LongshotPos] = {}
        self._by_cat: dict[str, int] = {}

    def run_scan(self) -> list[dict]:
        markets = self.analyzer.fetch_all_markets()
        signals = []

        for mkt in markets:
            tokens = mkt.get("tokens", [])
            yes_t = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_t = next((t for t in tokens if t.get("outcome") == "No"), None)
            if not yes_t or not no_t:
                continue

            price = float(yes_t.get("price", 0.5))
            category = mkt.get("category", "unknown")

            # Check YES cheap
            if _MIN_PRICE <= price <= _MAX_PRICE:
                sig = self._evaluate(mkt, "yes", price, category)
                if sig:
                    signals.append(sig)

            # Check NO cheap
            no_price = float(no_t.get("price", 1 - price))
            if _MIN_PRICE <= no_price <= _MAX_PRICE:
                sig = self._evaluate(mkt, "no", no_price, category)
                if sig:
                    signals.append(sig)

        # Sort by cheapest first (more upside)
        signals.sort(key=lambda s: s["price"])
        return signals[:20]  # max 20 signals per cycle

    def _evaluate(self, mkt, side, price, category) -> dict | None:
        if mkt["ticker"] in self._positions:
            return None
        if self._by_cat.get(category, 0) >= _MAX_PER_CAT:
            return None
        if len(self._positions) >= _MAX_OPEN:
            return None

        end = mkt.get("endDate") or mkt.get("end_date_iso", "")
        days = self._days(end)
        if days < _MIN_DAYS or days > _MAX_DAYS:
            return None

        return {
            "ticker": mkt["ticker"],
            "side": side,
            "price": price,
            "contracts": _MAX_CONTRACTS,
            "action": "buy",
            "type": "limit",
            "title": mkt.get("question", ""),
            "category": category,
        }

    def execute_signal(self, sig: dict) -> bool:
        try:
            resp = self.client.place_order(
                ticker=sig["ticker"], action="buy", side=sig["side"],
                count=sig["contracts"], type="limit",
                yes_price=sig["price"] if sig["side"] == "yes" else None,
                no_price=sig["price"] if sig["side"] == "no" else None,
            )
            if resp.get("order"):
                self._positions[sig["ticker"]] = LongshotPos(
                    ticker=sig["ticker"], side=sig["side"],
                    entry=sig["price"], category=sig.get("category", "unknown"),
                )
                cat = sig.get("category", "unknown")
                self._by_cat[cat] = self._by_cat.get(cat, 0) + 1
                logger.info("Longshot: %s %s @ %.3f [%s]",
                           sig["ticker"], sig["side"].upper(), sig["price"], cat)
                return True
        except Exception as e:
            logger.error("Longshot failed: %s", e)
        return False

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Close positions that are about to resolve."""
        closed = []
        for ticker in list(self._positions):
            mp = mark_prices.get(ticker)
            if mp:
                price = mp.get(f"yes_{self._positions[ticker].side}_bid", 0)
                if price and price > 0.95:
                    try:
                        self.client.place_order(
                            ticker=ticker, action="sell",
                            side=self._positions[ticker].side,
                            count=1,
                        )
                    except: pass
                    cat = self._positions[ticker].category
                    self._by_cat[cat] = max(0, self._by_cat.get(cat, 0) - 1)
                    closed.append(ticker)
                    del self._positions[ticker]
        return closed

    @staticmethod
    def _days(end_str):
        if not end_str: return 999
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return max(0, (end - datetime.now(timezone.utc)).total_seconds() / 86400)
        except: return 999
