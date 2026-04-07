#!/usr/bin/env python3
"""
Research Agent — Autonomous Market Scanner
Scans Kalshi weather markets 24/7, identifies edge opportunities, writes proposals to DB.
Independent process. Never stops.
"""
import os, sys, time, sqlite3, random, math, logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/research.log")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RESEARCH] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("research")


class Swarm:
    """250-agent swarm for prediction consensus."""
    def __init__(self, n=250):
        self.agents = []
        types = [
            ("quant", 0.20, 0, 0.3),
            ("contrarian", 0.15, 0, 0.6),
            ("bull", 0.15, 0.5, 0.7),
            ("bear", 0.10, -0.4, 0.8),
            ("degen", 0.15, 0.3, 1.1),
            ("cautious", 0.10, -0.1, 0.2),
            ("momentum", 0.10, 0, 1.3),
            ("news", 0.05, 0.2, 0.9),
        ]
        pid = 0
        for ptype, w, bias, vol in types:
            for _ in range(max(5, int(n * w))):
                self.agents.append(dict(p=ptype, w=w, b=bias, v=vol))
                pid += 1
        self.agents = self.agents[:n]

    def predict(self, price):
        """Get consensus YES probability."""
        votes = []
        for a in self.agents:
            ch = price < 0.15
            p = a['p']
            b = a['b']
            v = a['v']
            if p == 'quant':
                val = (1 - price) * 0.25 + random.gauss(0, 0.05) if ch else price + random.gauss(0, v * 0.05)
            elif p == 'contrarian':
                val = 0.22 + random.gauss(0, 0.08) if ch else 1 - price + random.gauss(0, 0.06)
            elif p == 'degen':
                val = 0.18 + b * 0.2 + random.gauss(0, 0.1) if ch else price * (1 + b * 0.5) + random.gauss(0, 0.08)
            elif p == 'news':
                val = 0.20 + random.gauss(0, 0.12) if ch else price + b * 0.05
            elif p == 'bull':
                val = price * (1 + b * 0.15) + random.gauss(0, v * 0.06)
            elif p == 'bear':
                val = price * (1 - abs(b) * 0.1) - abs(b) * 0.08 + random.gauss(0, 0.06)
            elif p == 'momentum':
                val = price + v * 0.05 + random.gauss(0, v * 0.07)
            else:
                val = price + b * 0.03 + random.gauss(0, v * 0.06)
            votes.append(("yes" if val >= 0.5 else "no", max(0.01, min(0.99, val))))
        yes_w = sum(self.agents[i]['w'] for i, (v, _) in enumerate(votes) if v == "yes")
        no_w = sum(self.agents[i]['w'] for i, (v, _) in enumerate(votes) if v == "no")
        total = yes_w + no_w
        return yes_w / total if total > 0 else 0.5


def init_db():
    """Ensure tables exist with correct schema."""
    try:
        conn = sqlite3.connect(DB_PATH)
        # Drop and recreate proposals table to avoid schema mismatch
        conn.execute("DROP TABLE IF EXISTS research_proposals")
        conn.execute("""CREATE TABLE research_proposals (
            ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
            price_cents INTEGER, edge REAL, score REAL,
            market_yes_ask REAL, market_yes_bid REAL, vol REAL,
            swarm_yes REAL, details TEXT
        )""")
        # Create positions table to track what we own
        conn.execute("""CREATE TABLE IF NOT EXISTS positions (
            ticker TEXT PRIMARY KEY, count INTEGER, side TEXT, avg_price REAL
        )""")
        conn.commit()
        return conn
    except Exception as e:
        log.error(f"DB init failed: {e}")
        return None


def get_open_markets(client, series_list):
    """Fetch all open markets for weather series."""
    all_mkts = []
    for s in series_list:
        try:
            resp = client.get_markets(series_ticker=s, status="open", limit=50)
            for m in resp.get("markets", []):
                all_mkts.append(m)
        except Exception as e:
            log.debug(f"  Failed to fetch {s}: {e}")
    return all_mkts


