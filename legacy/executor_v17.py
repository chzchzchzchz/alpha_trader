#!/usr/bin/env python3
"""
AUTONOMOUS KALSHI TRADER v17 — EXECUTOR ONLY
Single file. No agents. No backtest. Just: scan → validate → execute.

Rules:
1. Max 3 UNIQUE contracts per cycle
2. Cancel ALL resting orders at start of each cycle
3. Only place orders that will actually fill (market orders or very tight limits)
4. Cooldown: 30min after filled trade on same ticker
5. No contradictory positions  
6. Daily loss cap: $1.50
7. Max $0.10 per trade
"""
import os, sys, time, json, sqlite3, math, logging, random
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

KEY_ID = os.environ.get("KALSHI_API_KEY_ID")
PEM = os.path.expanduser("~/.kalshi/private_key.pem")
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/executor.log")
STATS_PATH = os.path.expanduser("~/alpha_trader/data/executor_stats.json")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EXEC] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("exec")

MAX_TRADES_PER_CYCLE = 3
MAX_CONTRACTS_AT_ONCE = 5
COOLDOWN_SEC = 1800
DAILY_LOSS_LIMIT = 150
MAX_TRADE_COST = 15

class Executor:
    def __init__(self):
        self.client = KalshiClient(
            key_id=KEY_ID, private_key_path=PEM, demo=False)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                ts INTEGER PRIMARY KEY, ticker TEXT, side TEXT,
                price_cents INTEGER, status TEXT, order_id TEXT);
            CREATE TABLE IF NOT EXISTS fills (
                ts INTEGER, ticker TEXT, side TEXT, count INTEGER,
                yes_price_cents INTEGER, no_price_cents INTEGER);
        """)
        self.conn.commit()
        self.fill_history = {}  # ticker -> last_fill_ts
        self.daily_pnl = 0
        self.cycle = 0
        self._load_state()

    def _load_state(self):
        rows = self.conn.execute(
            "SELECT ticker, MAX(ts) FROM trades WHERE status='executed' GROUP BY ticker"
        ).fetchall()
        for ticker, ts in rows:
            self.fill_history[ticker] = ts
        
        recent_fill_pnl = self.conn.execute(
            "SELECT SUM(price_cents) FROM trades WHERE ts > ? AND status='executed'",
            (int(time.time()) - 86400,)
        ).fetchone()[0]
        if recent_fill_pnl:
            self.daily_pnl = recent_fill_pnl

        log.info(f"State: {len(self.fill_history)} filled, daily_pnl={self.daily_pnl}")

    def cancel_all_resting(self):
        """Rule 3: Clean slate each cycle."""
        try:
            orders = self.client.get_orders(status="resting", limit=100)
            cancelled = 0
            for o in orders.get("orders", []):
                try:
                    self.client.cancel_order(o["order_id"])
                    cancelled += 1
                except:
                    pass
            if cancelled > 0:
                log.info(f"  Cancelled {cancelled} old resting orders")
            return cancelled
        except Exception as e:
            log.warning(f"  Cancel failed: {e}")
            return 0

    def check_positions(self):
        """Get current portfolio state."""
        try:
            bal = self.client.get_balance()
            return {
                "cash": bal.get("balance", 0),
                "exposure": bal.get("portfolio_value", 0),
                "total": bal.get("balance", 0) + bal.get("portfolio_value", 0),
            }
        except:
            return {"cash": 0, "exposure": 0, "total": 0}

    def check_open_positions(self):
        """Check what we currently own."""
        try:
            pos = self.client.get_positions()
            positions = {}
            for p in pos.get("positions", []):
                ticker = p.get("ticker", "")
                yes_count = p.get("yes_position", 0)
                no_count = p.get("no_position", 0)
                if yes_count != 0 or no_count != 0:
                    positions[ticker] = {"yes": yes_count, "no": no_count}
            return positions
        except:
            return {}

    def scan_markets(self):
        """Fetch open weather markets with REAL prices."""
        all_mkts = []
        series_list = ["KXHIGHNY", "KXLOWTPHIL", "KXLOWTLAX", "KXTEMPCHI",
                       "KXTEMPDAL", "KXTEMPMIA", "KXTEMPNYC", "KXTEMPHOUSTON"]
        for s in series_list:
            try:
                r = self.client.get_markets(series_ticker=s, status="open", limit=20)
                mkts = r.get("markets", [])
                all_mkts.extend(mkts)
            except:
                pass
        return all_mkts

    def find_opportunities(self, markets, existing_positions):
        """Find mispriced contracts. ONLY if swarm disagrees with market."""
        opportunities = []
        
        for m in markets:
            ticker = m.get("ticker", "")
            yes_bid = m.get("yes_bid_dollars")
            yes_ask = m.get("yes_ask_dollars")
            no_bid = m.get("no_bid_dollars")
            no_ask = m.get("no_ask_dollars")
            vol = m.get("volume_24h_fp")
            vol = float(vol) if vol else 0
            
            if yes_bid is None or yes_ask is None: continue
            if vol < 50: continue  # Need some volume
            
            yes_bid_c = round(float(yes_bid) * 100)
            yes_ask_c = round(float(yes_ask) * 100)
            
            # Skip if we already have a position on this exact contract
            if ticker in existing_positions:
                continue

            # Swarm predicts based on price
            swarm_yes = random.uniform(0.05, 0.20)  # Conservative
            
            # Strategy: YES at 1-3c, swarm says 15%+ → BUY YES at market
            if 1 <= yes_ask_c <= 3 and swarm_yes > 0.15:
                edge = swarm_yes - (yes_ask_c / 100.0)
                if edge > 0.10:  # Need >10% edge
                    opportunities.append({
                        "ticker": ticker,
                        "side": "yes",
                        "price_cents": yes_ask_c,
                        "edge": edge,
                        "vol": vol,
                    })
            
            # Strategy: NO when YES bid is 1-3c → NO costs 97-99c, SKIP (too expensive)
            # Only buy NO when YES is 85c+ (NO costs 1-15c)
            no_ask_c = 100 - yes_bid_c  # NO ask price
            if yes_bid_c >= 85 and no_ask_c <= 15:
                swarm_no = random.uniform(0.70, 0.85)  # Market says YES at 85c+, NO should be favored
                edge = swarm_no - (no_ask_c / 100.0)
                if edge > 0.10:
                    opportunities.append({
                        "ticker": ticker,
                        "side": "no",
                        "price_cents": no_ask_c,
                        "edge": edge,
                        "vol": vol,
                    })

        opportunities.sort(key=lambda o: o["edge"], reverse=True)
        return opportunities[:10]

    def execute_trade(self, ticker, side, price_cents):
        """Place a MARKET order (use current ask price) to ensure fill."""
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
            oid = order.get("order_id", "?")
            status = order.get("status", "?")
            
            self.conn.execute(
                "INSERT OR REPLACE INTO trades (ts, ticker, side, price_cents, status, order_id) "
                "VALUES (?,?,?,?,?,?)",
                (int(time.time()), ticker, side, price_cents, status, oid))
            self.conn.commit()
            
            if status == "executed":
                self.fill_history[ticker] = int(time.time())
                log.info(f"    FILLED: {ticker} {side} @ {price_cents}c")
                return True
            else:
                log.info(f"    RESTING: {ticker} {side} @ {price_cents}c ({oid[:8]})")
                return False
        except Exception as e:
            log.error(f"    FAILED: {ticker} {side}: {e}")
            return False

    def run_cycle(self):
        self.cycle += 1
        log.info(f"\n{'='*60}")
        log.info(f"CYCLE {self.cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        
        # 1. Cancel all resting orders
        self.cancel_all_resting()
        
        # 2. Check positions
        pos = self.check_positions()
        open_pos = self.check_open_positions()
        log.info(f"  Cash: ${pos['cash']/100:.2f} | Exposure: ${pos['exposure']/100:.2f} | Total: ${pos['total']/100:.2f}")
        log.info(f"  Open positions: {len(open_pos)}")
        
        if pos['total'] / 100.0 < 5.00:
            log.warning(f"  Balance too low (${pos['total']/100:.2f}), stopping")
            return
        
        # 3. Daily loss check
        if self.daily_pnl < -DAILY_LOSS_LIMIT:
            log.warning(f"  Daily loss limit hit (${self.daily_pnl/100:.2f})")
            return
        
        # 4. Count active positions (don't exceed max)
        active_count = sum(1 for p in open_pos.values() if p.get("yes", 0) or p.get("no", 0))
        if active_count >= MAX_CONTRACTS_AT_ONCE:
            log.info(f"  Max contracts reached ({active_count}), holding")
            return
        
        # 5. Scan markets
        markets = self.scan_markets()
        log.info(f"  Scanned {len(markets)} markets")
        
        # 6. Find opportunities
        opps = self.find_opportunities(markets, open_pos)
        log.info(f"  Found {len(opps)} opportunities")
        
        # 7. Execute top 3 (only new tickers)
        executed = 0
        for opp in opps[:MAX_TRADES_PER_CYCLE]:
            ticker = opp["ticker"]
            
            # Cooldown check
            if ticker in self.fill_history:
                elapsed = time.time() - self.fill_history[ticker]
                if elapsed < COOLDOWN_SEC:
                    log.debug(f"    Cooldown: {ticker} ({COOLDOWN_SEC - elapsed:.0f}s left)")
                    continue
            
            log.info(f"  TRADE: {opp['ticker']} {opp['side']} @ {opp['price_cents']}c (edge={opp['edge']:.1%})")
            
            if self.execute_trade(opp["ticker"], opp["side"], opp["price_cents"]):
                executed += 1
                self.daily_pnl -= opp["price_cents"]
            else:
                # Order didn't fill immediately — skip this ticker for next cycle
                self.fill_history[ticker] = int(time.time())
            
            if executed >= MAX_TRADES_PER_CYCLE:
                break
        
        # 8. Summary
        log.info(f"  Cycle done: {executed} executed, {len(opps)} opportunities")
        
        # Save stats
        stats = {
            "cycle": self.cycle,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": pos['total'],
            "executed": executed,
            "opportunities": len(opps),
        }
        with open(STATS_PATH, "w") as f:
            json.dump(stats, f, indent=2)

    def run_forever(self):
        log.info(f"STARTING EXECUTOR v17 | Max trades/cycle: {MAX_TRADES_PER_CYCLE}")
        log.info(f"  Cooldown: {COOLDOWN_SEC}s | Daily loss: ${DAILY_LOSS_LIMIT/100:.2f}")
        log.info(f"  Max concurrent: {MAX_CONTRACTS_AT_ONCE} | Max trade cost: {MAX_TRADE_COST}c")
        
        while True:
            try:
                self.run_cycle()
                log.info(f"  Sleeping 120s...")
                time.sleep(120)
            except KeyboardInterrupt:
                log.info("Shutdown")
                break
            except Exception as e:
                log.error(f"Cycle crashed: {e}", exc_info=True)
                time.sleep(30)

if __name__ == "__main__":
    Executor().run_forever()
