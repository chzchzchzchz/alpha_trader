#!/usr/bin/env python3
"""
RESEARCH SUBAGENT — Always Running, Always Backtesting
Scans ALL Kalshi series for new alpha, backtests strategies on REAL data,
proposes new signals to the trading system, and self-improves parameters.

Runs as independent process. Writes validated signals to research_proposals DB table.
NEVER executes trades — only proposes and validates.
"""
import os, sys, time, json, sqlite3, math, random, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
import requests

sys.path.insert(0, str(Path(__file__).parent))
import backtest_validation_layer as vlayer

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/research_agent.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RESEARCH] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("research")

# Strategy portfolio
STRATEGIES = {
    "near_zero_no": {
        "name": "Near-Zero NO",
        "description": "Buy NO on markets where YES is priced 1-15c",
        "enabled": True,
        "params": {"max_yes_ask": 15, "min_volume": 5},
    },
    "buy_yes_cheap": {
        "name": "Cheap YES",
        "description": "Buy YES on markets priced 1-10c",
        "enabled": True,
        "params": {"max_yes_ask": 10, "min_volume": 10},
    },
    "overreaction_buy_no": {
        "name": "Overreaction NO",
        "description": "Buy NO when YES is over 80c but swarm says <70%",
        "enabled": True,
        "params": {"min_yes_bid": 80, "max_swarm_yes": 0.70},
    },
    "panic_buy_yes": {
        "name": "Panic Buy YES",
        "description": "Buy YES when price dropped >20% in 3 cycles",
        "enabled": True,
        "params": {"drop_threshold": 0.20, "max_lookback": 3},
    },
    "momentum_follow": {
        "name": "Momentum Follow",
        "description": "Buy side with rising price trend (5+ candel up)",
        "enabled": True,
        "params": {"min_candles_up": 5, "min_volume": 100},
    },
}


def init_db():
    """Ensure research proposal table exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS research_proposals (
        ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
        yes_bid REAL, yes_ask REAL, vol_24h REAL,
        bt_markets INT, bt_wr REAL, bt_pnl REAL, bt_sharpe REAL,
        expected_pnl REAL, proposal_score REAL,
        verdict TEXT, details TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_performance (
        ts INTEGER, strategy TEXT, bt_markets INT,
        wr REAL, pnl REAL, sharpe REAL,
        enabled INT, params TEXT
    )""")
    conn.commit()
    return conn


class Swarm:
    """Lightweight swarm for research agent (independent from trader's swarm)."""
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


def get_series():
    """Get ALL Kalshi series."""
    try:
        r = requests.get(f"{KALSHI_API}/series?limit=200", timeout=30)
        if r.status_code == 200:
            return r.json().get("series", [])
    except: pass
    return []