def analyze_market(m, swarm):
    """Analyze a single market. Return proposal dict or None."""
    ticker = m.get("ticker", "")
    yes_bid = m.get("yes_bid_dollars")
    yes_ask = m.get("yes_ask_dollars")
    vol = m.get("volume_24h_fp")
    vol = float(vol) if vol else 0

    if vol < 50:
        return None

    if yes_bid is None or yes_ask is None:
        return None

    bid_c = round(float(yes_bid) * 100)
    ask_c = round(float(yes_ask) * 100)

    if bid_c >= 98 or ask_c <= 1:
        return None

    close_str = m.get("close_time", "")
    hours_left = None
    if close_str:
        try:
            ct = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
            hours_left = max(0, (ct - datetime.now(timezone.utc)).total_seconds() / 3600)
        except:
            pass

    price = (bid_c + ask_c) / 200.0
    swarm_yes = swarm.predict(price)
    swarm_no = 1.0 - swarm_yes

    proposals = []
    
    # Filter: Skip already resolved or near-resolved markets
    if bid_c >= 98 or ask_c <= 1:
        return proposals

    # Strategy 1: Cheap YES (1-10c ask) — swarm says edge >5%
    if 1 <= ask_c <= 10:
        cost = ask_c
        if swarm_yes > (cost / 100.0) + 0.05:
            edge = swarm_yes - (cost / 100.0)
            exp_pnl = swarm_yes * (100 - cost) - (1 - swarm_yes) * cost - 2
            if exp_pnl > 3:
                # Max loss = cost, Max win = 100 - cost
                roi = ((100 - cost) / cost - 1) if cost > 0 else 0
                score = exp_pnl * 2 + min(vol / 50, 30) + swarm_yes * 30
                proposals.append(dict(
                    ticker=ticker, side="yes", strategy="cheap_yes",
                    price_cents=cost, edge=round(edge, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"YES@{cost}c SWARM={swarm_yes:.0%} EDGE={edge:+.1%} ROI={roi:.0f}% EXP={exp_pnl:.0f}c VOL={vol:.0f}"
                ))

    # Strategy 2: Cheap NO (YES bid >=90c means NO costs 1-10c)
    if bid_c >= 90:
        no_cost = 100 - bid_c
        if no_cost <= 10 and swarm_no > (no_cost / 100.0) + 0.05:
            edge = swarm_no - (no_cost / 100.0)
            exp_pnl = swarm_no * (100 - no_cost) - (1 - swarm_no) * no_cost - 2
            if exp_pnl > 3:
                roi = ((100 - no_cost) / no_cost - 1) if no_cost > 0 else 0
                score = exp_pnl * 2 + min(vol / 50, 30) + swarm_no * 30
                proposals.append(dict(
                    ticker=ticker, side="no", strategy="cheap_no",
                    price_cents=no_cost, edge=round(edge, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"NO@{no_cost}c SW_NO={swarm_no:.0%} ROI={roi:.0f}% EXP={exp_pnl:.0f}c VOL={vol:.0f}"
                ))

    # Strategy 3: Mid-price value (5-15c YES or 85-95c YES) — swarm disagrees 5%+
    if 5 <= ask_c <= 15:
        if swarm_yes > (ask_c / 100.0) + 0.05:
            cost = ask_c
            edge = swarm_yes - (cost / 100.0)
            exp_pnl = swarm_yes * (100 - cost) - (1 - swarm_yes) * cost - 2
            if exp_pnl > 4:
                score = exp_pnl * 2 + min(vol / 50, 30) + swarm_yes * 20
                proposals.append(dict(
                    ticker=ticker, side="yes", strategy="value_yes",
                    price_cents=cost, edge=round(edge, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"YES@{cost}c SWARM={swarm_yes:.0%} EDGE={edge:+.1%} EXP={exp_pnl:.0f}c VOL={vol:.0f}"
                ))

    if bid_c >= 85:
        no_cost = 100 - bid_c
        if no_cost <= 15 and swarm_no > (no_cost / 100.0) + 0.05:
            edge = swarm_no - (no_cost / 100.0)
            exp_pnl = swarm_no * (100 - no_cost) - (1 - swarm_no) * no_cost - 2
            if exp_pnl > 4:
                score = exp_pnl * 2 + min(vol / 50, 30) + swarm_no * 20
                proposals.append(dict(
                    ticker=ticker, side="no", strategy="value_no",
                    price_cents=no_cost, edge=round(edge, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"NO@{no_cost}c SW_NO={swarm_no:.0%} EDGE={edge:+.1%} EXP={exp_pnl:.0f}c VOL={vol:.0f}"
                ))

    # Strategy 4: HIGH volume (1000+) ANY positive EV — swarm says EVEN 1% edge
    if vol >= 1000:
        # YES: if swarm says even 0.5% more YES than market prices
        if ask_c <= 20 and swarm_yes > (ask_c / 100.0) + 0.005:
            cost = ask_c
            exp_pnl = swarm_yes * (100 - cost) - (1 - swarm_yes) * cost - 2
            if exp_pnl > 1:
                score = exp_pnl * 2 + min(vol / 100, 40) + swarm_yes * 10
                proposals.append(dict(
                    ticker=ticker, side="yes", strategy="volume_yes",
                    price_cents=cost, edge=round(swarm_yes - cost/100, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"YES@{cost}c VOL={vol:.0f} SWARM={swarm_yes:.0%} EXP={exp_pnl:.0f}c"
                ))
        # NO: swarm says EVEN 0.5% more NO than market implies
        no_cost = 100 - bid_c
        if no_cost <= 20 and swarm_no > (no_cost / 100.0) + 0.005:
            exp_pnl = swarm_no * (100 - no_cost) - (1 - swarm_no) * no_cost - 2
            if exp_pnl > 1:
                score = exp_pnl * 2 + min(vol / 100, 40) + swarm_no * 10
                proposals.append(dict(
                    ticker=ticker, side="no", strategy="volume_no",
                    price_cents=no_cost, edge=round(swarm_no - no_cost/100, 3),
                    score=round(score, 1), swarm_yes=round(swarm_yes, 3),
                    market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                    hours_left=round(hours_left, 1) if hours_left else None,
                    details=f"NO@{no_cost}c VOL={vol:.0f} SW_NO={swarm_no:.0%} EXP={exp_pnl:.0f}c"
                ))

    return proposals


def run_cycle(client, swarm, conn, cycle):
    """One research cycle."""
    log.info(f"\n{'=' * 60}")
    log.info(f"CYCLE {cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

    series = ["KXHIGHNY", "KXLOWTPHIL", "KXLOWTLAX", "KXTEMPCHI",
              "KXTEMPDAL", "KXTEMPMIA", "KXTEMPNYC", "KXTEMPHOUSTON"]

    markets = get_open_markets(client, series)
    log.info(f"Fetched {len(markets)} open markets")

    all_proposals = []
    for m in markets:
        results = analyze_market(m, swarm)
        if results:
            all_proposals.extend(results)

    all_proposals.sort(key=lambda p: p["score"], reverse=True)

    # Clear old proposals (>5 min)
    cutoff = int(time.time()) - 300
    conn.execute("DELETE FROM research_proposals WHERE ts < ?", (cutoff,))
    conn.commit()

    # Save new proposals
    ts = int(time.time())
    saved = 0
    for p in all_proposals[:50]:
        conn.execute(
            "INSERT INTO research_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, p["ticker"], p["side"], p["strategy"],
             p["price_cents"], p["edge"], p["score"],
             p.get("market_yes_ask", 0), p.get("market_yes_bid", 0),
             p.get("vol", 0), p["swarm_yes"], p["details"]))
        saved += 1
    conn.commit()

    log.info(f"Analyzed: {len(markets)} | Valid proposals: {len(all_proposals)} | Saved: {saved}")

    if all_proposals:
        for p in all_proposals[:10]:
            log.info(f"  {p['ticker']:45s} {p['side']:>2s} | {p['details']}")
    else:
        log.info("  No proposals — markets are efficient")

    return all_proposals


def main():
    client = KalshiClient(
        key_id='REDACTED_KALSHI_KEY_ID',
        private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
        demo=False
    )
    swarm = Swarm(n=250)
    conn = init_db()
    if not conn:
        log.error("Failed to initialize DB, exiting")
        return

    log.info("=" * 60)
    log.info("RESEARCH AGENT — Autonomous Market Scanner")
    log.info(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 60)

    cycle = 0
    while True:
        try:
            cycle += 1
            run_cycle(client, swarm, conn, cycle)
            time.sleep(60)
        except KeyboardInterrupt:
            log.info("Research agent stopped")
            break
        except Exception as e:
            log.error(f"Cycle crashed: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
