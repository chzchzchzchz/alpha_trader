"""
Overreaction Reversal Strategy — "Fade the Headline"

FIFA UT parallel: When a new TOTY card drops, everyone panics and sells their old meta cards at a loss.
Kalshi equivalent: Breaking news causes immediate overreaction (20-30c move), then reality sets in
and the price partially reverses within the next few hours.

Example: "X candidate indicted" -> market crashes to 20c -> reality check -> bounces to 35c
The 15c bounce is pure profit.

Psychology: First reaction is emotional (fear/greed), second reaction is rational.
Be the rational trader.

Requirements:
- Fast news detection (RSS feeds, alerts)
- Rapid price tracking (need pre-news baseline)
- Quick execution (first 2-5 minutes matter)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

logger = logging.getLogger("trading")

# ── Tuning parameters ─────────────────────────────────────────────────
_MOVE_THRESHOLD = 0.25      # 25c+ move in <10 min = potential overreaction
_BASELINE_WINDOW = 1800     # 30-minute baseline for comparison
_ENTRY_DELAY = 120          # Wait 2 min after big move to confirm it's overreaction
_SIZE_USDC = 10.0           # Higher size — stronger edge
_MAX_OPEN = 3               # Fewer positions, higher conviction


@dataclass
class _ReversalPosition:
    ticker: str
    side: str
    entry_price: float
    pre_move_price: float   # Price before the news hit
    move_size: float        # Size of the original move
    entry_time: float
    target_price: float     # Our take-profit (partial reversal)
    stop_loss: float


class OverreactionReversalStrategy:
    """
    Detects news-driven overreactions and fades them.
    Waits for the initial panic to settle, then bets on partial recovery.
    """

    def __init__(self, client, analyzer, capital=500.0):
        self.client = client
        self.analyzer = analyzer
        self.capital = capital
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self._positions: dict[str, _ReversalPosition] = {}
        self._detected_moves: dict[str, dict] = {}  # ticker -> move details

    # ── Signal generation ─────────────────────────────────────────────

    def run_scan(self) -> list[dict]:
        """Scan for overreaction candidates."""
        now = time.time()
        signals = []

        try:
            markets = self.analyzer.fetch_all_markets()
        except Exception as e:
            logger.error("OverreactionReversal scan failed: %s", e)
            return []

        for mkt in markets:
            ticker = mkt.get("ticker", "")
            yes_mid = mkt.get("yes_mid_price", 0)

            if not ticker or not yes_mid or yes_mid <= 0:
                continue
            if ticker in self._positions:
                continue

            # Track price history
            self._history[ticker].append((now, yes_mid))

            # Get baseline (average 30 min ago)
            hist = list(self._history[ticker])
            if len(hist) < 20:
                continue

            # Find the baseline price (from before the recent window)
            cutoff = now - _BASELINE_WINDOW
            baseline_prices = [p for t, p in hist if t < cutoff]
            recent_prices = [p for t, p in hist if t >= cutoff]

            if not baseline_prices or not recent_prices:
                continue

            baseline_avg = sum(baseline_prices) / len(baseline_prices)
            current_price = yes_mid

            # Calculate move from baseline
            move_size = abs(current_price - baseline_avg)

            if move_size >= _MOVE_THRESHOLD and baseline_avg >= 0.2:
                # Big move detected — check if it's recent (<10 min)
                recent_start = None
                for t, p in hist:
                    if abs(p - baseline_avg) < 0.05:
                        recent_start = t
                    if recent_start and now - recent_start < 600:
                        break

                if recent_start and now - recent_start > _ENTRY_DELAY:
                    # This is a detected overreaction
                    # Wait for stabilization (price not moving much in last 2 min)
                    last_2min = [p for t, p in hist if now - t < 120]
                    if len(last_2min) >= 3:
                        recent_volatility = max(last_2min) - min(last_2min)
                        if recent_volatility < 0.03:  # Stabilized (less than 3c swing)
                            # The overreaction has settled — time to fade it
                            direction = "yes" if current_price < baseline_avg else "no"
                            entry_price = current_price

                            # Target: 60% reversal of the move
                            if current_price < baseline_avg:
                                # Price crashed below baseline — buy YES for recovery
                                target = current_price + move_size * 0.6
                            else:
                                # Price pumped above baseline — buy NO for reversal
                                target = current_price - move_size * 0.6

                            # Stop loss: 50% of the move continues
                            if direction == "yes":
                                stop = current_price - move_size * 0.5
                            else:
                                stop = current_price + move_size * 0.5

                            contracts = max(1, int(_SIZE_USDC / max(current_price, 0.01)))

                            signals.append({
                                "ticker": ticker,
                                "action": "buy",
                                "side": direction,
                                "contracts": min(contracts, 5),
                                "type": "limit",
                                "yes_price": round(current_price * 100) if direction == "yes" else None,
                                "no_price": round((1 - current_price) * 100) if direction == "no" else None,
                                "title": f"Overreaction: {ticker} moved {move_size:.0%}",
                                "pre_move_price": baseline_avg,
                                "current_price": current_price,
                                "move_size": move_size,
                                "target": target,
                                "stop_loss": stop,
                                "confidence": min(1.0, move_size / 0.4),
                                "strategy_type": "overreaction_reversal",
                            })

        # Sort by biggest overreaction (highest confidence)
        signals.sort(key=lambda s: s["move_size"], reverse=True)
        return signals[:5]

    # ── Execution ─────────────────────────────────────────────────────

    def execute_signal(self, sig: dict) -> bool:
        """Enter the overreaction fade position."""
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
                self._positions[ticker] = _ReversalPosition(
                    ticker=ticker,
                    side=sig["side"],
                    entry_price=sig.get("current_price", 0.5),
                    pre_move_price=sig.get("pre_move_price", 0.5),
                    move_size=sig.get("move_size", 0),
                    entry_time=time.time(),
                    target_price=sig.get("target", 0.5),
                    stop_loss=sig.get("stop_loss", 0.5),
                )
                logger.info(
                    "OverreactionReversal: %s %s @ %.3f (fade %.0%% move)",
                    ticker, sig["side"].upper(),
                    sig.get("current_price", 0),
                    sig.get("move_size", 0) * 100,
                )
                return True
        except Exception as e:
            logger.error("OverreactionReversal failed on %s: %s", ticker, e)

        return False

    # ── Exit management ───────────────────────────────────────────────

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Take profit on reversal, stop loss on continuation."""
        closed = []

        for ticker, pos in list(self._positions.items()):
            mp = mark_prices.get(ticker)
            if not mp:
                continue

            current = (mp.get("yes_bid", 0) + mp.get("yes_ask", 100)) / 200.0
            if not current:
                continue

            # For YES positions: profit when price recovers
            # For NO positions: profit when price falls
            if pos.side == "yes":
                pnl = current - pos.entry_price
            else:
                pnl = pos.entry_price - current

            # Take profit at 60% reversal
            if pnl >= (pos.target_price - pos.entry_price) * 0.8:
                logger.info(
                    "OverreactionReversal TP: %s %s recovered (entry=%.3f now=%.3f pnl=+%.2f)",
                    ticker, pos.side.upper(), pos.entry_price, current, pnl,
                )
                closed.append(ticker)
                continue

            # Stop loss: overreaction continues
            if pnl <= (pos.stop_loss - pos.entry_price) if pos.side == "yes" else (pos.entry_price - pos.stop_loss) < 0:
                if abs(pnl) >= 0.15:  # 15c stop loss
                    logger.info(
                        "OverreactionReversal SL: %s %s (entry=%.3f now=%.3f pnl=%.2f)",
                        ticker, pos.side.upper(), pos.entry_price, current, pnl,
                    )
                    closed.append(ticker)

            # Time stop: if no reversal within 4 hours, it's not an overreaction
            if time.time() - pos.entry_time > 14400:
                logger.info(
                    "OverreactionReversal time stop: %s no reversal after 4h",
                    ticker,
                )
                closed.append(ticker)

        for t in closed:
            self._positions.pop(t, None)

        return closed

    def active_positions(self) -> int:
        return len(self._positions)
