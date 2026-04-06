#!/usr/bin/env python3
"""AUTONOMOUS KALSHI TRADER v13 — The Print Money Machine"""
import os, sys, time, json, sqlite3, math, logging, random
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")
KALSHI_DEMO = True
SPREAD_CENTS = 2
MAX_DAILY_LOSS_CENTS = 150
MAX_SINGLE_TRADE_CENTS = 10
MAX_CONCURRENT_TRADES = 3
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/autonomous.log")
STATS_PATH = os.path.expanduser("~/alpha_trader/data/stats.json")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger("autonomous")


class Agent:
    TYPES = [
        ("quant",      0.20, 0.0,  0.3,  0.8),
        ("contrarian", 0.15, 0.0,  0.6, -0.6),
        ("bull",       0.15, 0.5,  0.7,  0.9),
        ("bear",       0.10,-0.4,  0.8,  0.7),
        ("degen",      0.15, 0.3,  1.1,  0.6),
        ("cautious",   0.10,-0.1,  0.2,  0.3),
        ("momentum",   0.10, 0.0,  1.3,  0.95),
        ("news",       0.05, 0.2,  0.9,  0.7),
    ]
    def __init__(self, pid, ptype, w, bias, vol, sens):
        self.pid = pid; self.ptype = ptype; self.w = w
        self.bias = bias; self.vol = vol; self.sens = sens

    def vote(self, price, days):
        cheap = price < 0.15
        if self.ptype == "quant":
            p = (1-price)*0.25 + random.gauss(0,0.05) if (cheap) else price + random.gauss(0, self.vol*0.05)
        elif self.ptype == "contrarian":
            p = 0.22 + random.gauss(0,0.08) if cheap else 1-price + random.gauss(0,0.06)
        elif self.ptype == "degen":
            p = 0.18 + self.bias*0.2 + random.gauss(0,0.1) if cheap else price*(1+self.bias*0.5) + random.gauss(0,0.08)
        elif self.ptype == "news":
            p = 0.20 + random.gauss(0,0.12) if cheap else price + self.bias*0.05
        elif self.ptype == "bull":
            p = price*(1 + self.bias*0.15) + random.gauss(0, self.vol*0.06)
        elif self.ptype == "bear":
            p = price*(1 - abs(self.bias)*0.1) - abs(self.bias)*0.08 + random.gauss(0,0.06)
        elif self.ptype == "momentum":
            p = price + self.sens*0.05 + random.gauss(0, self.vol*0.07)
        else:
            p = price + self.bias*0.03 + random.gauss(0, self.vol*0.06)
        if days is not None:
            p += random.gauss(0, 0.06 * math.exp(-days/20))
        return "yes" if p >= 0.5 else "no", max(0.01, min(0.99, p))


class Swarm:
    def __init__(self, n=200):
        self.agents = []
        pid = 0
        for ptype, w, bias, vol, sens in Agent.TYPES:
            for _ in range(max(5, int(n*w))):
                self.agents.append(Agent(pid, ptype, w, bias, vol, sens))
                pid += 1
        self.agents = self.agents[:n]

    def predict(self, price, days):
        votes = [a.vote(price, days) for a in self.agents]
        yes_w = sum(self.agents[i].w for i,(v,_) in enumerate(votes) if v=="yes")
        no_w  = sum(self.agents[i].w for i,(v,_) in enumerate(votes) if v=="no")
        total = yes_w + no_w
        yp = yes_w/total if total > 0 else 0.5
        sig = abs(yp-0.5)*2
        edge = yp - price
        rec = "buy_yes" if yp > price+0.04 else ("buy_no" if (1-yp) > (1-price)+0.04 else "hold")
        return {"yes_pct": round(yp,4), "signal": round(sig,3), "edge": round(edge,4),
                "rec": rec, "yv": sum(1 for v,_ in votes if v=="yes"),
                "nv": sum(1 for v,_ in votes if v=="no")}


