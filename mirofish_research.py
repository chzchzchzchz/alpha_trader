#!/usr/bin/env python3
"""
MiroFish Research Team — Autonomous Market Intel
Runs as SEPARATE process from the trader. Reads the same Kalshi API,
discovers NEW alpha opportunities the main trader doesn't scan.
Outputs findings to DB that the main trader CAN read.

Layer: research → writes to autonomous.db.mirofish table
"""
import os, sys, time, json, sqlite3, math, random
from datetime import datetime, timezone
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
import backtest_validation_layer as vlayer
DB = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG = os.path.expanduser("~/alpha_trader/logs/mirofish_research.log")

os.makedirs(os.path.dirname(LOG), exist_ok=True)

# Mirror the Swarm from mirofish.py directly
class Agent:
    TYPES = [
        ("quant",0.20,0,0.3,0.8,True),
        ("contrarian",0.15,0,0.6,-0.6,True),
        ("bull",0.15,0.5,0.7,0.9,False),
        ("bear",0.10,-0.4,0.8,0.7,False),
        ("degen",0.15,0.3,1.1,0.6,True),
        ("cautious",0.10,-0.1,0.2,0.3,False),
        ("momentum",0.10,0,1.3,0.95,False),
        ("news",0.05,0.2,0.9,0.7,True),
    ]
    def __init__(self,pid,ptype,w,bias,vol,sens):
        self.pid=pid;self.ptype=ptype;self.w=w;self.bias=bias;self.vol=vol;self.sens=sens
    def vote(self,price,days):
        ch=price<0.15
        if self.ptype=="quant":
            p=(1-price)*0.25+random.gauss(0,0.05) if(ch and self.w>0.15) else price+random.gauss(0,self.vol*0.05)
        elif self.ptype=="contrarian":
            p=0.22+random.gauss(0,0.08) if(ch and self.bias==0) else 1-price+random.gauss(0,0.06)
        elif self.ptype=="degen":
            p=0.18+self.bias*0.5+random.gauss(0,0.1) if(ch and self.sens>0.5) else price*(1+self.bias*0.5)+random.gauss(0,0.08)
        elif self.ptype=="news":
            p=0.20+random.gauss(0,0.12) if(ch and self.sens>0.5) else price+self.bias*0.05
        elif self.ptype=="bull":
            p=price*(1+self.bias*0.15)+random.gauss(0,self.vol*0.06)
        elif self.ptype=="bear":
            p=price*(1-abs(self.bias)*0.1)-abs(self.bias)*0.08+random.gauss(0,0.06)
        elif self.ptype=="momentum":
            p=price+self.sens*0.05+random.gauss(0,self.vol*0.07)
        else:
            p=price+self.bias*0.03+random.gauss(0,self.vol*0.06)
        if days is not None:
            p+=random.gauss(0,0.06*math.exp(-days/20))
        return ("yes" if p>=0.5 else "no",max(0.01,min(0.99,p)))

class Swarm:
    def __init__(self,n=250):
        self.agents=[]
        pid=0
        for ptype,w,bias,vol,sens in Agent.TYPES:
            for _ in range(max(3,int(n*w))):
                self.agents.append(Agent(pid,ptype,w,bias,vol,sens))
                pid+=1
        self.agents=self.agents[:n]
    def predict(self,price,days):
        votes=[a.vote(price,days) for a in self.agents]
        yes_w=sum(self.agents[i].w for i,(v,_) in enumerate(votes) if v=="yes")
        no_w=sum(self.agents[i].w for i,(v,_) in enumerate(votes) if v=="no")
        total=yes_w+no_w
        yp=yes_w/total if total>0 else 0.5
        sig=abs(yp-0.5)*2
        edge=round(yp-price,4)
        if yp>price+0.04: rec="buy_yes"
        elif(1-yp)>(1-price)+0.04: rec="buy_no"
        else: rec="hold"
        return {"yes_pct":round(yp,4),"signal":round(sig,3),"edge":edge,"rec":rec,
                "yv":sum(1 for v,_ in votes if v=="yes"),
                "nv":sum(1 for v,_ in votes if v=="no")}

