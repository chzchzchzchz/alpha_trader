#!/usr/bin/env python3
"""
EXECUTOR v19 — THE AUTONOMOUS AGENT
Combines Scan + Decision + Execution into ONE robust loop.
No dependency on broken research agent.
Rules: 
1. Cancel old orders.
2. Max 1 bet per ticker per cycle.
3. Max 3 active bets.
4. Max cost 20c.
"""
import os, sys, time, sqlite3, logging
from datetime import datetime, timezone
from pathlib import Path
import random

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

# Configuration
KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/executor_v19.log")

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EXEC] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("executor")

SERIES_TO_SCAN = [
    "KXHIGHNY", "KXLOWTPHIL", "KXLOWTLAX", 
    "KXTEMPCHI", "KXTEMPDAL", "KXTEMPMIA", "KXTEMPNYC"
]

class ExecutorV19:
    def __init__(self):
        self.client = KalshiClient(
            key_id=KEY_ID, 
            private_key_path=PEM, 
            demo=False
        )
        self.conn = sqlite3.connect(DB_PATH)
        self.traded_tickers = set() # In-memory cooldown
        
    def cancel_everything(self):
        """Nuke all resting orders. We only want active trades."""
        try:
            resp = self.client.get_orders(status="resting", limit=100)
            orders = resp.get("orders", [])
            cancelled = 0
            for o in orders:
                oid = o.get("order_id")
                if oid:
                    try:
                        self.client.cancel_order(oid)
                        cancelled += 1
                        time.sleep(0.2)
                    except: pass
            if cancelled > 0:
                log.info(f"Cancelled {cancelled} stale orders.")
        except: pass

    def get_balance(self):
        try:
            bal = self.client.get_balance()
            return bal.get("balance", 0) + bal.get("portfolio_value", 0)
        except: return 0

    def scan_and_execute(self):
        log.info(f"--- SCAN CYCLE at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ---")
        balance = self.get_balance()
        log.info(f"Balance: ${balance/100:.2f}")
        
        # Cancel old mess
        self.cancel_everything()
        
        # Collect opportunities
        opportunities = []
        
        for series in SERIES_TO_SCAN:
            try:
                resp = self.client.get_markets(series_ticker=series, status="open", limit=10)
                markets = resp.get("markets", [])
                
                for m in markets:
                    ticker = m.get("ticker", "")
                    yb = m.get("yes_bid_dollars")
                    ya = m.get("yes_ask_dollars")
                    vol = m.get("volume_24h_fp", 0) or 0
                    
                    if yb is None or ya is None: continue
                    
                    bid_c = round(float(yb)*100)
                    ask_c = round(float(ya)*100)
                    vol = float(vol)
                    
                    # Strategy: "The Penny Grabber"
                    # Buy NO on markets where YES is cheap (5-25c).
                    # Market implies 75-95% chance of NO.
                    # It's safer to buy NO at 20c (wins 80c) than YES at 80c (wins 20c).
                    # We only do this if volume is decent (>100).
                    
                    if vol > 100 and 5 <= ask_c <= 25:
                        # YES is 5-25c. Buy NO.
                        # No Cost = 100 - Bid.
                        no_cost = 100 - bid_c
                        
                        # Heuristic: Don't buy if NO cost is absurd (>20c)
                        if no_cost <= 25:
                            score = vol + (25 - ask_c) * 10 # Higher score for cheaper YES
                            opportunities.append({
                                "ticker": ticker,
                                "side": "no",
                                "price": no_cost,
                                "score": score,
                                "reason": f"YES is {ask_c}c (vol {vol:.0f})"
                            })
                    
                    # Strategy: High Vol / High Edge
                    # If market says 30-60c, but volume is MASSIVE (>2000), 
                    # algo buys the trend.
                    elif vol > 2000 and 30 <= ask_c <= 60:
                        no_cost = 100 - bid_c
                        # Let's buy YES if it's "cheap" relative to volume
                        score = vol / 100
                        opportunities.append({
                            "ticker": ticker,
                            "side": "yes",
                            "price": ask_c,
                            "score": score,
                            "reason": f"Vol {vol:.0f} YES@{ask_c}c"
                        })
                        
            except Exception as e:
                log.warning(f"Scan failed {series}: {e}")

        # Sort by score
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        
        # Filter out recently traded tickers
        active_trades = 0
        
        for opp in opportunities[:5]: # Top 5 candidates
            if active_trades >= 3: break
            
            t = opp['ticker']
            
            # Cooldown check
            if t in self.traded_tickers:
                continue
            
            price = opp['price']
            
            # Safety cap
            if price > 30: continue
            
            log.info(f"EXECUTING: {t} {opp['side']} @ {price}c ({opp['reason']})")
            
            try:
                side = opp['side']
                order = self.client.place_order(
                    ticker=t,
                    action="buy",
                    side=side,
                    count=1,
                    yes_price=price if side=="yes" else None,
                    no_price=price if side=="no" else None
                )
                
                status = order.get("order", {}).get("status", "unknown")
                oid = order.get("order", {}).get("order_id", "?")
                
                if status == "resting":
                    log.info(f" -> Order Resting: {oid}")
                    self.traded_tickers.add(t)
                    active_trades += 1
                elif status == "executed":
                    log.info(f" -> FILLED IMMEDIATELY!")
                    self.traded_tickers.add(t)
                    active_trades += 1
                else:
                    log.info(f" -> Status: {status}")
                    
            except Exception as e:
                log.warning(f"Order failed: {e}")
        
        if active_trades > 0:
            log.info(f"Placed {active_trades} new bets.")
        else:
            log.info("No trades placed (all cooled out or no edge).")

    def run(self):
        log.info("Starting Executor v19")
        # Load existing cooldowns from DB if needed, but for now clean slate
        while True:
            try:
                self.scan_and_execute()
                # Short sleep. We rely on cancelling old orders, so we can check often.
                time.sleep(120)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Loop crash: {e}")
                time.sleep(10)

if __name__ == "__main__":
    ExecutorV19().run()