class Trader:
    def __init__(self):
        self.client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=KALSHI_DEMO)
        self.swarm = Swarm(n=250)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (ts INT, ticker TEXT, price REAL,
                swarm_yes REAL, edge REAL, signal REAL, score REAL);
            CREATE TABLE IF NOT EXISTS trades (ts INT, ticker TEXT, side TEXT,
                price_cents INT, status TEXT, order_id TEXT);
            CREATE TABLE IF NOT EXISTS daily_stats (date TEXT PRIMARY KEY,
                balance REAL, n_scans INT, n_trades INT, pnl REAL);
        """)
        self.conn.commit()
        self.cycle = 0
        self.daily_pnl = 0
        self.stats = {"total_scans":0, "total_trades":0, "cycles":0}
        if os.path.exists(STATS_PATH):
            try:
                with open(STATS_PATH) as f: self.stats.update(json.load(f))
            except: pass

    def save_stats(self):
        with open(STATS_PATH, "w") as f: json.dump(self.stats, f, indent=2)

    def scan(self):
        self.cycle += 1
        self.stats["cycles"] = self.cycle
        try:
            bal = self.client.get_balance()
            cents = bal.get("balance",0) + bal.get("portfolio_value",0)
        except: cents = 0

        log.info(f"\n{'='*70}")
        log.info(f"CYCLE {self.cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')} | ${cents/100:.2f}")
        log.info(f"{'='*70}")

        series_list = ["KXHIGHNY","KXINX","KXBTC100K","KXWEATHER","KXETH"]
        all_signals = []

        for series in series_list[:4]:
            try:
                r = self.client.get_markets(series_ticker=series, limit=10)
                for m in r.get("markets",[]):
                    bid = m.get("yes_bid_dollars")
                    ask = m.get("yes_ask_dollars")
                    if bid is None or ask is None: continue
                    bc, ac = float(bid), float(ask)
                    price = (bc+ac)/2
                    vol = m.get("volume_24h_fp",0) or 0
                    if vol < 5: continue

                    days = None
                    ct = m.get("close_time","")
                    if ct:
                        try:
                            cdt = datetime.fromisoformat(ct.replace("Z","+00:00"))
                            days = max(0, (cdt-datetime.now(timezone.utc)).total_seconds()/86400)
                        except: pass

                    result = self.swarm.predict(price, days)
                    bc_cents = int(bc*100)
                    score = 0
                    if 1 <= bc_cents <= 15 and result["edge"] > 0.02:
                        score = abs(result["edge"]) * result["signal"] * 2000
                    elif result["signal"] > 0.4 and abs(result["edge"]) > 0.08:
                        score = abs(result["edge"]) * result["signal"] * 500

                    if score > 0.3:
                        all_signals.append({
                            "ticker": m["ticker"], "price": price,
                            "bid_cents": bc_cents, "ask_cents": int(ac*100),
                            "swarm_yes": result["yes_pct"], "edge": result["edge"],
                            "signal": result["signal"], "rec": result["rec"],
                            "score": round(score,2), "vol": vol, "days": days,
                        })
            except Exception as e:
                log.debug(f"  {series}: {e}")

        all_signals.sort(key=lambda s: s["score"], reverse=True)
        self.stats["total_scans"] += len(all_signals)

        log.info(f"  Signals: {len(all_signals)}")
        if all_signals:
            hdr = f"  {'TICKER':48s} {'PRC'} {'S_YES'}  {'EDGE'} {'SIG'} {'REC':>7s} {'VOL':>5s} {'SCORE'}"
            log.info(hdr)
            log.info(f"  {'-'*len(hdr)}")
            for s in all_signals[:12]:
                log.info(f"  {s['ticker']:48s} {s['price']*100:3.0f}c {s['swarm_yes']:5.1%} {s['edge']:+5.1%} "
                         f"{s['signal']:.2f} {s['rec']:>7s} {s['vol']:5.0f} {s['score']:5.1f}")

        now = int(time.time())
        for s in all_signals:
            self.conn.execute("INSERT INTO scans VALUES (?,?,?,?,?,?,?)",
                (now, s["ticker"], s["price"], s["swarm_yes"], s["edge"], s["signal"], s["score"]))
        self.conn.commit()
        return all_signals

    def execute(self, signals, max_t=3):
        done = 0
        for sig in signals[:max_t*2]:
            if sig["rec"] not in ("buy_yes","buy_no") or sig["score"] < 0.5: continue
            if done >= max_t: break
            if self.daily_pnl < -MAX_DAILY_LOSS_CENTS:
                log.warning(f"  Daily loss limit ({self.daily_pnl}c)")
                break

            ticker = sig["ticker"]
            side = "yes" if sig["rec"]=="buy_yes" else "no"
            pc = sig["ask_cents"] if side=="yes" else int(sig["swarm_yes"]*100)
            pc = max(1, min(pc, MAX_SINGLE_TRADE_CENTS))

            log.info(f"  TRADE: {ticker} {side} x1 @{pc}c edge={sig['edge']:+.1%} score={sig['score']:.1f}")
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
                self.daily_pnl -= pc
                done += 1
                log.info(f"    -> {oid}: {status}")
            except Exception as e:
                log.error(f"    -> FAIL: {e}")
        return done

    def run(self):
        log.info(f"STARTING AUTONOMOUS TRADER v13 | Demo={KALSHI_DEMO}")
        while True:
            try:
                signals = self.scan()
                n = self.execute(signals)
                log.info(f"  Done: {len(signals)} signals, {n} trades. Next in 60s.")
                self.save_stats()
                time.sleep(60)
            except KeyboardInterrupt:
                self.conn.close(); self.save_stats(); break
            except Exception as e:
                log.error(f"Crash: {e}"); time.sleep(15)


if __name__ == "__main__":
    Trader().run()
