#!/usr/bin/env python3
"""
EXECUTOR — Reads research proposals and places orders.
Rules: max 3 unique contracts per cycle, cancel resting first, track fills.
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/executor.log")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EXEC] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("exec")


class Executor:
    def __init__(self):
        self.client = KalshiClient(
            key_id='REDACTED_KALSHI_KEY_ID',
            private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
            demo=False
        )
        self.conn = sqlite3.connect(DB_PATH)
        self.tried = set()   # contracts we've already ordered
        self.fill_times = {}  # ticker → ts for cooldown
        self.daily_spent = 0
        self.cycle = 0

    def cancel_all_resting(self):
        """Clear all resting orders from previous cycles."""
        try:
            resp = self.client.get_orders(status="resting", limit=100)
            orders = resp.get("orders", [])
            cancelled = 0
            for o in orders:
                try:
                    self.client.cancel_order(o["order_id"])
                    cancelled += 1
                    time.sleep(0.15)
                except:
                    pass
            if cancelled:
                log.info(f"  Cancelled {cancelled} old resting orders")
        except Exception as e:
            log.warning(f"  Cancel failed: {e}")

    def get_position_and_balance(self):
        """Get current balance and open positions."""
        try:
            bal = self.client.get_balance()
            positions_resp = self.client.get_positions()
            positions = {}
            for p in positions_resp.get("positions", []):
                t = p.get("ticker", "")
                yes = p.get("yes_position", 0)
                no = p.get("no_position", 0)
                if yes or no:
                    positions[t] = {"yes": yes, "no": no}
            return {
                "cash": bal.get("balance", 0),
                "exposure": bal.get("portfolio_value", 0),
                "positions": positions,
            }
        except Exception as e:
            log.warning(f"  Balance check failed: {e}")
            return {"cash": 0, "exposure": 0, "positions": {}}

    def get_proposals(self):
        """Get fresh proposals from research agent."""
        cutoff = int(time.time()) - 180  # Last 3 min
        rows = self.conn.execute(
            "SELECT ticker, side, strategy, price_cents, edge, score, "
            "market_yes_ask, market_yes_bid, vol, swarm_yes, details "
            "FROM research_proposals WHERE ts > ? "
            "ORDER BY score DESC",
            (cutoff,)
        ).fetchall()
        proposals = []
        for r in rows:
            proposals.append({
                "ticker": r[0], "side": r[1], "strategy": r[2],
                "price_cents": r[3], "edge": r[4], "score": r[5],
                "market_yes_ask": r[6], "market_yes_bid": r[7],
                "vol": r[8], "swarm_yes": r[9], "details": r[10],
            })
        return proposals

    def place_order(self, ticker, side, price_cents):
        """Place an order at correct price (market taker for fill)."""
        try:
            result = self.client.place_order(
                ticker=ticker,
                action="buy",
                side=side,
                count=1,
                yes_price=price_cents if side == "yes" else None,
                no_price=price_cents if side == "no" else None,
            )
            order = result.get("order", {})
            return order.get("order_id", ""), order.get("status", "unknown")
        except Exception as e:
            return "error", str(e)[:100]

    def run_cycle(self):
        self.cycle += 1
        log.info(f"\n{'='*60}")
        log.info(f"EXEC CYCLE {self.cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

        # 1. Cancel all resting orders (clean slate)
        self.cancel_all_resting()

        # 2. Check balance and positions
        pos = self.get_position_and_balance()
        cash = pos.get("cash", 0)
        exposure = pos.get("exposure", 0)
        total = cash + exposure
        positions = pos.get("positions", {})
        log.info(f"  Cash: ${cash/100:.2f} | Exposure: ${exposure/100:.2f} | Total: ${total/100:.2f}")
        if positions:
            log.info(f"  Current positions: {len(positions)}")
            for t, p in positions.items():
                log.info(f"    {t}: YES={p['yes']} NO={p['no']}")

        if cash < 100:
            log.warning("  Cash too low, stopping")
            return

        # 3. Daily spend check
        if self.daily_spent >= 150:
            log.warning(f"  Daily limit hit: ${self.daily_spent/100:.2f}")
            return

        # 4. Get proposals from research
        proposals = self.get_proposals()
        log.info(f"  Research proposals: {len(proposals)}")

        # 5. Execute top 3 unique contracts
        executed = 0
        skip_reasons = {"already_tried": 0, "cooldown": 0, "has_position": 0}

        for prop in proposals[:10]:
            if executed >= 3:
                break

            ticker = prop["ticker"]
            side = prop["side"]
            price = min(prop["price_cents"], 15)
            details = prop.get("details", "")

            # Rule 1: Don't trade same contract twice
            if ticker in self.tried:
                skip_reasons["already_tried"] += 1
                continue

            # Rule 2: Don't add more if we already have a position
            if ticker in positions:
                skip_reasons["has_position"] += 1
                continue

            # Rule 3: Cooldown on series
            series = "-".join(ticker.split("-")[:2])
            if series in self.fill_times:
                elapsed = time.time() - self.fill_times[series]
                if elapsed < 1800:  # 30 min cooldown per series
                    skip_reasons["cooldown"] += 1
                    continue

            # Mark as tried immediately (one shot only per contract)
            self.tried.add(ticker)

            log.info(f"  EXECUTE: {ticker} {side} @ {price}c | {details}")

            order_id, status = self.place_order(ticker, side, price)
            ts = int(time.time())

            if status == "executed":
                self.fill_times[series] = ts
                self.daily_spent += price
                executed += 1
                log.info(f"    ✅ FILLED")
            else:
                log.info(f"    ⏳ Status: {status} ({order_id[:8] if order_id != 'error' else order_id})")

        # Summary
        log.info(f"  Summary: {executed} executed, "
                 f"tried={skip_reasons['already_tried']} "
                 f"pos={skip_reasons['has_position']} "
                 f"cooldown={skip_reasons['cooldown']}")
    
    def run_forever(self):
        log.info(f"EXECUTOR starting | Daily spend limit: $1.50")
        while True:
            try:
                self.run_cycle()
                log.info(f"  Next cycle in 60s")
                time.sleep(60)
            except KeyboardInterrupt:
                log.info("Stopped")
                break
            except Exception as e:
                log.error(f"Crash: {e}", exc_info=True)
                time.sleep(30)


if __name__ == "__main__":
    Executor().run_forever()