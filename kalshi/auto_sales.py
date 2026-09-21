#!/usr/bin/env python3
"""
Auto-Sales Engine — monitors open positions and executes exit orders.
Uses proper 'sell' action to close positions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("auto_sales")

from kalshi.client import KalshiClient
from kalshi.orchestrator import StrategyOrchestrator

@dataclass
class ExitSignal:
    ticker: str
    side: str  # 'yes' or 'no' - the SIDE of the position we are exiting (sell this side)
    reason: str
    priority: int
    size: int
    price_cents: Optional[int] = None

class AutoSalesEngine:
    def __init__(self, client: KalshiClient, db_conn, orchestrator: StrategyOrchestrator):
        self.client = client
        self.db_conn = db_conn
        self.orchestrator = orchestrator
        self.STOP_LOSS_CENTS = -5
        self.TAKE_PROFIT_CENTS = 10
        self.MAX_HOLD_DAYS = 30.0

    def scan_positions(self) -> List[ExitSignal]:
        exits = []
        positions = self._get_open_positions_from_db()
        if not positions:
            return exits
        market_prices = self._fetch_market_prices([p['ticker'] for p in positions])
        for pos in positions:
            ticker = pos['ticker']
            side = pos['side']  # 'yes' or 'no' - the side we hold
            entry_cents = pos['entry_price_cents']
            contracts = pos['contracts']
            entry_ts = pos['entry_ts']
            current_price = market_prices.get(ticker)
            if current_price is None:
                continue
            # Compute P&L in cents for the held side
            if side == 'yes':
                current_cents = int(current_price * 100)
                pnl_cents = current_cents - entry_cents
            else:
                current_cents = int((1.0 - current_price) * 100)
                pnl_cents = entry_cents - current_cents
            reason = None
            priority = 99
            if pnl_cents <= self.STOP_LOSS_CENTS:
                reason = f"stop_loss: {pnl_cents}c"
                priority = 1
            elif pnl_cents >= self.TAKE_PROFIT_CENTS:
                reason = f"take_profit: {pnl_cents}c"
                priority = 2
            age_days = (datetime.now(timezone.utc).timestamp() - entry_ts) / 86400
            if age_days >= self.MAX_HOLD_DAYS:
                reason = f"max_hold: {age_days:.1f}d"
                priority = 3
            if reason:
                exits.append(ExitSignal(
                    ticker=ticker,
                    side=side,  # Sell the same side we hold
                    reason=reason,
                    priority=priority,
                    size=contracts,
                    price_cents=current_cents if priority <= 2 else None,
                ))
        exits.sort(key=lambda x: x.priority)
        return exits

    def _get_open_positions_from_db(self) -> List[dict]:
        positions = []
        try:
            cur = self.db_conn.cursor()
            cur.execute("""
                SELECT ticker, strategy, side, entry_price_cents, contracts, entry_ts
                FROM positions
                WHERE status != 'closed'
            """)
            for ticker, strategy, side, entry_price_cents, contracts, entry_ts in cur.fetchall():
                positions.append({
                    'ticker': ticker,
                    'strategy': strategy,
                    'side': side,
                    'entry_price_cents': entry_price_cents,
                    'contracts': contracts,
                    'entry_ts': entry_ts,
                })
        except Exception as e:
            logger.error(f"Error fetching open positions: {e}")
        return positions

    def _fetch_market_prices(self, tickers: List[str]) -> Dict[str, float]:
        markets = self.orchestrator.analyzer.fetch_all_markets()
        price_map = {}
        for m in markets:
            if m.ticker in tickers:
                price_map[m.ticker] = m.yes_mid_price
        return price_map

    def execute_exits(self, exit_signals: List[ExitSignal]) -> int:
        executed = 0
        for signal in exit_signals:
            try:
                ticker = signal.ticker
                side = signal.side
                contracts = signal.size
                price_cents = signal.price_cents
                if price_cents is None:
                    price = self._fetch_market_prices([ticker]).get(ticker)
                    if price is None:
                        continue
                    price_cents = int(price * 100) if side == 'yes' else int((1.0 - price) * 100)
                    price_cents = max(1, price_cents)
                logger.info("AUTO-EXIT: %s SELL %s x%d @ %dc reason=%s", ticker, side.upper(), contracts, price_cents, signal.reason)
                result = self.client.place_order(
                    ticker=ticker,
                    action="sell",  # Proper sell action
                    side=side,
                    count=contracts,
                    type="limit",
                    yes_price=price_cents if side == 'yes' else None,
                    no_price=price_cents if side == 'no' else None,
                    client_order_id=f"exit-{datetime.now(timezone.utc).timestamp()}",
                )
                order = result.get("order", {})
                oid = order.get("order_id")
                if oid:
                    # Immediately mark position closed - in demo orders fill instantly
                    self._mark_position_closed(ticker, oid, price_cents)
                    executed += 1
            except Exception as e:
                logger.error("Exit failed for %s: %s", ticker, e)
        return executed

    def _mark_position_closed(self, ticker: str, closing_order_id: str, exit_price_cents: int):
        try:
            cur = self.db_conn.cursor()
            # Mark all trades for this ticker that are still open
            cur.execute("""
                UPDATE trades
                SET exit_ts = ?, exit_price_cents = ?, exit_status = ?, closing_trade = ?
                WHERE ticker = ? AND exit_ts IS NULL
            """, (int(time.time()), exit_price_cents, "filled", closing_order_id, ticker))
            # Close position
            cur.execute("""
                UPDATE positions
                SET status = 'closed'
                WHERE ticker = ?
            """, (ticker,))
            self.db_conn.commit()
        except Exception as e:
            logger.error("Failed to mark position closed: %s", e)