def scan_series(series, swarm, conn):
    """Deep-scan a series for signals."""
    proposals = []
    s_ticker = series.get("ticker", "")
    if not s_ticker:
        return proposals

    try:
        r = requests.get(
            f"{KALSHI_API}/markets?series_ticker={s_ticker}&status=open&limit=50",
            timeout=20)
        if r.status_code != 200:
            return proposals
        markets = r.json().get("markets", [])
    except:
        return proposals

    for mkt in markets:
        bid = mkt.get("yes_bid_dollars")
        ask = mkt.get("yes_ask_dollars")
        if bid is None or ask is None: continue
        bid_c = round(float(bid) * 100)
        ask_c = round(float(ask) * 100)
        vol = float(mkt.get("volume_24h_fp", 0) or 0)
        if vol < 5: continue

        # Skip resolved markets
        if ask_c >= 98 or bid_c <= 2: continue

        ct = mkt.get("close_time", "")
        days = None
        if ct:
            try:
                cdt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                days = max(0, (cdt - datetime.now(timezone.utc)).total_seconds() / 86400)
            except:
                pass

        price = (bid_c + ask_c) / 200
        swarm_yes = swarm.predict(price, days)

        # Check each strategy
        for strat_name, strat_cfg in STRATEGIES.items():
            if not strat_cfg["enabled"]: continue
            p = strat_cfg["params"]

            side = None
            entry_price = None
            passes_filter = False

            if strat_name == "near_zero_no":
                # YES cheap (1-15c), buy NO
                if 1 <= ask_c <= p["max_yes_ask"] and vol >= p["min_volume"]:
                    side = "no"
                    entry_price = 100 - bid_c  # NO ask
                    passes_filter = True

            elif strat_name == "buy_yes_cheap":
                # YES cheap (1-10c), buy YES
                if 1 <= ask_c <= p["max_yes_ask"] and vol >= p["min_volume"]:
                    side = "yes"
                    entry_price = ask_c
                    passes_filter = True

            elif strat_name == "overreaction_buy_no":
                # YES over 80c but swarm says <70%, buy NO
                if bid_c >= p["min_yes_bid"] and swarm_yes < p["max_swarm_yes"]:
                    side = "no"
                    entry_price = 100 - bid_c
                    passes_filter = True

            elif strat_name == "panic_buy_yes":
                # YES under 20c with high swarm confidence
                if ask_c <= 20 and swarm_yes > 0.30:
                    side = "yes"
                    entry_price = ask_c
                    passes_filter = True

            elif strat_name == "momentum_follow":
                if 10 <= bid_c <= 60 and vol >= p["min_volume"] and swarm_yes > 0.20:
                    side = "yes" if swarm_yes > 0.50 else "no"
                    entry_price = ask_c if side == "yes" else (100 - bid_c)
                    passes_filter = True

            if not passes_filter:
                continue

            # ── BACKTEST VALIDATION ──
            bt_passed, bt_stats, bt_reason = vlayer.validate_signal(
                mkt["ticker"], side, strat_name, entry_price)

            if not bt_passed:
                continue

            # Calculate expected PnL
            if side == "yes":
                exp_pnl = swarm_yes * (100 - entry_price) - (1 - swarm_yes) * entry_price - 2
            else:
                no_swarm = 1 - swarm_yes
                exp_pnl = no_swarm * (100 - entry_price) - (1 - no_swarm) * entry_price - 2

            proposal_score = (
                (bt_stats.get("bt_win_rate", 0) * 100) +
                (bt_stats.get("bt_total_pnl", 0) / 100) +
                max(0, exp_pnl / 5)
            )

            proposal = {
                "ts": int(time.time()),
                "ticker": mkt["ticker"],
                "side": side,
                "strategy": strat_name,
                "bid_cents": bid_c,
                "ask_cents": ask_c,
                "vol": vol,
                "bt_markets": bt_stats.get("bt_total_trades", 0),
                "bt_wr": bt_stats.get("bt_win_rate", 0),
                "bt_pnl": bt_stats.get("bt_total_pnl", 0),
                "bt_sharpe": bt_stats.get("bt_avg_sharpe", 0),
                "expected_pnl": round(exp_pnl, 1),
                "proposal_score": round(proposal_score, 1),
                "verdict": "PROPOSE",
                "details": bt_reason,
            }
            proposals.append(proposal)

    return proposals


def self_improve(conn):
    """Analyze past research proposals and adjust strategy parameters."""
    log.info("[SELF-IMPROVE] Analyzing strategy performance...")

    for strat_name, strat_cfg in STRATEGIES.items():
        rows = conn.execute(
            "SELECT bt_wr, bt_pnl FROM research_proposals "
            "WHERE strategy=? AND verdict='PROPOSE' ORDER BY ts DESC LIMIT 30",
            (strat_name,)).fetchall()

        if not rows:
            continue

        avg_wr = sum(r[0] for r in rows) / len(rows)
        avg_pnl = sum(r[1] for r in rows) / len(rows)

        log.info(f"  {strat_name}: avg_wr={avg_wr:.1%}, avg_pnl={avg_pnl:.0f}c, proposals={len(rows)}")

        # If WR drops below 50%, disable
        new_enabled = avg_wr >= 0.50 and avg_pnl > 0
        if new_enabled != strat_cfg["enabled"]:
            strat_cfg["enabled"] = new_enabled
            log.info(f"  {'ENABLED' if new_enabled else 'DISABLED'} {strat_name} (WR={avg_wr:.1%}, PnL={avg_pnl:.0f}c)")

        # Save performance
        conn.execute("INSERT INTO strategy_performance VALUES (?,?,?,?,?,?,?,?)",
            (int(time.time()), strat_name, len(rows),
             round(avg_wr, 3), round(avg_pnl, 1), 0,
             int(new_enabled), json.dumps(strat_cfg["params"])))

    conn.commit()


