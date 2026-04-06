#!/usr/bin/env python3
"""AUTONOMOUS KALSHI TRADER v14 — The Print Money Machine"""
import os, sys, time, json, sqlite3, math, logging, random
from datetime import datetime, timezone
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")
API = "https://api.elections.kalshi.com/trade-api/v2"
SPREAD_CENTS = 2
MAX_DAILY_LOSS_CENTS = 150
MAX_SINGLE_PRICE_CENTS = 15
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
log = logging.getLogger("at")

SERIES = ["KXHIGHNY","KXLOWTPHIL","KXLOWTLAX","KXTEMPCHI",
          "KXTEMPDAL","KXTEMPMIA","KXTEMPNYC","KXTEMPHOUSTON",
          "KXTEMPSEA","KXTEMPDEN","KXTEMPATL","KXTEMPPHX",
          "KXSNOWSTORM","KXWINDCHILL"]


class Swarm:
    def __init__(self, n=250):
        self.agents = []
        types = [
            ("quant",0.20,0,0.3,0.8,True),
            ("contrarian",0.15,0,0.6,-0.6,True),
            ("bull",0.15,0.5,0.7,0.9,False),
            ("bear",0.10,-0.4,0.8,0.7,False),
            ("degen",0.15,0.3,1.1,0.6,True),
            ("cautious",0.10,-0.1,0.2,0.3,False),
            ("momentum",0.10,0,1.3,0.95,False),
            ("news",0.05,0.2,0.9,0.7,True),
        ]
        pid = 0
        for ptype,w,bias,vol,sens,cheap in types:
            for _ in range(max(5,int(n*w))):
                self.agents.append(dict(pid=pid,ptype=ptype,w=w,bias=bias,vol=vol,sens=sens,cheap=cheap))
                pid += 1
        self.agents = self.agents[:n]

    def predict(self, price, days):
        votes = []
        for a in self.agents:
            ch = price < 0.15
            if a["ptype"] == "quant":
                p = (1-price)*0.25 + random.gauss(0,0.05) if ch and a["cheap"] else price+random.gauss(0,a["vol"]*0.05)
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
                p += random.gauss(0,0.06*math.exp(-days/20))
            votes.append(("yes" if p>=0.5 else "no", max(0.01,min(0.99,p))))

        yes_w = sum(self.agents[i]["w"] for i,(v,_) in enumerate(votes) if v=="yes")
        no_w = sum(self.agents[i]["w"] for i,(v,_) in enumerate(votes) if v=="no")
        total = yes_w+no_w
        yp = yes_w/total if total>0 else 0.5
        sig = abs(yp-0.5)*2
        edge = yp - price
        if yp > price+0.04:
            rec = "buy_yes"
        elif (1-yp) > (1-price)+0.04:
            rec = "buy_no"
        else:
            rec = "hold"
        return dict(yes_pct=round(yp,4), signal=round(sig,3), edge=round(edge,4),
                    rec=rec, yv=sum(1 for v,_ in votes if v=="yes"),
                    nv=sum(1 for v,_ in votes if v=="no"))


class Trader:
    def __init__(self):
        self.client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=False)
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
        self.stats = dict(total_scans=0, total_trades=0, cycles=0)
        if os.path.exists(STATS_PATH):
            try:
                with open(STATS_PATH) as f: self.stats.update(json.load(f))
            except: pass

    def save_stats(self):
        with open(STATS_PATH, "w") as f: json.dump(self.stats, f, indent=2)

    def fetch_markets_public(self):
        all_mkts = []
        for series in SERIES:
            try:
                url = f"{API}/markets?series_ticker={series}&status=open&limit=50"
                r = requests.get(url, timeout=15)
                if r.status_code == 200:
                    mkts = r.json().get("markets", [])
                    all_mkts.extend(mkts)
                time.sleep(0.05)
            except Exception as e:
                log.debug(f"  {series}: {e}")
        return all_mkts

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

        mkts = self.fetch_markets_public()
        log.info(f"  Fetched {len(mkts)} open markets")

        all_signals = []
        for m in mkts:
            bid = m.get("yes_bid_dollars")
            ask = m.get("yes_ask_dollars")
            if bid is None or ask is None: continue
            bc = float(bid)
            ac = float(ask)
            if bc <= 0 and ac <= 0: continue
            price = (bc+ac)/2
            vol = float(m.get("volume_24h_fp",0) or 0)
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

            # NearZero: cheap markets + swarm edge
            score = 0
            if 1 <= bc_cents <= 15 and result["edge"] > 0.02:
                score = abs(result["edge"]) * result["signal"] * 2000
            elif result["signal"] > 0.4 and abs(result["edge"]) > 0.08:
                score = abs(result["edge"]) * result["signal"] * 500

            if score > 0.3:
                all_signals.append(dict(
                    ticker=m["ticker"], price=price,
                    bid_cents=bc_cents, ask_cents=int(ac*100),
                    swarm_yes=result["yes_pct"], edge=result["edge"],
                    signal=result["signal"], rec=result["rec"],
                    score=round(score,2), vol=vol, days=days,
                ))

        all_signals.sort(key=lambda s: s["score"], reverse=True)
        self.stats["total_scans"] += len(all_signals)

        log.info(f"  {'TICKER':48s} {'PRC':>4s} {'S_YES':>5s}  {'EDGE':>5s} {'SIG':>4s} {'REC':>7s} {'VOL':>5s} {'SCORE':>5s}")
        log.info(f"  {'-'*85}")
        for s in all_signals[:12]:
            log.info(f"  {s['ticker']:48s} {s['price']*100:4.0f}c {s['swarm_yes']:5.1%} {s['edge']:+5.1%} {s['signal']:4.2f} {s['rec']:>7s} {s['vol']:5.0f} {s['score']:5.1f}")

        if not all_signals:
            log.info(f"  No signals above threshold. Top markets by volume:")
            by_vol = sorted(mkts, key=lambda m: float(m.get("volume_24h_fp",0) or 0), reverse=True)[:5]
            for m in by_vol:
                bc = float(m.get("yes_bid_dollars",0) or 0)
                ac = float(m.get("yes_ask_dollars",0) or 0)
                p = (bc+ac)/2 * 100
                v = float(m.get("volume_24h_fp",0) or 0)
                log.info(f"    {m.get('ticker','?'):48s} price=${p:.0f}c vol={v:.0f}")

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
                log.warning(f"  Daily loss limit")
                break

            ticker = sig["ticker"]
            side = "yes" if sig["rec"]=="buy_yes" else "no"
            pc = sig["ask_cents"] if side=="yes" else max(1, int(sig["swarm_yes"]*100))
            pc = max(1, min(pc, MAX_SINGLE_PRICE_CENTS))

            log.info(f"  TRADE: {ticker} {side} x1 @{pc}c edge={sig['edge']:+.1%}")
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
                log.error(f"    FAIL: {e}")
        return done

    def run(self):
        log.info(f"STARTING AUTONOMOUS TRADER v14 | API={API}")
        while True:
            try:
                signals = self.scan()
                n = self.execute(signals, max_t=MAX_CONCURRENT_TRADES)
                log.info(f"  Done: {len(signals)} signals, {n} trades. Sleeping 60s.")
                self.save_stats()
                time.sleep(60)
            except KeyboardInterrupt:
                self.conn.close(); self.save_stats(); break
            except Exception as e:
                log.error(f"Crash: {e}"); time.sleep(15)


if __name__ == "__main__":
    Trader().run()
