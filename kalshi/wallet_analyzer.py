"""
Wallet analyzer — scans Kalshi market data to identify profitable patterns.

Kalshi API field mapping (both demo+prod):
  Market endpoint returns: yes_bid_dollars, yes_ask_dollars, 
    volume_24h_fp, open_interest_fp, event_ticker, close_time (ISO8601)

We normalize everything for strategy consumption:
  - yes_bid/yes_ask as int cents
  - yes_mid_price as float 0.0-1.0
  - volume_24h as float
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
    event_ticker: str      # category proxy
    title: str
    yes_bid: int           # cents
    yes_ask: int           # cents
    yes_mid_price: float   # 0.0-1.0 midpoint
    volume_24h: float      # fill-point volume
    open_interest: float
    close_time: datetime | None
    status: str = "active"
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
    buy_side: str
    smart_money_volume: int
    days_to_close: float | None
    score: float


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int_cents(dollars: Any, default: int = 0) -> int:
    """Convert dollar float to int cents."""
    if dollars is None:
        return default
    try:
        return int(round(float(dollars) * 100))
    except (ValueError, TypeError):
        return default


def _parse_close_time(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class WalletAnalyzer:
    def __init__(self, client):
        self.client = client

    def fetch_all_markets(self, status: str | None = None) -> list[MarketStats]:
        """Page through open markets. Returns normalized MarketStats."""
        markets: list[MarketStats] = []
        cursor = None

        while True:
            try:
                resp = self.client.get_markets(limit=200, cursor=cursor, status=status)
            except Exception as e:
                logger.error("get_markets failed: %s", e, exc_info=True)
                break

            batch = resp.get("markets", [])
            if not batch:
                break

            for m in batch:
                # Kalshi API: yes_bid_dollars (float 0-1), volume_24h_fp (float)
                yes_bid = _safe_int_cents(m.get("yes_bid_dollars"))
                yes_ask = _safe_int_cents(m.get("yes_ask_dollars"))

                if yes_bid > 0 and yes_ask < 100 and yes_bid <= yes_ask:
                    yes_mid = (yes_bid + yes_ask) / 200.0
                else:
                    yes_mid = 0.0

                vol = _safe_float(m.get("volume_24h_fp"))
                oi = _safe_float(m.get("open_interest_fp"))
                events = m.get("event_ticker", "") or m.get("mve_collection_ticker", "unknown")

                # Skip markets with no liquidity AND no volume
                if yes_mid == 0 and vol == 0 and oi == 0:
                    continue

                markets.append(MarketStats(
                    ticker=m["ticker"],
                    event_ticker=events,
                    title=m.get("title", ""),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    yes_mid_price=yes_mid,
                    volume_24h=vol,
                    open_interest=oi,
                    close_time=_parse_close_time(m.get("close_time")),
                    status=m.get("status", "active"),
                ))

            cursor = resp.get("cursor")
            if not cursor:
                break

        logger.info("Fetched %d markets with pricing data (%d skipped illiquid)", 
                     len(markets), len(resp.get("markets", [])) - len(markets))
        return markets

    def fetch_recent_trades(self, ticker: str, limit: int = 100) -> list[dict]:
        try:
            resp = self.client.get_fills(limit=limit)
            fills = resp.get("fills", [])
            return [f for f in fills if f.get("ticker") == ticker][:limit]
        except Exception as e:
            logger.debug("Trade fetch failed for %s: %s", ticker, e)
            return []

    def find_near_zero_opportunities(
        self, markets: list[MarketStats],
        price_ceiling: float = 0.08,
        min_volume: float = 5.0,
        min_days_to_close: float = 0.1,
        max_days_to_close: float = 60.0,
    ) -> list[NearZeroOpportunity]:
        opportunities: list[NearZeroOpportunity] = []

        for m in markets:
            days = m.days_to_close
            if days is None or days < min_days_to_close or days > max_days_to_close:
                continue
            if yes_mid := m.yes_mid_price:
                # YES cheap
                if yes_mid <= price_ceiling and yes_mid > 0.001:
                    score = self._near_zero_score(yes_mid, days, m.volume_24h)
                    if score > 0:
                        opportunities.append(NearZeroOpportunity(
                            ticker=m.ticker, title=m.title,
                            yes_price=yes_mid, buy_side="yes",
                            smart_money_volume=int(m.volume_24h * 10),
                            days_to_close=days, score=score,
                        ))
                # NO cheap
                no_p = 1.0 - yes_mid
                if no_p <= price_ceiling and no_p > 0.001:
                    score = self._near_zero_score(no_p, days, m.volume_24h)
                    if score > 0:
                        opportunities.append(NearZeroOpportunity(
                            ticker=m.ticker, title=m.title,
                            yes_price=yes_mid, buy_side="no",
                            smart_money_volume=int(m.volume_24h * 10),
                            days_to_close=days, score=score,
                        ))

        opportunities.sort(key=lambda o: o.score, reverse=True)
        return opportunities

    @staticmethod
    def _near_zero_score(price: float, days: float, vol_24h: float) -> float:
        payout = (1.0 / price) if price > 0 else 0
        time_f = 1.0 / (1.0 + abs(days - 7) / 7)
        vol_f = min(1.0, vol_24h / 50.0)
        return payout * time_f * vol_f

    def detect_category_patterns(self, markets: list[MarketStats]) -> dict[str, dict]:
        cat_data: dict[str, list[MarketStats]] = defaultdict(list)
        for m in markets:
            if m.yes_mid_price > 0:
                cat_data[m.event_ticker].append(m)
        
        stats = {}
        for cat, mkts in sorted(cat_data.items(), key=lambda x: -len(x[1])):
            prices = [m.yes_mid_price for m in mkts if m.yes_mid_price > 0]
            if not prices:
                continue
            avg = sum(prices) / len(prices)
            stats[cat] = {
                "market_count": len(mkts),
                "avg_price": round(avg, 3),
                "contested": sum(1 for p in prices if 0.3 <= p <= 0.7),
                "near_zero": sum(1 for p in prices if p < 0.10),
                "near_one": sum(1 for p in prices if p > 0.90),
            }
        return stats

    def find_stale_prices(
        self, markets: list[MarketStats],
        external_signals: dict[str, float],
        staleness_threshold: float = 0.10,
    ) -> list[dict]:
        stale = []
        for m in markets:
            if m.ticker not in external_signals:
                continue
            sig_p = external_signals[m.ticker]
            gap = sig_p - m.yes_mid_price
            if abs(gap) >= staleness_threshold:
                stale.append({
                    "ticker": m.ticker, "title": m.title,
                    "kalshi_price": m.yes_mid_price,
                    "signal_price": sig_p, "gap": round(gap, 4),
                    "side": "yes" if gap > 0 else "no",
                })
        stale.sort(key=lambda x: abs(x["gap"]), reverse=True)
        return stale
