"""
Flash Crash / Volatility Mean Reversion Strategy.

Source: discountry/polymarket-trading-bot (347 stars)

Signal: Detects probability drops ≥ 0.30 absolute in a 10-second window
via WebSocket.  The thesis: sudden large moves are often market overreaction
(thin book, panic sell) and will mean-revert.

Parameters:
  - MIN_DROP: 0.30 absolute probability change to trigger
  - TAKE_PROFIT: +$0.10 per position
  - STOP_LOSS: -$0.05 per position
  - TRADE_SIZE_USDC: $5 per trade (keep small, high frequency)

WebSocket: Polymarket streams orderbook via wss://ws-subscriptions-clob.polymarket.com
We track mid-price (best_bid + best_ask) / 2 per token.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("trading")

_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
_WINDOW_SECONDS = 10
_MIN_DROP = 0.30
_TAKE_PROFIT_USDC = 0.10
_STOP_LOSS_USDC   = 0.05
_TRADE_SIZE_USDC  = 5.0


@dataclass
class PricePoint:
    timestamp: float
    mid: float


@dataclass
class FlashCrashSignal:
    token_id: str
    market_title: str
    crash_side: str       # 'yes' or 'no' — whichever crashed
    pre_crash_price: float
    crash_price: float
    drop_magnitude: float
    timestamp: float


@dataclass
class OpenPosition:
    token_id: str
    side: str
    entry_price: float
    amount_usdc: float
    entry_time: float
    order_id: str = ""


class FlashCrashMonitor:
    """
    Monitors Polymarket prices via HTTP polling (WebSocket optional upgrade).
    Fires signals when a flash crash is detected.
    """

    def __init__(self, client, poll_interval: float = 3.0,
                 min_drop: float = _MIN_DROP,
                 window_seconds: float = _WINDOW_SECONDS):
        self.client = client
        self.poll_interval = poll_interval
        self.min_drop = min_drop
        self.window_seconds = window_seconds
        # token_id -> deque of PricePoints
        self._price_history: dict[str, deque] = {}
        self._watched_tokens: dict[str, str] = {}   # token_id -> market_title
        self._lock = threading.Lock()
        self._signals: list[FlashCrashSignal] = []

    def watch_tokens(self, tokens: dict[str, str]) -> None:
        """tokens: {token_id -> market_title}"""
        with self._lock:
            self._watched_tokens.update(tokens)
            for tid in tokens:
                if tid not in self._price_history:
                    self._price_history[tid] = deque(maxlen=200)

    def poll_once(self) -> list[FlashCrashSignal]:
        """Fetch current prices and check for flash crashes."""
        new_signals: list[FlashCrashSignal] = []
        now = time.time()

        with self._lock:
            tokens = dict(self._watched_tokens)

        for token_id, title in tokens.items():
            try:
                mid = self.client.get_midpoint(token_id)
                if mid is None:
                    continue

                with self._lock:
                    history = self._price_history[token_id]
                    history.append(PricePoint(now, mid))

                    # Find the oldest price within the window
                    cutoff = now - self.window_seconds
                    window_prices = [p for p in history if p.timestamp >= cutoff]

                    if len(window_prices) < 2:
                        continue

                    oldest_mid = window_prices[0].mid
                    current_mid = window_prices[-1].mid
                    drop = oldest_mid - current_mid   # positive = price dropped

                    if drop >= self.min_drop:
                        sig = FlashCrashSignal(
                            token_id=token_id,
                            market_title=title,
                            crash_side="yes",
                            pre_crash_price=oldest_mid,
                            crash_price=current_mid,
                            drop_magnitude=drop,
                            timestamp=now,
                        )
                        new_signals.append(sig)
                        logger.info(
                            "FLASH CRASH: %s dropped %.3f → %.3f (Δ=%.3f)",
                            title[:40], oldest_mid, current_mid, drop,
                        )

            except Exception as e:
                logger.debug("Price poll error %s: %s", token_id[:12], e)

        return new_signals

    def run_loop(self, running_flag) -> None:
        logger.info("Flash crash monitor started — %d tokens watched", len(self._watched_tokens))
        while running_flag():
            self.poll_once()
            time.sleep(self.poll_interval)


class FlashCrashStrategy:
    """
    Executes trades on flash crash signals with TP/SL management.
    """

    def __init__(self, client, monitor: FlashCrashMonitor,
                 trade_size_usdc: float = _TRADE_SIZE_USDC,
                 take_profit_usdc: float = _TAKE_PROFIT_USDC,
                 stop_loss_usdc: float = _STOP_LOSS_USDC,
                 max_open: int = 5):
        self.client = client
        self.monitor = monitor
        self.trade_size = trade_size_usdc
        self.take_profit = take_profit_usdc
        self.stop_loss = stop_loss_usdc
        self.max_open = max_open
        self._positions: dict[str, OpenPosition] = {}

    def load_active_markets(self, limit: int = 50) -> None:
        """Auto-populate monitor with highest-volume active markets."""
        try:
            markets = self.client.get_markets(limit=limit, active=True)
            tokens = {}
            for m in markets:
                for t in m.get("tokens", []):
                    if t.get("outcome") == "Yes":
                        tid = t.get("token_id") or t.get("tokenId", "")
                        if tid:
                            tokens[tid] = m.get("question") or m.get("title", "")
            self.monitor.watch_tokens(tokens)
            logger.info("Loaded %d tokens for flash crash monitoring", len(tokens))
        except Exception as e:
            logger.error("Failed to load markets: %s", e)

    def run_cycle(self) -> list[str]:
        """Check for signals and manage positions. Returns order IDs of new trades."""
        new_orders: list[str] = []

        # Check for new signals
        signals = self.monitor.poll_once()
        for sig in signals:
            if sig.token_id in self._positions:
                continue
            if len(self._positions) >= self.max_open:
                logger.debug("Max open positions reached — skipping flash crash")
                continue
            # Buy the crashed side (expecting mean reversion)
            order_id = self._enter(sig)
            if order_id:
                new_orders.append(order_id)

        # Manage existing positions
        self._manage_exits()
        return new_orders

    def _enter(self, sig: FlashCrashSignal) -> str:
        try:
            resp = self.client.place_market_order(sig.token_id, "BUY", self.trade_size)
            order_id = resp.get("orderID") or resp.get("id") or ""
            pos = OpenPosition(
                token_id=sig.token_id,
                side="yes",
                entry_price=sig.crash_price,
                amount_usdc=self.trade_size,
                entry_time=time.time(),
                order_id=order_id,
            )
            self._positions[sig.token_id] = pos
            logger.info("Flash crash entry: %s @ %.3f size=$%.2f",
                        sig.market_title[:40], sig.crash_price, self.trade_size)
            return order_id
        except Exception as e:
            logger.error("Flash crash entry failed: %s", e)
            return ""

    def _manage_exits(self) -> None:
        for token_id, pos in list(self._positions.items()):
            try:
                current = self.client.get_midpoint(token_id)
                if current is None:
                    continue
                pnl = (current - pos.entry_price) * (self.trade_size / max(pos.entry_price, 0.01))
                should_exit = pnl >= self.take_profit or pnl <= -self.stop_loss
                if should_exit:
                    reason = "take_profit" if pnl >= self.take_profit else "stop_loss"
                    self.client.place_market_order(token_id, "SELL", pos.amount_usdc)
                    logger.info("Exit (%s): %s pnl=$%.4f", reason, token_id[:12], pnl)
                    del self._positions[token_id]
            except Exception as e:
                logger.debug("Exit check error %s: %s", token_id[:12], e)
