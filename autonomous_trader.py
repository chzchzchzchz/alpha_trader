#!/usr/bin/env python3
"""AUTONOMOUS KALSHI TRADER v16 — Backtest-Validated Every Signal"""
import os, sys, time, json, sqlite3, math, logging, random
from datetime import datetime, timezone
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient
import backtest_validation_layer as vlayer

KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")
API = "https://api.elections.kalshi.com/trade-api/v2"
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/autonomous.log")
STATS_PATH = os.path.expanduser("~/alpha_trader/data/stats.json")

# Config
COOLDOWN_SEC = 1800     # 30min cooldown per ticker after fill
MAX_STALE_CYCLES = 2    # Cancel unfilled orders after N cycles
MAX_DAILY_LOSS = 150    # cents
MAX_CONCURRENT = 3      # active orders
MIN_NET_PROFIT = 5      # cents expected profit threshold
CYCLE_SEC = 60

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("at")

SERIES = ["KXHIGHNY","KXLOWTPHIL","KXLOWTLAX","KXTEMPCHI","KXTEMPDAL",
          "KXTEMPMIA","KXTEMPNYC","KXTEMPHOUSTON","KXTEMPSEA","KXTEMPDEN",
          "KXTEMPATL","KXTEMPPHX","KXSNOWSTORM","KXWINDCHILL"]


class State:
    """Central state — filled trades, pending orders, portfolio awareness."""
    def __init__(self, conn):
        self.conn = conn
        self.filled = {}    # ticker -> [(ts, side, cents), ...]
        self.pending = {}   # ticker -> {order_id, ts, cents, side, stale_cycles}
        self._load()

    def _load(self):
        try:
            # Cancel ALL old resting orders from DB (from previous runs)
            self.conn.execute(
                "UPDATE trades SET status='cancelled_restart' "
                "WHERE status='resting'")
            self.conn.commit()

            # Load ALL executed fills (never drop — cooldown depends on this)
            rows = self.conn.execute(
                "SELECT ticker,side,price_cents,ts FROM trades "
                "WHERE status='executed' ORDER BY ts DESC").fetchall()
            for t, s, p, ts in rows:
                if t not in self.filled:
                    self.filled[t] = [(ts, s, p)]

            # Track tickers that failed to fill (to avoid repeat spam)
            rows = self.conn.execute(
                "SELECT ticker, MAX(ts), status FROM trades GROUP BY ticker HAVING status='resting'").fetchall()
            self.no_fill_until = {}  # ticker -> ts when we can retry
            for t, last_ts, st in rows:
                self.no_fill_until[t] = last_ts + 1800  # Don't retry for 30 min

            # No pending orders survive restart
            self.pending = {}
            log.info(f"  State: {len(self.filled)} filled tickers, {len(self.pending)} pending, "
                     f"{len(self.no_fill_until)} no-fill cooldowns")
        except Exception as e:
            log.warning(f"  State load failed: {e}")
            self.no_fill_until = {}

    def last_fill_ts(self, ticker: str) -> float:
        return self.filled.get(ticker, [(0,)])[0][0]

    def in_cooldown(self, ticker: str) -> bool:
        elapsed = time.time() - self.last_fill_ts(ticker)
        return elapsed < COOLDOWN_SEC

    def has_pending(self, ticker: str) -> bool:
        return ticker in self.pending

    def record_fill(self, ticker, side, cents):
        ts = int(time.time())
        self.filled.setdefault(ticker, []).insert(0, (ts, side, cents))
        self.pending.pop(ticker, None)

    def record_pending(self, ticker, oid, cents, side):
        self.pending[ticker] = dict(order_id=oid, ts=int(time.time()),
                                    cents=cents, side=side, stale_cycles=0)

    def tick_stale(self):
        for t in self.pending:
            self.pending[t]["stale_cycles"] += 1

    def stale_tickers(self, max_cycles=MAX_STALE_CYCLES) -> list:
        return [t for t, p in self.pending.items()
                if p["stale_cycles"] >= max_cycles]

    def purge_stale(self, max_cycles=MAX_STALE_CYCLES) -> list:
        """Remove stale orders from pending state."""
        stale = self.stale_tickers(max_cycles)
        for t in stale:
            self.pending.pop(t, None)
            # Mark as cancelled_in_memory in DB so they don't reload
            self.conn.execute(
                "UPDATE trades SET status='cancelled_stale' WHERE status='resting' AND ticker=?",
                (t,))
            self.conn.commit()
        return stale

    def portfolio_coherent(self, ticker: str, side: str) -> tuple:
        """Rule 4: no opposing positions on same underlying."""
        base = ticker.rsplit("-", 2)[0] if "-" in ticker else ticker
        for pt, pd in self.pending.items():
            pb = pt.rsplit("-", 2)[0] if "-" in pt else pt
            if pb == base and pd["side"] != side:
                return False, f"pending {pt} {pd['side']}"
        for ft, fills in self.filled.items():
            fb = ft.rsplit("-", 2)[0] if "-" in ft else ft
            if fb == base and time.time() - fills[0][0] < 1200:
                return False, f"recent fill {ft}"
        return True, "ok"

    def net_profit(self, side: str, cents: int, swarm_yes: float) -> float:
        """Expected profit after spread. swarm_yes in 0-1."""
        if side == "no":
            # Buy NO: cost=cents, payout=(100-cents) if event is NO
            win_prob = 1 - swarm_yes
            expected = win_prob * (100 - cents) - (1 - win_prob) * cents - 1
        else:
            win_prob = swarm_yes
            expected = win_prob * (100 - cents) - (1 - win_prob) * cents - 1
        return expected

    def save_trade(self, ticker, side, cents, status, oid):
        self.conn.execute("INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?)",
            (int(time.time()), ticker, side, cents, status, oid))
        self.conn.commit()

    def save_scan(self, ticker, price, swarm, edge, sig, score):
        self.conn.execute("INSERT INTO scans VALUES (?,?,?,?,?,?,?)",
            (int(time.time()), ticker, price, swarm, edge, sig, score))
        self.conn.commit()