def discover_new_series():
    """Scan ALL series for markets the main trader doesn't cover."""
    # Main trader covers: KXHIGHNY,KXLOWTPHIL,KXLOWTLAX,KXTEMPCHI,
    # KXTEMPDAL,KXTEMPMIA,KXTEMPNYC,KXTEMPHOUSTON,KXTEMPSEA,
    # KXTEMPDEN,KXTEMPATL,KXTEMPPHX,KXSNOWSTORM,KXWINDCHILL
    
    try:
        r = requests.get("https://api.elections.kalshi.com/trade-api/v2/series?limit=200", timeout=20)
        if r.status_code != 200: return []
        all_series = r.json().get("series", [])
    except: return []
    
    covered = {
        "KXHIGHNY","KXLOWTPHIL","KXLOWTLAX","KXTEMPCHI","KXTEMPDAL",
        "KXTEMPMIA","KXTEMPNYC","KXTEMPHOUSTON","KXTEMPSEA","KXTEMPDEN",
        "KXTEMPATL","KXTEMPPHX","KXSNOWSTORM","KXWINDCHILL"
    }
    
    # Find UNCOVERED series with open markets
    discoveries = []
    for s in all_series:
        ticker = s.get("ticker","")
        if ticker.startswith("KX") and ticker not in covered:
            try:
                mr = requests.get(
                    f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={ticker}&status=open&limit=5",
                    timeout=10
                )
                if mr.status_code == 200:
                    mkts = mr.json().get("markets", [])
                    liquid = [m for m in mkts if float(m.get("volume_24h_fp",0) or 0) > 50]
                    if liquid:
                        discoveries.append({
                            "series": ticker,
                            "category": s.get("category","?"),
                            "title": s.get("title","?"),
                            "open_markets": len(mkts),
                            "liquid_markets": len(liquid),
                            "top_vol": max(float(m.get("volume_24h_fp",0) or 0) for m in mkts),
                        })
                time.sleep(0.03)
            except: pass
    
    discoveries.sort(key=lambda d: d["top_vol"], reverse=True)
    return discoveries[:20]


def analyze_opportunity(market, swarm):
    """Swarm-analysis of a single market."""
    bid = float(market.get("yes_bid_dollars",0) or 0)
    ask = float(market.get("yes_ask_dollars",0) or 0)
    if bid <= 0 and ask <= 0: return None
    price = (bid+ask)/2
    vol = float(market.get("volume_24h_fp",0) or 0)
    if vol < 10: return None
    
    ct = market.get("close_time","")
    days = None
    if ct:
        try:
            cdt = datetime.fromisoformat(ct.replace("Z","+00:00"))
            days = max(0,(cdt-datetime.now(timezone.utc)).total_seconds()/86400)
        except: pass
    
    result = swarm.predict(price, days)
    
    bc = int(bid*100)
    score = 0
    if 1 <= bc <= 15 and result["edge"] > 0.02:
        score = abs(result["edge"]) * result["signal"] * 2000
    elif result["signal"] > 0.4 and abs(result["edge"]) > 0.08:
        score = abs(result["edge"]) * result["signal"] * 500
    
    if score < 1.0: return None
    
    return {
        "ticker": market["ticker"],
        "price": price,
        "vol": vol,
        "days": round(days,1) if days else None,
        "swarm_yes": result["yes_pct"],
        "edge": result["edge"],
        "signal": result["signal"],
        "rec": result["rec"],
        "score": round(score, 1),
        "category": market.get("event_ticker",""),
    }


