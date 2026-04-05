"""
Polymarket Copy Trader.

Watches a basket of profitable wallets via the Data API and mirrors
their trades with configurable sizing and risk controls.

Architecture (from research):
  1. Poll Data API for new wallet activity every N seconds
  2. Skip SELL orders on first pass (avoid chasing exits)
  3. Size via fractional Kelly or fixed USDC multiplier
  4. Apply per-wallet and per-market caps
  5. Execute via CLOB API (market orders for speed)

Key insight from research:
  - Basket of 5-10 specialists outperforms following one whale
  - Detect trades within 5-10 seconds via polling
  - Take profits at 80-90% (don't hold to resolution like smart money does)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.kelly_sizer import KellySizer
from core.metrics import metrics

logger = logging.getLogger("trading")


@dataclass
class CopyTraderConfig:
    # Sizing
    usdc_per_trade: float = 10.0          # base USDC per copied trade
    kelly_fraction: float = 0.25          # fractional Kelly multiplier
    max_trade_usdc: float = 50.0          # cap per individual trade
    # Risk
    max_open_positions: int = 15
    max_usdc_per_market: float = 100.0    # max exposure per market
    daily_loss_limit_usdc: float = 200.0  # stop copying if down this much
    # Timing
    poll_interval_seconds: float = 8.0    # how often to check followed wallets
    skip_sells: bool = True               # don't copy sell/exit orders
    min_original_size_usdc: float = 20.0  # ignore tiny trades (noise)
    # Take profit
    take_profit_at: float = 0.85          # sell when position reaches 85¢ if bought < 50¢


@dataclass
class TrackedTrade:
    market_id: str
    token_id: str
    side: str           # 'BUY' | 'SELL'
    price: float
    amount_usdc: float
    copied_at: datetime
    source_wallet: str
    order_id: str = ""


class CopyTrader:
    def __init__(self, client, wallet_scanner, config: CopyTraderConfig | None = None):
        self.client  = client
        self.scanner = wallet_scanner
        self.cfg     = config or CopyTraderConfig()
        self.sizer   = KellySizer(self.cfg.kelly_fraction)

        self._followed: list[str] = []           # wallet addresses to copy
        self._seen_tx:  set[str]  = set()        # already-processed tx IDs
        self._positions: dict[str, TrackedTrade] = {}  # token_id -> trade
        self._daily_pnl: float = 0.0
        self._last_reset: str = ""               # date string for daily reset

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_wallets(self, wallets: list[str]) -> None:
        self._followed = wallets
        logger.info("Copy trader watching %d wallets", len(wallets))

    def load_top_wallets(self, top_n: int = 10, category: str | None = None) -> None:
        """Auto-populate from leaderboard scan."""
        profiles = self.scanner.scan_leaderboard(top_n=200)
        if category:
            profiles = self.scanner.find_category_specialists(
                profiles, category, min_category_wr=0.60
            )
        self._followed = [p.address for p in profiles[:top_n]]
        logger.info("Auto-loaded %d wallets (category=%s)", len(self._followed), category or "all")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_once(self) -> list[TrackedTrade]:
        """Check all followed wallets for new trades. Returns executed copies."""
        self._maybe_reset_daily()
        if self._daily_pnl <= -self.cfg.daily_loss_limit_usdc:
            logger.warning("Daily loss limit hit (%.2f) — pausing", self._daily_pnl)
            return []

        executed: list[TrackedTrade] = []
        for wallet in self._followed:
            new_trades = self._fetch_new_trades(wallet)
            for trade in new_trades:
                result = self._process_trade(trade, wallet)
                if result:
                    executed.append(result)
                    time.sleep(0.05)  # don't hammer CLOB

        # Check take-profit on open positions
        self._check_take_profits()

        metrics.set("copy_trader_open_positions", len(self._positions))
        metrics.set("copy_trader_daily_pnl", self._daily_pnl)
        return executed

    def run_loop(self, running_flag) -> None:
        """Blocking loop — run in a thread."""
        logger.info("Copy trader started — polling every %.0fs", self.cfg.poll_interval_seconds)
        while running_flag():
            self.run_once()
            time.sleep(self.cfg.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Trade processing
    # ------------------------------------------------------------------

    def _fetch_new_trades(self, wallet: str) -> list[dict]:
        try:
            activity = self.client.get_wallet_activity(wallet, limit=20)
        except Exception as e:
            logger.debug("Activity fetch error for %s: %s", wallet[:10], e)
            return []

        new = []
        for tx in activity:
            tx_id = tx.get("id") or tx.get("tradeId") or str(tx)
            if tx_id in self._seen_tx:
                continue
            self._seen_tx.add(tx_id)
            new.append(tx)

        # Prevent set from growing unbounded
        if len(self._seen_tx) > 50_000:
            self._seen_tx = set(list(self._seen_tx)[-25_000:])

        return new

    def _process_trade(self, trade: dict, source_wallet: str) -> TrackedTrade | None:
        side  = (trade.get("side") or trade.get("type") or "BUY").upper()
        if self.cfg.skip_sells and side == "SELL":
            return None

        amount = float(trade.get("usdcSize") or trade.get("amount") or 0)
        if amount < self.cfg.min_original_size_usdc:
            return None

        price    = float(trade.get("price") or trade.get("outcomePrice") or 0)
        token_id = trade.get("asset") or trade.get("tokenId") or ""
        market_id = trade.get("market") or trade.get("conditionId") or ""

        if not token_id or price <= 0:
            return None

        # Don't double-up on same market
        if token_id in self._positions:
            return None
        if len(self._positions) >= self.cfg.max_open_positions:
            return None

        # Size the copy trade
        win_rate = self._get_wallet_win_rate(source_wallet)
        copy_size = self.sizer.size_usdc(
            win_rate=win_rate,
            avg_win=price,           # approximate: win = 1.0, loss = price
            avg_loss=price,
            bankroll=self._estimate_bankroll(),
            base_amount=self.cfg.usdc_per_trade,
        )
        copy_size = min(copy_size, self.cfg.max_trade_usdc)

        # Market exposure check
        existing_exposure = sum(
            t.amount_usdc for t in self._positions.values()
            if t.market_id == market_id
        )
        if existing_exposure + copy_size > self.cfg.max_usdc_per_market:
            logger.debug("Market exposure cap hit for %s", market_id[:12])
            return None

        # Execute
        logger.info(
            "Copying %s from %s: %s $%.2f @ %.3f",
            side, source_wallet[:10], token_id[:12], copy_size, price
        )
        try:
            resp = self.client.place_market_order(token_id, side, copy_size)
            order_id = resp.get("orderID") or resp.get("id") or ""
        except Exception as e:
            logger.error("Copy order failed: %s", e)
            metrics.inc("copy_trader_errors_total")
            return None

        tracked = TrackedTrade(
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            amount_usdc=copy_size,
            copied_at=datetime.now(timezone.utc),
            source_wallet=source_wallet,
            order_id=order_id,
        )
        self._positions[token_id] = tracked
        metrics.inc("copy_trader_trades_total", labels={"side": side})
        return tracked

    def _check_take_profits(self) -> None:
        """Sell positions that hit the take-profit threshold."""
        for token_id, pos in list(self._positions.items()):
            if pos.side != "BUY":
                continue
            if pos.price >= self.cfg.take_profit_at:
                # already entered at high price — skip
                continue
            try:
                current = self.client.get_midpoint(token_id)
                if current and current >= self.cfg.take_profit_at:
                    self.client.place_market_order(token_id, "SELL", pos.amount_usdc)
                    pnl = (current - pos.price) * (pos.amount_usdc / pos.price)
                    self._daily_pnl += pnl
                    logger.info("Take profit: %s @ %.3f pnl=%.2f", token_id[:12], current, pnl)
                    del self._positions[token_id]
                    metrics.inc("copy_trader_exits_total", labels={"reason": "take_profit"})
            except Exception as e:
                logger.debug("Take profit check failed %s: %s", token_id[:12], e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_wallet_win_rate(self, address: str) -> float:
        profile = self.scanner._wallet_cache.get(address)
        return profile.win_rate if profile else 0.55  # conservative default

    def _estimate_bankroll(self) -> float:
        return max(100.0, self.cfg.usdc_per_trade * 20)

    def _maybe_reset_daily(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset:
            self._daily_pnl = 0.0
            self._last_reset = today
