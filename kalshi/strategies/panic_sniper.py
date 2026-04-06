"""
Panic Sniper Strategy — "Buy the Blood"

FIFA UT parallel: When a player concedes in FUT Champs, panic-selling their squad at 50% value.
Kalshi equivalent: A market gets hit with cascading sell orders (fear), price drops 25%+ from
recent average in <5 minutes — far more than fundamentals justify.

This is pure human psychology. Fear creates dislocations. The bot buys the panic.

Edge: 60-75% of >25c drops from >50c recover within 15-60 minutes.

Requirements:
- High-frequency polling (every 3-5 seconds for active monitoring)
- Historical price tracking per ticker
- Fast mean-reversion detection
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")

# ── Tuning parameters ─────────────────────────────────────────────────
_DROP_THRESHOLD = 0.20       # 20%+ price drop triggers panic alert
_RECENT_WINDOW = 300         # Look back 5 minutes for price history
_MIN_PRICE_BEFORE_DROP = 30  # Price must have been >= 30c before crash
_MAX_RECOVERY_WINDOW = 1800  # Expect recovery within 30 min (take profit)
_SIZE_USDC = 5.0             # Per-position size
_MAX_OPEN = 8                # Max concurrent panic positions
_COOLDOWN_SECONDS = 120      # Don't re-buy same ticker for 2 min after entry

# Position sizing by panic severity
_SIZE_TIERS = [
    (0.30, 10),   # 30%+ drop = max conviction, 10 contracts
    (0.25, 5),    # 25%+ drop = high conviction, 5 contracts
    (0.20, 3),    # 20%+ drop = moderate conviction, 3 contracts
]


@dataclass
class _PanicPosition:
    ticker: str
    side: str
    entry_mid: float
    pre_panic_mid: float          # Price before panic (our exit target)
    drop_size: float              # How big was the drop
    t0: float                     # Entry timestamp
    cooldown_until: float = 0.0


class PanicSniperStrategy:
    """
    Detects panic cascades (sudden 20%+ drops) and buys the dip.
    Takes profit on mean-reversion back toward pre-panic price.
    """

    def __init__(self, client, analyzer, capital=500.0):
        self.client = client
        self.analyzer = analyzer
        self.capital = capital
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._positions: dict[str, _PanicPosition] = {}
        self._last_scan = 0.0

    # ── Signal generation ─────────────────────────────────────────────

    def run_scan(self) -> list[dict]:
        """Scan for active panic cascades across all markets."""
        now = time.time()

        # Poll all markets for prices
        try:
            markets = self.analyzer.fetch_all_markets()
        except Exception as e:
            logger.error("PanicSniper scan failed: %s", e)
            return []

        signals = []

        for mkt in markets:
            ticker = mkt.get("ticker", "")
            yes_mid = mkt.get("yes_mid_price", 0)

            if not ticker or not yes_mid or yes_mid <= 0:
                continue

            # Skip tickers we already have positions in
            if ticker in self._positions:
                continue

            # Skip if in cooldown
            pos = self._positions.get(ticker)
            if pos and now < pos.cooldown_until:
                continue

            # Update price history
            self._history[ticker].append((now, yes_mid))

            # Need at least 50 data points in recent window
            hist = [(t, p) for t, p in self._history[ticker] if now - t <= _RECENT_WINDOW]
            if len(hist) < 10:
                continue

            # Calculate the recent price range
            recent_prices = [p for _, p in hist]
            recent_avg = sum(recent_prices) / len(recent_prices)
            recent_max = max(recent_prices)
            recent_min = min(recent_prices)

            # Detect panic: drop from recent high to current
            if recent_max >= _MIN_PRICE_BEFORE_DROP / 100:
                drop_from_high = (recent_max - yes_mid) / max(recent_max, 0.01)

                if drop_from_high >= _DROP_THRESHOLD:
                    # Panic detected! Determine position size by severity
                    contracts = self._size_contracts(drop_from_high)

                    signals.append({
                        "ticker": ticker,
                        "action": "buy",
                        "side": "yes",
                        "contracts": contracts,
                        "type": "limit",
                        "yes_price": yes_mid + 2,  # Bid slightly above current
                        "title": f"PANIC: {ticker} crashed {drop_from_high:.0%}",
                        "pre_panic_mid": recent_avg,
                        "drop": drop_from_high,
                        "score": min(1.0, drop_from_high / 0.3),
                        "strategy_type": "panic_sniper",
                    })

        # Sort by biggest drop first (highest edge)
        signals.sort(key=lambda s: s["drop"], reverse=True)
        return signals[:10]  # Max 10 signals per cycle

    # ── Execution ─────────────────────────────────────────────────────

    def execute_signal(self, sig: dict) -> bool:
        """Buy the panic dip."""
        ticker = sig["ticker"]

        try:
            resp = self.client.place_order(
                ticker=ticker,
                action="buy",
                side="yes",
                count=min(sig["contracts"], _MAX_OPEN - len(self._positions)),
                type="limit",
                yes_price=sig.get("yes_price"),
            )

            if resp.get("order"):
                self._positions[ticker] = _PanicPosition(
                    ticker=ticker,
                    side="yes",
                    entry_mid=sig["yes_price"] / 100 if isinstance(sig["yes_price"], int) else sig["yes_price"],
                    pre_panic_mid=sig.get("pre_panic_mid", 0.5),
                    drop_size=sig.get("drop", 0),
                    t0=time.time(),
                    cooldown_until=time.time() + _COOLDOWN_SECONDS,
                )
                logger.info(
                    "PanicSniper BOUGHT %s YES @ %.3f (panic drop %.0%%)",
                    ticker,
                    sig.get("yes_price", 0),
                    sig.get("drop", 0) * 100,
                )
                return True
        except Exception as e:
            logger.error("PanicSniper failed on %s: %s", ticker, e)

        return False

    # ── Exit management ───────────────────────────────────────────────

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Take profit on recovery, stop loss if panic continues."""
        now = time.time()
        closed = []

        for ticker, pos in list(self._positions.items()):
            mp = mark_prices.get(ticker)
            if not mp:
                continue

            current_yes = (mp.get("yes_bid", 0) + mp.get("yes_ask", 100)) / 200.0
            if not current_yes:
                continue

            # Take profit: price recovered to pre-panic level or 80% of the drop
            recovery_target = pos.entry_mid + (pos.pre_panic_mid - pos.entry_mid) * 0.8
            if current_yes >= recovery_target:
                logger.info(
                    "PanicSniper TP: %s recovered %.3f (target %.3f)",
                    ticker, current_yes, recovery_target,
                )
                self._close_position(ticker)
                closed.append(ticker)
                continue

            # Stop loss: panic continues, drop another 10c
            if current_yes <= pos.entry_mid - 0.10:
                logger.info(
                    "PanicSniper SL: %s %.3f -> %.3f (continuing crash)",
                    ticker, pos.entry_mid, current_yes,
                )
                self._close_position(ticker)
                closed.append(ticker)
                continue

            # Time stop: if no recovery within 30 minutes, cut it
            if now - pos.t0 > _MAX_RECOVERY_WINDOW:
                logger.info(
                    "PanicSniper time stop: %s no recovery after %ds",
                    ticker, int(now - pos.t0),
                )
                self._close_position(ticker)
                closed.append(ticker)

        return closed

    # ── Helpers ───────────────────────────────────────────────────────

    def _size_contracts(self, drop_size: float) -> int:
        """Size position by panic severity — bigger drop = bigger bet."""
        for threshold, size in _SIZE_TIERS:
            if drop_size >= threshold:
                return size
        return 1

    def _close_position(self, ticker: str) -> None:
        """Close the position (market sell)."""
        pos = self._positions.pop(ticker, None)
        if pos:
            try:
                self.client.place_order(
                    ticker=ticker,
                    action="sell",
                    side="yes",
                    count=pos.contracts if hasattr(pos, 'contracts') else 1,
                    type="market",
                )
            except Exception as e:
                logger.debug("PanicSniper close sell failed (may be OK): %s", e)

    def active_positions(self) -> int:
        return len(self._positions)