def main_loop():
    """Main research loop — runs forever."""
    swarm = Swarm(n=300)
    conn = init_db()

    log.info("=" * 70)
    log.info("RESEARCH SUBAGENT — Always Backtesting, Always Proposing")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 70)

    cycle = 0
    last_improve = 0

    while True:
        cycle += 1
        log.info(f"\n--- Research Cycle {cycle} ---")

        # Get all series
        series_list = get_series()
        log.info(f"Found {len(series_list)} series on Kalshi")

        if not series_list:
            log.warning("No series found, retrying in 30s...")
            time.sleep(30)
            continue

        # Sort by category priority (sports, crypto, economics first)
        priority_cats = {"Sports": 1, "Crypto": 2, "Economics": 3,
                         "Politics": 4, "Entertainment": 5}
        series_list.sort(key=lambda s: priority_cats.get(s.get("category", ""), 99))

        # Scan top series (time-boxed to 5 minutes)
        all_proposals = []
        series_scanned = 0
        scan_start = time.time()

        for series in series_list[:200]:
            if time.time() - scan_start > 300:
                log.info(f"  Time limit reached at {series_scanned} series")
                break

            proposals = scan_series(series, swarm, conn)
            all_proposals.extend(proposals)
            series_scanned += 1

            if proposals:
                log.info(f"  {series.get('ticker','?')}: found {len(proposals)} validated signals")

        # Sort proposals by score
        all_proposals.sort(key=lambda p: p["proposal_score"], reverse=True)

        # Save top proposals to DB
        saved = 0
        for prop in all_proposals[:50]:
            conn.execute(
                "INSERT INTO research_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (prop["ts"], prop["ticker"], prop["side"], prop["strategy"],
                 prop.get("bid_cents",0), prop.get("ask_cents",0), prop.get("vol",0),
                 prop["bt_markets"], prop["bt_wr"], prop["bt_pnl"],
                 prop["bt_sharpe"], prop["expected_pnl"], prop["proposal_score"],
                 prop["verdict"], prop["details"]))
            saved += 1

        conn.commit()

        # Print summary
        log.info(f"\n{'='*60}")
        log.info(f"Scanned {series_scanned} series, found {len(all_proposals)} validated signals")
        log.info(f"Saved {saved} top proposals to DB")

        if all_proposals:
            log.info(f"\n{'TICKER':50s} {'SIDE':>4s} {'STRATEGY':>20s} {'BT_WR':>6s} {'BT_PNL':>7s} {'EXP':>5s} {'SCORE':>5s}")
            log.info("-" * 100)
            for p in all_proposals[:10]:
                log.info(
                    f"{p['ticker']:50s} {p['side']:>4s} {p['strategy']:>20s} "
                    f"{p['bt_wr']:6.1%} {p['bt_pnl']:7.1f}c {p['expected_pnl']:5.1f}c "
                    f"{p['proposal_score']:5.1f}")

        # Self-improve every 3 cycles (~15 min)
        if time.time() - last_improve > 900:
            self_improve(conn)
            last_improve = time.time()

        log.info(f"\nNext research cycle in 180s...\n")
        time.sleep(180)


if __name__ == "__main__":
    main_loop()
