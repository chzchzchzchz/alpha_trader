"""
Time-of-Day Sniper Strategy — "3AM Snipe"

FIFA UT parallel: Sneaky sniping at 3-5am when most players are asleep.
Kalshi equivalent: Market makers are LESS active at off-hours (early morning ET),
creating wider spreads, stale prices, and mispricings that persist until market open.

Human psychology: People are lazy, sleeping, not paying attention. The bot doesn't sleep.

Best windows:
- 3:00-6:00 AM ET: Minimal market maker activity, wide spreads
- 12:00-2:00 PM ET: Lunch lull in activity
- Weekends: Different liquidity profile entirely

Edge: Markets with >10c spreads during off-hours are often mispriced.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger("trading")

# ── ET timezone offsets from UTC ─────────────────────────────────────
_ET_UTC_OFFSET = -5  # EST (adjust for EDT dynamically in production)

# ── Snipe windows (Eastern Time hours) ────────────────────────────────
_SNIPE_WINDOWS = [
    (3, 6),     # Deep night: best snipe window
    (12, 14),   # Lunch lull
]

_WEEKEND_MULTIPLIER = 1.5  # More opportunities on weekends

# ── Entry parameters ─────────────────────────────────────────────────
_MIN_SPREAD_CENTS = 12     # Minimum spread in cents to consider
_MIN_VOLUME = 20           # Minimum 24h volume
_MAX_PRICE = 0.85          # Don't snipe already-resolved prices
_MIN_PRICE = 0.15          # Don't snipe worthless prices
_SIZE_USDC = 5.0           # Per-position
_MAX_OPEN = 5              # Max concurrent positions


@dataclass
class ToDPos:
    ticker: str
    side: str
    entry_yes: float
    entry_spread: float
    t0: float


class TimeOfDaySniperStrategy:
    """
    Exploits off-hours market maker inattention.
    Buys mispriced contracts during low-activity windows.
    Takes profit when spreads normalize during active hours.
    """

    def __init__(self, client, analyzer):
        self.client = client
        self.analyzer = analyzer
        self._positions: dict[str, ToDPos] = {}

    # ── Time helpers ──────────────────────────────────────────────────

    @classmethod
    def is_snipe_window(cls) -> bool:
        """Check if current time is within any snipe window (ET)."""
        now_utc = datetime.now(timezone.utc)
        et_hour = (now_utc.hour + _ET_UTC_OFFSET) % 24

        for start, end in _SNIPE_WINDOWS:
            if start <= et_hour < end:
                return True
        return False

    @classmethod
    def is_weekend(cls) -> bool:
        now_utc = datetime.now(timezone.utc)
        return now_utc.weekday() >= 5  # Sat=5, Sun=6

    # ── Signal generation ─────────────────────────────────────────────

    def run_scan(self) -> list[dict]:
        """Look for wide-spread markets during off-hours."""
        if not self.is_snipe_window():
            logger.debug("TimeSniper: outside snipe window, skipping")
            return []

        try:
            markets = self.analyzer.fetch_all_markets()
        except Exception as e:
            logger.error("TimeSniper scan failed: %s", e)
            return []

        signals = []

        for mkt in markets:
            ticker = mkt.get("ticker", "")
            yes_mid = mkt.get("yes_mid_price", 0)
            yes_bid = mkt.get("yes_bid", 0)
            yes_ask = mkt.get("yes_ask", 100)

            if not ticker or not yes_mid:
                continue
            if ticker in self._positions:
                continue
            if len(self._positions) >= _MAX_OPEN:
                break

            spread = yes_ask - yes_bid
            if spread < _MIN_SPREAD_CENTS:
                continue
            if yes_mid < _MIN_PRICE or yes_mid > _MAX_PRICE:
                continue
            if mkt.get("volume_24h", 0) < _MIN_VOLUME:
                continue

            # During snipe windows, wide spreads mean stale prices
            # Buy at the mid when spread is abnormally wide
            # If yes_mid < 0.5, the mid is biased toward "no" — buy yes
            # If yes_mid > 0.5, the mid is biased toward "yes" — sell yes (buy no)
            if yes_mid < 0.5:
                side = "yes"
                price = yes_bid  # Bid aggressively
            else:
                side = "no"
                price = 100 - yes_ask  # Ask aggressively for NO

            edge_pct = spread / max(yes_mid * 100, 1)
            confidence = min(1.0, edge_pct / 0.5)

            signals.append({
                "ticker": ticker,
                "action": "buy",
                "side": side,
                "contracts": 2,
                "type": "limit",
                "yes_price": price if side == "yes" else None,
                "no_price": price if side == "no" else None,
                "title": f"TimeSnipe: {ticker} spread={spread}c mid={yes_mid:.3f}",
                "spread_cents": spread,
                "confidence": confidence,
                "strategy_type": "time_sniper",
            })

        signals.sort(key=lambda s: s["spread_cents"], reverse=True)
        return signals[:5]

    # ── Execution ─────────────────────────────────────────────────────

    def execute_signal(self, sig: dict) -> bool:
        """Enter the snipe position."""
        ticker = sig["ticker"]
        try:
            resp = self.client.place_order(
                ticker=ticker,
                action="buy",
                side=sig["side"],
                count=sig["contracts"],
                type="limit",
                yes_price=sig.get("yes_price"),
                no_price=sig.get("no_price"),
            )

            if resp.get("order"):
                self._positions[ticker] = ToDPos(
                    ticker=ticker,
                    side=sig["side"],
                    entry_yes=sig.get("yes_price", 50) / 100,
                    entry_spread=sig.get("spread_cents", 0),
                    t0=0,
                )
                logger.info(
                    "TimeSniper: %s %s @ %.3f spread=%dc",
                    ticker, sig["side"].upper(),
                    sig.get("yes_price", 0),
                    sig.get("spread_cents", 0),
                )
                return True
        except Exception as e:
            logger.error("TimeSniper failed on %s: %s", ticker, e)

        return False

    # ── Exit management ───────────────────────────────────────────────

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Exit when spreads tighten during active hours."""
        closed = []

        for ticker, pos in list(self._positions.items()):
            mp = mark_prices.get(ticker)
            if not mp:
                continue

            spread = mp.get("yes_ask", 100) - mp.get("yes_bid", 0)

            # Exit when spread normalizes (<8c)
            if spread < 8:
                logger.info("TimeSniper exit: %s spread narrowed to %dc", ticker, spread)
                closed.append(ticker)
                continue

            # Exit if we're now in peak hours (spreads naturally tighten)
            if self.is_active_hours():
                logger.info("TimeSniper: peak hours, exiting %s to capture spread normalization", ticker)
                closed.append(ticker)

        for t in closed:
            self._positions.pop(t, None)

        return closed

    @classmethod
    def is_active_hours(cls) -> bool:
        """During active market hours (9AM-4PM ET weekdays), spreads tighten."""
        now_utc = datetime.now(timezone.utc)
        et_hour = (now_utc.hour + _ET_UTC_OFFSET) % 24
        is_weekday = now_utc.weekday() < 5
        return is_weekday and 9 <= et_hour < 16

    def active_positions(self) -> int:
        return len(self._positions)
