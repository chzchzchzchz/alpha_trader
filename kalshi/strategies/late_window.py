"""
Late-Window Snipe - Kalshi native.

Thesis: in the final 1-2 minutes of a binary market, the apparent winner
is almost certain to win. Buy YES at 93 cents, resolves to $1.00.
Edge: 7.5% ROI in 90 seconds. High frequency = meaningful returns.

Kalshi advantage: many 5min/1hr/same-day markets (FOMC, CPI, sports).
Resolution handled by Kalshi itself. Settlement delay ~30-60s.

Entry: <= 90 seconds to close, YES bid >= 93 cents
Risk: upset in final seconds. Size small ($10 max per position).

TRIGGER mode (AstroTick pattern): price breaches 70 cents within 3 min
of close -> enter at 90 cents.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")

_ENTRY_WINDOW = 90.0       # seconds
_ENTRY_THRESHOLD = 0.93    # YES bid >= this
_NO_THRESHOLD = 0.07       # YES ask <= this (= NO >= 93c)
_TRADE_SIZE = 10.0         # $10 max
_MAX_OPEN = 3
_TRIGGER_PRICE = 0.70      # monitor mode starts here
_TRIGGER_WINDOW = 180.0   # 3 minutes before close
_EXIT_PRICE = 0.90


@dataclass
class LWPosition:
    ticker: str
    title: str
    entry_price: float
    side: str
    close_ts: float
    amount: float
    mode: str  # 'snipe' or 'trigger'


class LateWindowStrategy:
    """
    Scans for markets in the final entry window and snipes near-certain outcomes.
    """

    def __init__(self, client):
        self.client = client
        self._positions: dict[str, LWPosition] = {}
        self._trigger_watchlist: dict[str, dict] = {}

    def generate_signals(self, markets: list) -> list[dict]:
        """Find late-window opportunities."""
        signals = []
        now = time.time()

        for mkt in markets:
            close_ts = _parse_close(mkt.get('close_time', mkt.get('end_date_iso', '')))
            if close_ts is None:
                continue

            remaining = close_ts - now
            if remaining <= 0:
                continue

            ticker = mkt['ticker']
            if ticker in self._positions:
                continue

            yes_bid = mkt.get('yes_bid', 0)
            yes_ask = mkt.get('yes_ask', 100)
            yes_p = yes_bid / 100.0
            no_p = 1.0 - yes_ask / 100.0

            # --- SNIPE mode ---
            if remaining <= _ENTRY_WINDOW:
                if yes_p >= _ENTRY_THRESHOLD:
                    signals.append({
                        "ticker": ticker, "action": "buy", "side": "yes",
                        "yes_price": yes_bid,
                        "contracts": max(1, int(_TRADE_SIZE / max(yes_p, 0.01))),
                        "title": mkt.get('subtitle', mkt.get('event_ticker', ticker)),
                        "mode": "snipe",
                        "score": yes_p,
                        "remaining": remaining,
                    })
                elif no_p >= _ENTRY_THRESHOLD:
                    signals.append({
                        "ticker": ticker, "action": "buy", "side": "no",
                        "yes_price": yes_ask,
                        "contracts": max(1, int(_TRADE_SIZE / max(no_p, 0.01))),
                        "title": mkt.get('subtitle', mkt.get('event_ticker', ticker)),
                        "mode": "snipe",
                        "score": no_p,
                        "remaining": remaining,
                    })

            # --- TRIGGER mode: price crossed threshold, add to watchlist ---
            if remaining <= _TRIGGER_WINDOW and yes_p >= _TRIGGER_PRICE:
                if ticker not in self._trigger_watchlist:
                    self._trigger_watchlist[ticker] = {
                        "ticker": ticker,
                        "title": mkt.get('subtitle', mkt.get('event_ticker', ticker)),
                        "close_ts": close_ts,
                        "remaining": remaining,
                    }

        # Check trigger watchlist
        for ticker in list(self._trigger_watchlist):
            if ticker in self._positions:
                del self._trigger_watchlist[ticker]
                continue
            info = self._trigger_watchlist[ticker]
            remaining = info['close_ts'] - now
            if remaining <= _ENTRY_WINDOW:
                # In final window, check if price is still high
                for mkt in markets:
                    if mkt['ticker'] == ticker:
                        yes_p = mkt.get('yes_bid', 0) / 100.0
                        if yes_p >= _EXIT_PRICE:
                            signals.append({
                                "ticker": ticker, "action": "buy", "side": "yes",
                                "yes_price": mkt.get('yes_bid', 90),
                                "contracts": max(1, int(_TRADE_SIZE)),
                                "title": info['title'],
                                "mode": "trigger",
                                "score": yes_p,
                                "remaining": remaining,
                            })
                        del self._trigger_watchlist[ticker]
                        break

        signals.sort(key=lambda s: s['score'], reverse=True)
        return signals

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Remove expired positions."""
        now = time.time()
        closed = []
        grace = 120  # settlement grace

        for ticker, pos in list(self._positions.items()):
            if now > pos.close_ts + grace:
                logger.info("LateWindow expired: %s %s entry=%.2f", 
                            ticker, pos.mode, pos.entry_price)
                closed.append(ticker)
                del self._positions[ticker]

        return closed

    def record_fill(self, signal: dict, order_id: str) -> None:
        ticker = signal['ticker']
        self._positions[ticker] = LWPosition(
            ticker=ticker, title=signal.get('title', ''),
            entry_price=signal.get('yes_price', 93) / 100.0,
            side=signal['side'], close_ts=signal.get('remaining', 0) + time.time(),
            amount=_TRADE_SIZE, mode=signal.get('mode', 'snipe'),
        )

    def active_positions(self) -> int:
        return len(self._positions)

def _parse_close(s: str) -> float | None:
    if not s: return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.timestamp()
    except: return None