class Swarm:
    def __init__(self, n=250):
        self.agents = []
        types = [("quant",0.20,0,0.3,0.8,True),("contrarian",0.15,0,0.6,-0.6,True),
                 ("bull",0.15,0.5,0.7,0.9,False),("bear",0.10,-0.4,0.8,0.7,False),
                 ("degen",0.15,0.3,1.1,0.6,True),("cautious",0.10,-0.1,0.2,0.3,False),
                 ("momentum",0.10,0,1.3,0.95,False),("news",0.05,0.2,0.9,0.7,True)]
        pid = 0
        for ptype,w,bias,vol,sens,cheap in types:
            for _ in range(max(5,int(n*w))):
                self.agents.append(dict(ptype=ptype,w=w,bias=bias,vol=vol,
                                        sens=sens,cheap=cheap))
                pid += 1
        self.agents = self.agents[:n]

    def predict(self, price, days):
        votes = []
        for a in self.agents:
            ch = price < 0.15
            if a["ptype"] == "quant":
                p = (1-price)*0.25+random.gauss(0,0.05) if ch and a["cheap"] else price+random.gauss(0,a["vol"]*0.05)
            elif a["ptype"] == "contrarian":
                p = 0.22+random.gauss(0,0.08) if ch and a["cheap"] else 1-price+random.gauss(0,0.06)
            elif a["ptype"] == "degen":
                p = 0.18+a["bias"]*0.2+random.gauss(0,0.1) if ch and a["cheap"] else price*(1+a["bias"]*0.5)+random.gauss(0,0.08)
            elif a["ptype"] == "news":
                p = 0.20+random.gauss(0,0.12) if ch and a["cheap"] else price+a["bias"]*0.05
            elif a["ptype"] == "bull":
                p = price*(1+a["bias"]*0.15)+random.gauss(0,a["vol"]*0.06)
            elif a["ptype"] == "bear":
                p = price*(1-abs(a["bias"])*0.1)-abs(a["bias"])*0.08+random.gauss(0,0.06)
            elif a["ptype"] == "momentum":
                p = price+a["sens"]*0.05+random.gauss(0,a["vol"]*0.07)
            else:
                p = price+a["bias"]*0.03+random.gauss(0,a["vol"]*0.06)
            if days is not None:
                p += random.gauss(0, 0.06*math.exp(-days/20))
            votes.append(("yes" if p>=0.5 else "no", max(0.01,min(0.99,p))))
        yes_w = sum(self.agents[i]["w"] for i,(v,_) in enumerate(votes) if v=="yes")
        no_w = sum(self.agents[i]["w"] for i,(v,_) in enumerate(votes) if v=="no")
        total = yes_w + no_w
        yp = yes_w / total if total > 0 else 0.5
        sig = abs(yp - 0.5) * 2
        edge = yp - price
        rec = "buy_yes" if yp > price + 0.04 else ("buy_no" if (1-yp) > (1-price)+0.04 else "hold")
        return dict(yes_pct=round(yp,4), signal=round(sig,3), edge=round(edge,4), rec=rec)


