#!/usr/bin/env python3
"""Research SubAgent v3 — Real-time OPEN market scanning
Does NOT use the broken settled market API (status=settled returns final prices not historical).
Instead: scans OPEN markets, runs swarm analysis, calculates expected PnL.
Works RIGHT NOW with real market data.
"""
import os, sys, time, sqlite3, json, math, random, logging
from datetime import datetime, timezone
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/research_agent.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
API = "https://api.elections.kalshi.com/trade-api/v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RESEARCH] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("research")


class Swarm:
    def __init__(self, n=300):
        self.agents = []
        types = [("quant",0.20,0,0.3,0.8,True),("contrarian",0.15,0,0.6,-0.6,True),
                 ("bull",0.15,0.5,0.7,0.9,False),("bear",0.10,-0.4,0.8,0.7,False),
                 ("degen",0.15,0.3,1.1,0.6,True),("cautious",0.10,-0.1,0.2,0.3,False),
                 ("momentum",0.10,0,1.3,0.95,False),("news",0.05,0.2,0.9,0.7,True)]
        pid = 0
        for ptype,w,bias,vol,sens,cheap in types:
            for _ in range(int(n*w)):
                self.agents.append(dict(ptype=ptype,w=w,bias=bias,vol=vol,sens=sens,cheap=cheap))
                pid += 1
        self.agents = self.agents[:n]

    def predict(self, price, days):
        votes = []
        for a in self.agents:
            ch = price < 0.15
            if a["ptype"] == "quant":
                p = (1-price)*0.25+random.gauss(0,0.05) if(ch and a["cheap"]) else price+random.gauss(0,a["vol"]*0.05)
            elif a["ptype"] == "contrarian":
                p = 0.22+random.gauss(0,0.08) if(ch and a["cheap"]) else 1-price+random.gauss(0,0.06)
            elif a["ptype"] == "degen":
                p = 0.18+a["bias"]*0.2+random.gauss(0,0.1) if(ch and a["cheap"]) else price*(1+a["bias"]*0.5)+random.gauss(0,0.08)
            elif a["ptype"] == "news":
                p = 0.20+random.gauss(0,0.12) if(ch and a["cheap"]) else price+a["bias"]*0.05
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
        total = yes_w+no_w
        yp = yes_w/total if total>0 else 0.5
        return round(yp,4)


def fetch_all_open(limit_per_page=200, max_pages=10):
    """Fetch ALL open markets via pagination, filtering out non-priced markets."""
    all_mkts = []
    cursor = None
    for page in range(max_pages):
        try:
            url = f"{API}/markets?status=open&limit={limit_per_page}"
            if cursor:
                url += f"&cursor={cursor}"
            r = requests.get(url, timeout=20)
            if r.status_code != 200: break
            data = r.json()
            mkts = data.get("markets", [])
            # Filter: only keep markets that have real bid/ask prices
            # Multi-game parlays have bid=0, ask=0 — skip them
            real_mkts = [m for m in mkts 
                        if m.get("yes_bid_dollars") is not None 
                        and m.get("yes_ask_dollars") is not None
                        and float(m.get("yes_bid_dollars", 0) or 0) > 0]
            all_mkts.extend(real_mkts)
            cursor = data.get("cursor")
            if not cursor or len(mkts) < limit_per_page:
                break
            # Log progress
            log.info(f"  Page {page+1}: got {len(mkts)} markets, {len(real_mkts)} with prices (total so far: {len(all_mkts)})")
            time.sleep(0.05)
        except Exception as e:
            log.error(f"  Page {page+1} error: {e}")
            break
    return all_mkts


def get_series():
    try:
        r = requests.get(f"{API}/series?limit=200", timeout=15)
        if r.status_code == 200:
            return r.json().get("series", [])
    except:
        pass
    return []


