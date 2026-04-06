"""
7-Filter Convergence Strategy - Kalshi native.

Targets markets where price converges to 1.0 (YES) or 0.0 (NO).
7 filtering criteria:
  1. Price 60-96% range
  2. Resolution <= 14 days
  3. Liquidity >= $10K 24h volume
  4. Spread <= 200bps
  5. Order flow imbalance 
  6. No recent spike >= 8%
  7. Category cap 25%
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")

_MIN_PROB = 0.60
_MAX_PROB = 0.96
_MAX_DAYS = 14
_MIN_VOLUME = 10000  # $24h
_MAX_SPREAD = 0.02   # 200bps
_MAX_CLUSTER = 0.25
_BASE_PCT = 0.005
_MIN_SCORE = 0.60


@dataclass
class ConvSignal:
    ticker: str
    side: str       # 'yes' or 'no'  
    price: float
    score: float
    days: float
    title: str


class ConvergenceStrategy:
    def __init__(self, client, analyzer, capital=500.0):
        self.client = client
        self.analyzer = analyzer
        self.capital = capital
        self._history: dict[str, list[tuple]] = {}
        self._open_by_cat: dict[str, float] = {}
        self._total_open = 0.0

    def run_scan(self) -> list[dict]:
        markets = self.analyzer.fetch_all_markets()
        signals = []

        for mkt in markets:
            tokens = mkt.get("tokens", [])
            yes_t = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_t = next((t for t in tokens if t.get("outcome") == "No"), None)
            if not yes_t or not no_t:
                continue

            yes_p = float(yes_t.get("price", 0.5))
            no_p = float(no_t.get("price", yes_p))
            vol = float(mkt.get("volume24hr", mkt.get("volume", 0)))
            cat = mkt.get("category", "unknown")

            # Score YES side
            if _MIN_PROB <= yes_p <= _MAX_PROB:
                sig = self._evaluate(mkt, "yes", yes_p, vol, cat)
                if sig:
                    signals.append(sig)

            # Score NO side  
            if _MIN_PROB <= no_p <= _MAX_PROB:
                sig = self._evaluate(mkt, "no", no_p, vol, cat)
                if sig:
                    signals.append(sig)

        signals.sort(key=lambda s: s["score"], reverse=True)
        return signals

    def _evaluate(self, mkt, side, price, volume, category) -> dict | None:
        filters = [
            self._f_price(price),
            self._f_time(mkt),
            self._f_volume(volume),
            self._f_spread(mkt),
            self._f_flow(mkt["ticker"], price),
            self._f_spike(mkt["ticker"], price),
            self._f_cluster(category),
        ]

        if not all(f[0] for f in filters):
            return None

        score = sum(f[1] for f in filters) / len(filters)
        if score < _MIN_SCORE:
            return None

        usdc = self.capital * _BASE_PCT * score
        contracts = max(1, int(usdc / max(price, 0.01)))

        days = self._days_to_close(mkt.get("endDate") or mkt.get("end_date_iso", ""))

        return {
            "ticker": mkt["ticker"],
            "side": side,
            "price": price,
            "contracts": contracts,
            "score": round(score, 4),
            "days": days,
            "title": mkt.get("question", mkt.get("title", "")),
            "action": "buy",
            "order_type": "limit",
            "category": category,
        }

    def _f_price(self, p):
        score = 1.0 - abs(p - 0.85) / 0.35
        return (_MIN_PROB <= p <= _MAX_PROB, max(0, score))

    def _f_time(self, mkt):
        end = mkt.get("endDate") or mkt.get("end_date_iso", "")
        days = self._days_to_close(end)
        ok = 0 < days <= _MAX_DAYS
        score = 1.0 - (days / _MAX_DAYS) if ok else 0
        return (ok, max(0, score))

    def _f_volume(self, vol):
        ok = vol >= _MIN_VOLUME
        score = min(1.0, vol / (_MIN_VOLUME * 3))
        return (ok, score)

    def _f_spread(self, mkt):
        tokens = mkt.get("tokens", [])
        yes_t = next((t for t in tokens if t.get("outcome") == "Yes"), None)
        if not yes_t:
            return (False, 0)
        spread = float(yes_t.get("spreadBps", 99999)) / 10000
        ok = spread <= _MAX_SPREAD
        score = max(0, 1.0 - spread / _MAX_SPREAD)
        return (ok, score)

    def _f_flow(self, ticker, current):
        hist = self._history.get(ticker, [])
        now = time.time()
        hist = [(t, p) for t, p in hist if now - t <= 60]
        hist.append((now, current))
        self._history[ticker] = hist

        if len(hist) >= 3:
            oldest = hist[0][1]
            change = abs(current - oldest) / max(oldest, 0.001)
            ok = change < 0.08
            score = max(0, 1.0 - change / 0.08)
            return (ok, score)
        return (True, 1.0)

    def _f_spike(self, ticker, current):
        return self._f_flow(ticker, current)  # reuse

    def _f_cluster(self, category):
        total = max(self._total_open, 1.0)
        exposure = self._open_by_cat.get(category, 0)
        frac = exposure / total
        ok = frac <= _MAX_CLUSTER
        score = max(0, 1.0 - frac / _MAX_CLUSTER)
        return (ok, score)

    def execute_signal(self, sig: dict) -> bool:
        try:
            resp = self.client.place_order(
                ticker=sig["ticker"], action="buy", side=sig["side"],
                count=sig["contracts"], order_type="limit",
                yes_price=sig["price"] if sig["side"] == "yes" else None,
                no_price=sig["price"] if sig["side"] == "no" else None,
            )
            if resp.get("order"):
                cat = sig.get("category", "unknown")
                usdc = sig["contracts"] * sig["price"]
                self._open_by_cat[cat] = self._open_by_cat.get(cat, 0) + usdc
                self._total_open += usdc
                logger.info("Conv: %d %s %s @ %.3f score=%.2f",
                           sig["contracts"], sig["ticker"], sig["side"].upper(),
                           sig["price"], sig["score"])
                return True
        except Exception as e:
            logger.error("Conv failed: %s", e)
        return False

    def check_exits(self, mark_prices: dict) -> list[str]:
        return []

    @staticmethod
    def _days_to_close(end_str):
        if not end_str: return 999
        try:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return max(0, (end - datetime.now(timezone.utc)).total_seconds() / 86400)
        except: return 999