def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS mirofish_research (
        ts INTEGER, series TEXT, category TEXT, title TEXT,
        open_m INT, liquid_m INT, top_vol REAL, score REAL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mirofish_signals (
        ts INTEGER, ticker TEXT, price REAL, vol REAL, days REAL,
        swarm_yes REAL, edge REAL, signal REAL, rec TEXT, score REAL,
        category TEXT
    )""")
    conn.commit()
    return conn


def main():
    swarm = Swarm(n=300)
    conn = init_db()
    
    print(f"MIROFISH RESEARCH — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    print("=" * 70)
    
    # Phase 1: Discover new series
    print("\n[1/3] Discovering new series...")
    discoveries = discover_new_series()
    print(f"  Found {len(discoveries)} uncovered series with liquid markets")
    
    ts = int(time.time())
    for d in discoveries[:15]:
        conn.execute("INSERT INTO mirofish_research VALUES (?,?,?,?,?,?,?,?)",
            (ts, d["series"], d["category"], d["title"],
             d["open_markets"], d["liquid_markets"], d["top_vol"],
             d["top_vol"] * 10))  # Simple score
        print(f"  {d['series']:30s} cat={d['category']:20s} {d['liquid_markets']} liquid vol={d['top_vol']:.0f}")
    conn.commit()
    
    # Phase 2: Deep-scan top 5 uncovered series for signals  
    if not discoveries:
        print("  Nothing new to report. Sleeping 300s.")
        time.sleep(300)
        return
    
    print(f"\n[2/3] Deep-scanning top 5 uncovered series (with backtest validation)...")
    all_signals = []
    
    for d in discoveries[:5]:
        series = d["series"]
        try:
            mr = requests.get(
                f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={series}&status=open&limit=30",
                timeout=15)
            if mr.status_code != 200: continue
            mkts = mr.json().get("markets", [])
            for m in mkts:
                sig = analyze_opportunity(m, swarm)
                if sig:
                    # ── BACKTEST VALIDATION HOOK ──
                    side = "yes" if sig["rec"] == "buy_yes" else "no"
                    strat = "near_zero_no" if side == "no" else "buy_yes_cheap"
                    pc = sig["ask_cents"] if side == "yes" else sig["bid_cents"]
                    passed, bt_stats, bt_reason = vlayer.validate_signal(
                        sig["ticker"], side, strat, pc)
                    if passed:
                        sig["bt_passed"] = True
                        sig["bt_stats"] = bt_stats
                        sig["bt_reason"] = bt_reason
                        all_signals.append(sig)
                        print(f"  ✅ BT PASS: {sig['ticker']} WR={bt_stats.get('bt_win_rate',0):.0%} PnL={bt_stats.get('bt_total_pnl',0):+.0f}c")
                    else:
                        print(f"  ❌ BT FAIL: {sig['ticker']} — {bt_reason}")
            time.sleep(0.05)
        except: pass
    
    # Sort: BT-passed signals with highest score first
    all_signals.sort(key=lambda s: s.get("score", 0), reverse=True)
    print(f"  Found {len(all_signals)} BT-validated alpha signals")
    
    ts = int(time.time())
    for s in all_signals[:20]:
        conn.execute("INSERT INTO mirofish_signals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, s["ticker"], s["price"], s["vol"],
             s["days"] or 0, s["swarm_yes"], s["edge"], s["signal"],
             s["rec"], s["score"], s["category"]))
        print(f"  {s['ticker']:45s} price={s['price']*100:.0f}c swarm={s['swarm_yes']:.1%} edge={s['edge']:+.1%} score={s['score']:.1f}")
    conn.commit()
    
    # Phase 3: Summary vs main trader
    print(f"\n[3/3] Research summary:")
    total_research = conn.execute("SELECT COUNT(*) FROM mirofish_signals").fetchone()[0]
    top = conn.execute("SELECT * FROM mirofish_signals ORDER BY score DESC LIMIT 5").fetchall()
    print(f"  Total discoveries stored: {total_research}")
    if top:
        print(f"  Top alpha:")
        for t in top:
            print(f"    {t[1]:45s} score={t[9]:.1f} edge={t[6]:+.1%}")
    
    conn.close()
    print(f"\nDone. Next research cycle in 300s.\n")


if __name__ == "__main__":
    # Run once immediately, then every 5 minutes
    while True:
        try:
            main()
            time.sleep(300)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Research error: {e}")
            time.sleep(60)