class Trader:
    def __init__(self):
        self.client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=False)
        self.swarm = Swarm(n=250)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (ts INT, ticker TEXT, price REAL,
                swarm_yes REAL, edge REAL, signal REAL, score REAL);
            CREATE TABLE IF NOT EXISTS trades (ts INT PRIMARY KEY, ticker TEXT,
                side TEXT, price_cents INT, status TEXT, order_id TEXT);
        """)
        self.conn.commit()
        self.state = State(self.conn)
        self.cycle = 0
        self.daily_pnl = 0
        self.stats = dict(total_scans=0, total_trades=0, cycles=0,
                          holds=0, skips=0)

    def save_stats(self):
        Path(STATS_PATH).write_text(json.dumps(self.stats, indent=2))

    def fetch_markets(self):
        all_mkts = []
        for series in SERIES:
            try:
                r = requests.get(
                    f"{API}/markets?series_ticker={series}&status=open&limit=50", timeout=15)
                if r.status_code == 200:
                    all_mkts.extend(r.json().get("markets", []))
                time.sleep(0.03)
            except: pass
        return all_mkts

    def scan(self):
        self.cycle += 1
        self.stats["cycles"] = self.cycle

        # Balance check
        try:
            bal = self.client.get_balance()
            cents = bal.get("balance", 0) + bal.get("portfolio_value", 0)
        except:
            cents = 0

        log.info(f"\n{'='*70}")
        log.info(f"CYCLE {self.cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | ${cents/100:.2f}")
        log.info(f"{'='*70}")
        log.info(f"  Cooldowns active: {sum(1 for t in self.state.pending if self.state.in_cooldown(t))}")
        log.info(f"  Pending orders: {len(self.state.pending)}")
        log.info(f"  Filled tickers: {len(self.state.filled)}")

        # Bump stale counters
        self.state.tick_stale()
        # Purge stale orders so they don't block new trades
        purged = self.state.purge_stale()
        if purged:
            log.warning(f"  PURGED {len(purged)} stale orders: {', '.join(purged[:5])}")

        mkts = self.fetch_markets()
        log.info(f"  Fetched {len(mkts)} open markets")

        all_signals = []
        for m in mkts:
            bid = m.get("yes_bid_dollars")
            ask = m.get("yes_ask_dollars")
            if bid is None or ask is None: continue
            bc, ac = float(bid), float(ask)
            if bc <= 0 and ac <= 0: continue
            price = (bc + ac) / 2
            vol = float(m.get("volume_24h_fp", 0) or 0)
            if vol < 5: continue

            days = None
            ct = m.get("close_time", "")
            if ct:
                try:
                    cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    days = max(0, (cdt - datetime.now(timezone.utc)).total_seconds() / 86400)
                except: pass

            result = self.swarm.predict(price, days)
            bc_cents = int(bc * 100)

            score = 0
            if 1 <= bc_cents <= 15 and result["edge"] > 0.02:
                score = abs(result["edge"]) * result["signal"] * 2000
            elif result["signal"] > 0.4 and abs(result["edge"]) > 0.08:
                score = abs(result["edge"]) * result["signal"] * 500

            if score > 0.3:
                all_signals.append(dict(
                    ticker=m["ticker"], price=price,
                    bid_cents=bc_cents, ask_cents=int(ac * 100),
                    swarm_yes=result["yes_pct"],
                    edge=result["edge"], signal=result["signal"],
                    rec=result["rec"], score=round(score, 2),
                    vol=vol, days=days,
                ))

        all_signals.sort(key=lambda s: s["score"], reverse=True)
        self.stats["total_scans"] += len(all_signals)

        log.info(f"  {'TICKER':48s} {'PRC':>4s} {'S_YES':>5s} {'EDGE':>6s} {'SIG':>4s} {'REC':>7s} {'VOL':>5s} {'SCORE':>5s}")
        log.info(f"  {'-'*88}")
        for s in all_signals[:15]:
            log.info(
                f"  {s['ticker']:48s} {s['price']*100:4.0f}c "
                f"{s['swarm_yes']:5.1%} {s['edge']:+6.1%} {s['signal']:4.2f} "
                f"{s['rec']:>7s} {s['vol']:5.0f} {s['score']:5.1f}")

        return all_signals

    def execute(self, signals, max_t=MAX_CONCURRENT):
        placed = 0
        skipped = dict(cooldown=0, already_pending=0, stale=0,
                       coherence=0, profit=0, holds=0, bt_fail=0)

        if self.daily_pnl < -MAX_DAILY_LOSS:
            log.warning(f"  ⛔ Daily loss limit hit (${abs(self.daily_pnl)/100:.2f})")
            return skipped

        # ── RULE 0: Backtest validation on every signal ──
        log.info(f"  [VALIDATION] Running backtest check on top signals...")
        validated_signals = []
        for sig in signals[:max_t * 3]:  # Validate more signals than max_t
            ticker = sig["ticker"]
            side = "yes" if sig["rec"] == "buy_yes" else "no"
            pc = sig["ask_cents"] if side == "yes" else max(1, int(sig["swarm_yes"] * 100))
            pc = max(1, min(pc, 15))

            strat = "near_zero_no" if side == "no" else "buy_yes_cheap"
            passed, bt_stats, reason = vlayer.validate_signal(ticker, side, strat, pc)

            if passed:
                sig["bt_stats"] = bt_stats
                sig["bt_reason"] = reason
                validated_signals.append(sig)
                log.info(f"    ✅ BT PASS: {ticker} {side} @ {pc}c — {reason}")
            else:
                log.info(f"    ❌ BT FAIL: {ticker} {side} @ {pc}c — {reason}")
                skipped["bt_fail"] += 1

        log.info(f"  [VALIDATION] {len(validated_signals)}/{len(signals[:max_t*3])} signals passed backtest")

        for sig in validated_signals:
            if placed >= max_t: break

            ticker = sig["ticker"]
            side = "yes" if sig["rec"] == "buy_yes" else "no"
            bid_c = sig.get("bid_cents", 1)
            ask_c = sig.get("ask_cents", 99)

            # ── FIX: Price logic for YES vs NO ──
            # YES buy: pay yes_ask_cents (1-99c range)
            # NO buy: pay (100 - yes_bid_cents) = the NO ask price

            # BLOCK already-resolved markets (100c or 0c = outcome known)
            if ask_c >= 98 or bid_c <= 2:
                skipped["profit"] += 1
                log.debug(f"    SKIP {ticker}: already resolved (bid={bid_c}c ask={ask_c}c)")
                continue

            if side == "yes":
                order_price = min(ask_c, 15)  # Cap at 15c max
                order_price = max(1, order_price)
            else:
                # NO ask = 100 - yes_bid. If yes_bid=11c, NO ask=89c
                # We only want YES-side cheap markets (<=15c yes_ask)
                # For NO, we buy when NO is cheap = when YES is expensive (>=85c)
                no_ask = 100 - bid_c  # NO ask price in cents
                no_bid = 100 - ask_c  # NO bid price in cents
                if no_ask > 85:
                    # NO is expensive, skip (this is a YES-lean market)
                    skipped["profit"] += 1
                    log.debug(f"    SKIP {ticker}: NO too expensive ({no_ask}c)")
                    continue
                order_price = no_ask  # Pay market price for NO
                if order_price < 30:
                    order_price = max(1, min(no_bid + 1, no_ask))  # Slightly above bid, at or below ask
                else:
                    order_price = max(1, min(no_ask, 30))

            swarm_yes = sig["swarm_yes"]

            # Rule 1: Cooldown
            if self.state.in_cooldown(ticker):
                remaining = COOLDOWN_SEC - (time.time() - self.state.last_fill_ts(ticker))
                log.debug(f"    SKIP {ticker}: cooldown {remaining:.0f}s remaining")
                skipped["cooldown"] += 1
                continue

            # Rule 2: Already have pending order on this?
            if self.state.has_pending(ticker):
                log.debug(f"    SKIP {ticker}: already have pending order")
                skipped["already_pending"] += 1
                continue

            # Rule 3: Stale check (redundant after purge, but safety net)
            if self.state.stale_tickers() and ticker in self.state.stale_tickers():
                skipped["stale"] += 1
                continue

            # Rule 4: Portfolio coherence
            ok, reason = self.state.portfolio_coherent(ticker, side)
            if not ok:
                log.debug(f"    SKIP {ticker}: portfolio incoherent — {reason}")
                skipped["coherence"] += 1
                continue

            # Rule 5: Min net profit (double-check with CORRECT price)
            expected = self.state.net_profit(side, order_price, swarm_yes)
            if expected < MIN_NET_PROFIT:
                log.debug(f"    SKIP {ticker}: expected profit {expected:.1f}c < {MIN_NET_PROFIT}c at {order_price}c")
                skipped["profit"] += 1
                continue

            # Signal quality gate
            if sig["score"] < 10:
                skipped["holds"] += 1
                continue

            bt = sig.get("bt_stats", {})
            bt_info = f"WR={bt.get('bt_win_rate',0):.1%} PnL={bt.get('bt_total_pnl',0):+.1f}c" if bt else "no BT data"
            log.info(f"  ▶ TRADE: {ticker} {side} x1 @{order_price}c [BT: {bt_info}] edge={sig['edge']:+.1%}")
            try:
                result = self.client.place_order(
                    ticker=ticker, action="buy", side=side, count=1,
                    yes_price=pc if side=="yes" else None,
                    no_price=pc if side=="no" else None)
                order = result.get("order",{})
                oid = order.get("order_id","?")
                status = order.get("status","?")
                self.conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)",
                    (int(time.time()), ticker, side, pc, status, oid))
                self.conn.commit()
                self.stats["total_trades"] += 1
                # Only count against daily PnL when EXECUTED, not when resting
                if status == "executed":
                    self.daily_pnl -= pc

                if status == "executed":
                    self.state.record_fill(ticker, side, pc)
                    log.info(f"    ✓ FILLED immediately")
                else:
                    self.state.record_pending(ticker, oid, pc, side)
                    log.info(f"    ⏳ Waiting for fill")
            except Exception as e:
                log.error(f"    ✗ FAIL: {e}")

        log.info(f"  Summary: {placed} placed | "
                 f"bt_fail:{skipped['bt_fail']} cooldown:{skipped['cooldown']} "
                 f"pending:{skipped['already_pending']} stale:{skipped['stale']} "
                 f"coherent:{skipped['coherence']} profit:{skipped['profit']} "
                 f"held:{skipped['holds']}")
        skipped["placed"] = placed
        self.stats["skips"] = self.stats.get("skips", 0) + sum(v for k, v in skipped.items() if k != "placed")
        return skipped

    def run(self):
        log.info(f"STARTING AUTONOMOUS TRADER v15.1 | API={API}")
        log.info(f"  Cooldown:{COOLDOWN_SEC//60}min | Loss cap:${MAX_DAILY_LOSS/100:.2f} | "
                 f"Max concurrent:{MAX_CONCURRENT} | Min profit:{MIN_NET_PROFIT}c")
        while True:
            try:
                signals = self.scan()
                self.execute(signals)
                self.save_stats()
                time.sleep(CYCLE_SEC)
            except KeyboardInterrupt:
                log.info("Shutdown")
                self.conn.close(); self.save_stats(); break
            except Exception as e:
                log.error(f"Crash: {e}", exc_info=True)
                time.sleep(15)


if __name__ == "__main__":
    Trader().run()
