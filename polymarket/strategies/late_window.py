"""
Late-Window Snipe Strategy.

Source: LuciferForge/polymarket-btc-autotrader (claimed 94% WR, 17W/1L)

Applies to short-duration binary markets (e.g., BTC price in 15 minutes).
The thesis: in the final 1-2 minutes of a binary market, price action is
nearly deterministic — the apparent winner is almost certain to win, and
late-window price is a near-perfect predictor of resolution.

Entry criteria:
  - Market closes within ENTRY_WINDOW_SECONDS (default: 90s)
  - Current YES price ≥ ENTRY_THRESHOLD (default: 0.93)
  - Sufficient liquidity to fill

Edge: You're buying a 93¢ contract that will resolve to $1.00 in 90 seconds.
ROI = 7.5% in 90 seconds.  High frequency = meaningful returns.

Risk: If price drops from 0.93 to 0.00 in the final seconds (upset), loss is 93¢.
The 94% WR claim reflects that late-window leaders very rarely lose.

Also implements the Reddit FOMO pattern from AstroTick:
  Entry when price breaches TRIGGER_POINT_PRICE within TRIGGER_MINUTES of close.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")


@dataclass
class LateWindowConfig:
    entry_window_seconds: float = 90.0    # enter in last 90 seconds
    entry_threshold_price: float = 0.93   # buy YES if ≥ 93¢
    no_entry_threshold: float = 0.07      # buy NO if ≤ 7¢ (= 93¢ NO)
    trade_size_usdc: float = 10.0
    max_open: int = 3                     # max simultaneous late-window bets
    # Reddit/FOMO trigger
    trigger_price: float = 0.70           # price breach triggers monitoring
    trigger_minutes_remaining: float = 3.0
    exit_price: float = 0.90             # exit at 90¢ if triggered early


@dataclass
class LateWindowPosition:
    token_id: str
    market_title: str
    entry_price: float
    side: str
    close_time: float        # Unix timestamp
    amount_usdc: float
    mode: str                # 'snipe' or 'trigger'


class LateWindowStrategy:
    """
    Monitors short-duration markets and enters in the final window.
    """

    def __init__(self, client, config: LateWindowConfig | None = None):
        self.client = client
        self.cfg    = config or LateWindowConfig()
        self._positions: dict[str, LateWindowPosition] = {}
        self._trigger_watchlist: dict[str, dict] = {}  # token_id -> market info

    def scan_for_entries(self, markets: list[dict]) -> list[dict]:
        """
        Find markets in the entry window and return signals.
        """
        signals = []
        now = time.time()

        for market in markets:
            end_str = market.get("endDate") or market.get("end_date_iso", "")
            close_ts = self._parse_close_time(end_str)
            if close_ts is None:
                continue

            seconds_to_close = close_ts - now
            if seconds_to_close <= 0:
                continue

            tokens   = market.get("tokens", [])
            question = market.get("question") or market.get("title", "")
            yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_token  = next((t for t in tokens if t.get("outcome") == "No"),  None)
            if not yes_token:
                continue

            yes_price = float(yes_token.get("price", 0.5))
            no_price  = 1.0 - yes_price
            yes_id = yes_token.get("token_id") or yes_token.get("tokenId", "")
            no_id  = (no_token.get("token_id") or no_token.get("tokenId", "")) if no_token else ""

            # SNIPE mode: in final window, price already at threshold
            if seconds_to_close <= self.cfg.entry_window_seconds:
                if yes_price >= self.cfg.entry_threshold_price and yes_id not in self._positions:
                    signals.append({
                        "token_id": yes_id,
                        "side": "YES",
                        "price": yes_price,
                        "close_ts": close_ts,
                        "seconds_to_close": seconds_to_close,
                        "title": question,
                        "mode": "snipe",
                    })
                elif no_price >= self.cfg.entry_threshold_price and no_id and no_id not in self._positions:
                    signals.append({
                        "token_id": no_id,
                        "side": "NO",
                        "price": no_price,
                        "close_ts": close_ts,
                        "seconds_to_close": seconds_to_close,
                        "title": question,
                        "mode": "snipe",
                    })

            # TRIGGER mode: price crossed threshold with 1-3 min remaining
            trigger_window = self.cfg.trigger_minutes_remaining * 60
            if seconds_to_close <= trigger_window and yes_price >= self.cfg.trigger_price:
                if yes_id not in self._positions and yes_id not in self._trigger_watchlist:
                    self._trigger_watchlist[yes_id] = {
                        "token_id": yes_id,
                        "side": "YES",
                        "price": yes_price,
                        "close_ts": close_ts,
                        "title": question,
                    }
                    logger.debug("Added to trigger watchlist: %s @ %.3f", question[:30], yes_price)

        return signals

    def check_trigger_watchlist(self) -> list[dict]:
        """
        For watchlisted tokens, check if price has risen to exit threshold.
        If so, enter now (price likely to resolve YES).
        """
        signals = []
        for token_id, info in list(self._trigger_watchlist.items()):
            try:
                current = self.client.get_midpoint(token_id)
                if current and current >= self.cfg.exit_price:
                    signals.append({
                        **info,
                        "price": current,
                        "mode": "trigger",
                    })
                    del self._trigger_watchlist[token_id]
            except Exception:
                pass
        return signals

    def execute(self, signal: dict) -> bool:
        if len(self._positions) >= self.cfg.max_open:
            return False
        token_id = signal["token_id"]
        try:
            resp = self.client.place_market_order(token_id, "BUY", self.cfg.trade_size_usdc)
            if resp:
                self._positions[token_id] = LateWindowPosition(
                    token_id=token_id,
                    market_title=signal["title"],
                    entry_price=signal["price"],
                    side=signal["side"],
                    close_time=signal["close_ts"],
                    amount_usdc=self.cfg.trade_size_usdc,
                    mode=signal["mode"],
                )
                logger.info(
                    "LateWindow [%s]: %s %s @ %.3f closes in %.0fs",
                    signal["mode"], signal["title"][:35], signal["side"],
                    signal["price"], signal.get("seconds_to_close", 0),
                )
                return True
        except Exception as e:
            logger.error("Late window order failed: %s", e)
        return False

    def expire_positions(self) -> None:
        """Remove positions past their close time."""
        now = time.time()
        for token_id, pos in list(self._positions.items()):
            if now > pos.close_time + 30:  # 30s grace period for settlement
                logger.info("Position expired: %s", pos.market_title[:35])
                del self._positions[token_id]

    @staticmethod
    def _parse_close_time(end_str: str) -> float | None:
        if not end_str:
            return None
        try:
            dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return None
