"""
Flash Crash / Volatility Mean Reversion - Kalshi native.

Thesis: sudden large moves are thin-book overreaction and will revert.
Detect drops via HTTP polling (no WebSocket needed on Kalshi - 3s polling is fine).

Entry: price drops >= 30 cents in 10-second window
Exit: take profit +10c, stop loss -5c per position
Size: $5 per trade, max 5 open
Target: Kalshi binary markets with >= 50 volume, <= 30 days to close
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("trading")

_WINDOW_SECONDS = 10
_MIN_DROP = 0.30      # 30 cent absolute drop
_MAX_DROP = 0.80      # ignore > 80c (likely real event)
_TAKE_PROFIT = 0.10   # +10 cents per position
_STOP_LOSS = 0.05     # -5 cents
_SIZE_USDC = 5.0
_MAX_OPEN = 5


@dataclass
class PricePoint:
    ts: float
    mid: float  # 0-1 yes price midpoint


@dataclass
class Position:
    ticker: str
    side: str       # 'yes' or 'no'
    entry_price: float
    entry_mid: float
    contracts: int
    t0: float


class FlashCrashStrategy:
    """
    Monitors Kalshi markets via HTTP polling. Fires when a flash crash
    is detected. Buys the crashed side expecting mean reversion.
    """

    def __init__(self, client):
        self.client = client
        # ticker -> deque of PricePoint
        self._history: dict[str, deque] = {}
        self._positions: dict[str, Position] = {}

    # ---- Scan ----

    def generate_signals(self, markets) -> list[dict]:
        """Scan all markets for new crash signals."""
        signals = []
        now = time.time()

        for mkt in markets:
            ticker = mkt['ticker']
            yes_bid = mkt.get('yes_bid', 0)
            yes_ask = mkt.get('yes_ask', 100)
            mid = (yes_bid + yes_ask) / 200.0  # 0-1 float

            if ticker not in self._history:
                self._history[ticker] = deque(maxlen=120)
            self._history[ticker].append(PricePoint(now, mid))

            if ticker in self._positions:
                continue
            if len(self._positions) >= _MAX_OPEN:
                continue

            # Check for crash in window
            hist = self._history[ticker]
            cutoff = now - _WINDOW_SECONDS
            window = [p for p in hist if p.ts >= cutoff]

            if len(window) < 2:
                continue

            oldest = window[0].mid
            drop = oldest - mid

            if _MIN_DROP <= drop <= _MAX_DROP:
                signals.append({
                    "ticker": ticker,
                    "action": "buy",
                    "side": "yes",  # buy yes side (crashed, expecting bounce)
                    "contracts": max(1, int(_SIZE_USDC / max(mid, 0.01))),
                    "yes_price": yes_bid,
                    "title": mkt.get('subtitle', mkt.get('event_ticker', ticker)),
                    "pre_drop": oldest,
                    "drop": drop,
                    "score": min(1.0, drop),  # bigger drop = higher score
                })

        return signals

    # ---- Exit management ----

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Check open positions for TP/SL."""
        now = time.time()
        closed = []

        for ticker, pos in list(self._positions.items()):
            mp = mark_prices.get(ticker)
            if not mp:
                continue

            current_yes = (mp.get('yes_bid', 0) + mp.get('yes_ask', 100)) / 200.0
            pnl = current_yes - pos.entry_mid if pos.side == 'yes' else pos.entry_mid - current_yes

            if pnl >= _TAKE_PROFIT:
                logger.info("Flash TP: %s %s entry=%.3f now=%.3f pnl=+%.2f",
                            ticker, pos.side.upper(), pos.entry_mid, current_yes, pnl)
                closed.append(ticker)
            elif pnl <= -_STOP_LOSS:
                logger.info("Flash SL: %s %s entry=%.3f now=%.3f pnl=%.2f",
                            ticker, pos.side.upper(), pos.entry_mid, current_yes, pnl)
                closed.append(ticker)

        # Remove closed
        for t in closed:
            if t in self._positions:
                del self._positions[t]

        return closed

    def record_fill(self, signal: dict, order_id: str) -> None:
        """Record a new filled position."""
        ticker = signal['ticker']
        mid = signal.get('pre_drop', 0.5)
        self._positions[ticker] = Position(
            ticker=ticker,
            side=signal['side'],
            entry_price=signal.get('yes_price', 50) / 100.0,
            entry_mid=mid,
            contracts=signal['contracts'],
            t0=time.time(),
        )

    def active_positions(self) -> int:
        return len(self._positions)

