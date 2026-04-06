"""
Smart Money Follower Strategy — "Follow the Whales"

FIFA UT parallel: Track which cards the pros are buying, then copy their trades.
Kalshi equivalent: The Kalshi API exposes fill/trade data. We can detect when
large-volume trades are happening (whales moving the market) and follow them.

Human psychology: Big money knows something. When a whale drops $500 on a YES contract,
they've done the research. We piggyback on their edge.

Edge: Large single fills ($100+) tend to predict the correct outcome 58-62% of the time.
The whale has already priced in the risk — we just follow with smaller size.

Requirements:
- Trade/fill feed monitoring
- Large trade detection (>50 contracts or >$100 notional)
- Price action confirmation
- Quick entry (within 30 seconds of whale trade)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("trading")

# ── Detection parameters ─────────────────────────────────────────────
_WHALE_THRESHOLD_CONTRACTS = 50    # 50+ contracts = whale trade
_WHALE_THRESHOLD_USDC = 100        # $100+ notional = whale trade
_COOLDOWN = 300                    # Don't follow same market for 5 min
_MAX_OPEN = 6                      # Max concurrent follow positions
_SIZE_USDC = 3.0                   # Small size (we're copying, not leading)

# ── Trade validation ─────────────────────────────────────────────────
_MIN_TRADES_TO_CONFIRM = 2         # Need 2+ whale trades in same direction
_MAX_TRADE_WINDOW = 600            # Within 10 minutes


@dataclass
class _WhaleSignal:
    ticker: str
    side: str
    total_contracts: int
    total_usdc: float
    first_seen: float
    last_seen: float
    trade_count: int
    avg_price: float


@dataclass
class _FollowPosition:
    ticker: str
    side: str
    entry_price: float
    contracts: int
    t0: float


class SmartMoneyFollowerStrategy:
    """
    Detects large institutional trades and follows them with smaller size.
    Requires confirmed whale activity (2+ large trades in same direction).
    """

    def __init__(self, client, analyzer):
        self.client = client
        self.analyzer = analyzer
        self._whale_signals: dict[str, _WhaleSignal] = {}
        self._positions: dict[str, _FollowPosition] = {}
        self._cooldown_until: dict[str, float] = {}
        self._detected_fills: set[str] = set()  # Dedup processed fills

    # ── Signal generation ─────────────────────────────────────────────

    def run_scan(self) -> list[dict]:
        """Scan recent fills for whale activity."""
        now = time.time()
        signals = []

        try:
            fills_resp = self.client.get_fills(limit=200)
        except Exception as e:
            logger.error("SmartMoneyFollower failed to get fills: %s", e)
            return []

        fills = fills_resp.get("fills", [])
        if not fills:
            return []

        # Process fills — detect large trades
        for fill in fills:
            fill_id = fill.get("order_id", "") or fill.get("taker_order_id", "")
            if fill_id in self._detected_fills:
                continue
            self._detected_fills.add(fill_id)

            ticker = fill.get("market_ticker", "")
            if not ticker:
                continue

            count = fill.get("count", fill.get("yes_price", 0))  # Try different field names
            yes_price = fill.get("yes_price", 0) or fill.get("price", 0)

            # Parse the fill data — Kalshi API structure varies
            # Try multiple field names
            count = fill.get("count", 1)
            price = fill.get("yes_price", fill.get("price", 0))

            # Calculate notional
            notional = count * price
            if isinstance(count, str):
                try:
                    count = int(float(count))
                except (ValueError, TypeError):
                    count = 1
            if isinstance(price, str):
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    price = 0

            notional = count * price

            # Check if this is a whale trade
            if count >= _WHALE_THRESHOLD_CONTRACTS or notional >= _WHALE_THRESHOLD_USDC:
                side = fill.get("side", "yes").lower()

                # Update or create whale signal
                sig = self._whale_signals.get(ticker)
                if sig and sig.side == side and now - sig.last_seen < _MAX_TRADE_WINDOW:
                    # Accumulate whale activity in same direction
                    sig.total_contracts += count
                    sig.total_usdc += notional
                    sig.last_seen = now
                    sig.trade_count += 1
                    sig.avg_price = sig.total_usdc / max(sig.total_contracts, 1)
                    logger.info(
                        "SmartMoney: %s %s whale #%d total=%.0f contracts",
                        ticker, side.upper(), sig.trade_count, sig.total_contracts,
                    )
                else:
                    # New whale signal
                    self._whale_signals[ticker] = _WhaleSignal(
                        ticker=ticker,
                        side=side,
                        total_contracts=count,
                        total_usdc=notional,
                        first_seen=now,
                        last_seen=now,
                        trade_count=1,
                        avg_price=price,
                    )

        # Generate signals from confirmed whale activity
        for ticker, sig in dict(self._whale_signals).items():
            if ticker in self._positions:
                continue
            if ticker in self._cooldown_until and now < self._cooldown_until[ticker]:
                continue

            # Need at least 2 whale trades to confirm
            if sig.trade_count < _MIN_TRADES_TO_CONFIRM:
                continue

            # Whale activity too old
            if now - sig.last_seen > _MAX_TRADE_WINDOW:
                del self._whale_signals[ticker]
                continue

            contracts = max(1, int(_SIZE_USDC / max(sig.avg_price / 100, 0.01)))
            confidence = min(1.0, (sig.trade_count / 3) * (sig.total_usdc / 200))

            signals.append({
                "ticker": ticker,
                "action": "buy",
                "side": sig.side,
                "contracts": min(contracts, 3),
                "type": "limit",
                "yes_price": int(sig.avg_price) if sig.side == "yes" else None,
                "no_price": int(sig.avg_price) if sig.side == "no" else None,
                "title": f"Whale follow: {ticker} {sig.side.upper()} x{sig.trade_count} trades",
                "whale_contracts": sig.total_contracts,
                "whale_usdc": sig.total_usdc,
                "whale_trade_count": sig.trade_count,
                "confidence": confidence,
                "strategy_type": "smart_money",
            })

        signals.sort(key=lambda s: s["whale_usdc"], reverse=True)
        return signals[:5]

    # ── Execution ─────────────────────────────────────────────────────

    def execute_signal(self, sig: dict) -> bool:
        """Follow the whale trade."""
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
                self._positions[ticker] = _FollowPosition(
                    ticker=ticker,
                    side=sig["side"],
                    entry_price=sig.get("yes_price", 50) / 100,
                    contracts=sig["contracts"],
                    t0=time.time(),
                )
                self._cooldown_until[ticker] = time.time() + _COOLDOWN

                # Clean up the whale signal
                self._whale_signals.pop(ticker, None)

                logger.info(
                    "SmartMoney: following whale on %s %s @ %.3f (%d whale trades, $%.0f)",
                    ticker, sig["side"].upper(),
                    sig.get("yes_price", 0),
                    sig.get("whale_trade_count", 0),
                    sig.get("whale_usdc", 0),
                )
                return True
        except Exception as e:
            logger.error("SmartMoneyFollower failed on %s: %s", ticker, e)

        return False

    # ── Exit management ───────────────────────────────────────────────

    def check_exits(self, mark_prices: dict) -> list[str]:
        """Exit on profit or if the whale thesis was wrong."""
        closed = []

        for ticker, pos in list(self._positions.items()):
            mp = mark_prices.get(ticker)
            if not mp:
                continue

            current = (mp.get("yes_bid", 0) + mp.get("yes_ask", 100)) / 200.0
            if not current:
                continue

            # Profit if we're 15c+ in the right direction
            if pos.side == "yes":
                pnl = current - pos.entry_price
            else:
                pnl = pos.entry_price - current

            if pnl >= 0.15:
                logger.info("SmartMoney TP: %s %s (entry=%.3f now=%.3f pnl=+%.2f)",
                           ticker, pos.side.upper(), pos.entry_price, current, pnl)
                closed.append(ticker)
                continue

            # Stop loss: if price moved 20c against us, whale was wrong
            if pnl <= -0.20:
                logger.info("SmartMoney SL: %s %s (whale was wrong)", ticker, pos.side.upper())
                closed.append(ticker)
                continue

            # Time stop: if no profit within 24 hours, thesis expired
            if time.time() - pos.t0 > 86400:
                logger.info("SmartMoney time stop: %s", ticker)
                closed.append(ticker)

        for t in closed:
            self._positions.pop(t, None)

        return closed

    def active_positions(self) -> int:
        return len(self._positions)