def main_loop():
    swarm = Swarm(n=300)
    
    log.info("=" * 70)
    log.info("RESEARCH SUBAGENT v3 — Scanning ALL Open Markets")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 70)

    # Get series info for enrichment
    all_series = get_series()
    series_info = {}
    for s in all_series:
        series_info[s.get("ticker", "")] = s.get("title", s.get("category", ""))
    
    log.info(f"Series cache: {len(series_info)} series")

    cycle = 0
    while True:
        cycle += 1
        log.info(f"\n--- Research Cycle {cycle} at {datetime.now(timezone.utc).strftime('%H:%M UTC')} ---")

        t0 = time.time()
        
        # Fetch ALL open markets in one call (with pagination)
        all_open = fetch_all_open()
        t1 = time.time()
        log.info(f"Fetched {len(all_open)} open markets in {t1-t0:.1f}s")

        if not all_open:
            log.warning("No markets fetched. Retrying in 60s...")
            time.sleep(60)
            continue

        # Analyze each market
        proposals = []
        for mkt in all_open:
            bid = mkt.get("yes_bid_dollars")
            ask = mkt.get("yes_ask_dollars")
            if bid is None or ask is None: continue
            
            bid_c = round(float(bid) * 100)
            ask_c = round(float(ask) * 100)
            vol = mkt.get("volume_24h_fp")
            vol = float(vol) if vol else 0
            if vol < 10: continue
            if ask_c >= 98 or bid_c <= 2: continue  # Skip near-resolved
            
            ticker = mkt.get("ticker", "")
            series_t = mkt.get("event_ticker", ticker.split("-")[0] if "-" in ticker else "?")
            
            ct = mkt.get("close_time", "")
            days = None
            if ct:
                try:
                    cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    days = max(0, (cdt - datetime.now(timezone.utc)).total_seconds() / 86400)
                except: pass
            
            price = (bid_c + ask_c) / 200
            swarm_yes = swarm.predict(price, days)

            # Strategy 1: Buy YES when cheap AND swarm agrees
            if ask_c <= 15 and swarm_yes > 0.35:
                cost = ask_c
                win_prob = swarm_yes
                exp_pnl = win_prob * (100 - cost) - (1 - win_prob) * cost - 2
                if exp_pnl > 5:
                    score = (swarm_yes * 100) + (exp_pnl / 3) + min(vol/100, 20)
                    proposals.append(dict(
                        ticker=ticker, side="yes", strategy="near_zero_yes",
                        yes_bid=bid, yes_ask=ask, vol=vol,
                        exp_pnl=round(exp_pnl,1), score=round(score,1),
                        swarm_yes=round(swarm_yes,3),
                        details=f"YES@{ask_c}c Swarm:{swarm_yes:.0%} ExpPnL:{exp_pnl:.1f}c vol={vol:.0f}"
                    ))

            # Strategy 2: Buy NO when YES is expensive (>=85c) AND swarm says <70%
            elif bid_c >= 85 and swarm_yes < 0.70:
                no_cost = 100 - bid_c
                win_prob = 1 - swarm_yes
                exp_pnl = win_prob * (100 - no_cost) - (1 - win_prob) * no_cost - 2
                if exp_pnl > 5:
                    score = ((1-swarm_yes) * 100) + (exp_pnl / 3) + min(vol/100, 20)
                    proposals.append(dict(
                        ticker=ticker, side="no", strategy="overpriced_no",
                        yes_bid=bid, yes_ask=ask, vol=vol,
                        exp_pnl=round(exp_pnl,1), score=round(score,1),
                        swarm_yes=round(swarm_yes,3),
                        details=f"YES@{bid_c}c Swarm:{swarm_yes:.0%} NO_cost={no_cost:.0f}c ExpPnL:{exp_pnl:.1f}c"
                    ))

        t2 = time.time()
        log.info(f"Analyzed {len(all_open)} markets in {t2-t1:.1f}s — found {len(proposals)} proposals")

        # Sort and save top 50
        proposals.sort(key=lambda p: p["score"], reverse=True)
        ts = int(time.time())
        
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DROP TABLE IF EXISTS research_proposals")
            conn.execute("""CREATE TABLE research_proposals (
                ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
                yes_bid REAL, yes_ask REAL, vol REAL, exp_pnl REAL,
                score REAL, swarm_yes REAL, details TEXT
            )""")
            for p in proposals[:50]:
                conn.execute("INSERT INTO research_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, p["ticker"], p["side"], p["strategy"],
                     p["yes_bid"], p["yes_ask"], p["vol"], p["exp_pnl"],
                     p["score"], p["swarm_yes"], p["details"]))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"DB error: {e}")

        # Print top 10
        if proposals:
            log.info(f"\n{'TICKER':45s} {'SIDE':>4s} {'STRAT':>18s} {'EXP':>6s} {'SCR':>5s} {'VOL':>7s}")
            log.info("-" * 90)
            for p in proposals[:10]:
                log.info(f"{p['ticker']:45s} {p['side']:>4s} {p['strategy']:>18s} {p['exp_pnl']:5.1f}c {p['score']:5.1f} {p['vol']:7.0f}")
        else:
            log.info("No proposals found")

        # Print top open markets by volume for transparency
        by_vol = sorted(all_open, key=lambda m: float(m.get("volume_24h_fp",0) or 0), reverse=True)[:5]
        log.info(f"\nTop 5 markets by volume:")
        for m in by_vol[:5]:
            b = m.get("yes_bid_dollars")
            a = m.get("yes_ask_dollars")
            bc = round(float(b)*100) if b else 0
            ac = round(float(a)*100) if a else 0
            v = float(m.get("volume_24h_fp",0) or 0)
            log.info(f"  {m.get('ticker','?'):45s} bid={bc}c ask={ac}c vol={v:.0f}")

        elapsed = time.time() - t0
        log.info(f"\nCycle complete in {elapsed:.1f}s. Sleep 120s.\n")
        time.sleep(120)


if __name__ == "__main__":
    main_loop()
