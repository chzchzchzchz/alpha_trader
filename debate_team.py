#!/usr/bin/env python3
"""Debate Team Agent — ALWAYS running
Bull and Bear agents argue every signal from the Research subagent.
Only trades with Bull+Bear consensus reach the Executor.

Runs as independent daemon. Reads research_proposals table,
writes to debate_decisions table.
"""
import os, sys, time, sqlite3, json, logging, random
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/debate_team.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DEBATE] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("debate")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS debate_decisions (
        ts INTEGER, 
        ticker TEXT, 
        side TEXT, 
        strategy TEXT,
        bull_score REAL, 
        bull_reasons TEXT,
        bear_score REAL, 
        bear_reasons TEXT,
        consensus_score REAL,
        verdict TEXT
    )""")
    conn.commit()
    return conn


def bull_argument(proposal):
    """Bull agent argues FOR the trade."""
    reasons = []
    score = 50.0  # Start neutral

    bt_wr = proposal.get("bt_wr", 0)
    bt_pnl = proposal.get("bt_pnl", 0)
    bt_n = proposal.get("bt_markets", 0)
    exp_pnl = proposal.get("expected_pnl", 0)
    score_val = proposal.get("proposal_score", 0)
    vol = proposal.get("vol", 0)

    # Historical backtest performance
    if bt_wr >= 0.80 and bt_n >= 10:
        reasons.append(f"STRONG: Historical WR={bt_wr:.0%} over {bt_n} trades is exceptional")
        score += 25
    elif bt_wr >= 0.60 and bt_n >= 10:
        reasons.append(f"GOOD: Historical WR={bt_wr:.0%} with {bt_n} trades shows real edge")
        score += 15
    elif bt_n >= 5:
        reasons.append(f"DECENT: Some historical data ({bt_n} trades, {bt_wr:.0%} WR)")
        score += 5
    else:
        reasons.append(f"WEAK: Only {bt_n} backtest trades — limited historical data")
        score -= 10

    # P&L consistency
    if bt_pnl > 500:
        reasons.append(f"STRONG: Historical PnL=+{bt_pnl:.0f}c is significant")
        score += 20
    elif bt_pnl > 100:
        reasons.append(f"GOOD: Historical PnL=+{bt_pnl:.0f}c shows profitability")
        score += 10
    elif bt_pnl > 0:
        reasons.append(f"MARGINAL: Historical PnL=+{bt_pnl:.0f}c barely positive")
        score += 5
    else:
        reasons.append(f"BAD: Historical PnL={bt_pnl:.0f}c — strategy lost money historically")
        score -= 25

    # Expected value
    if exp_pnl > 10:
        reasons.append(f"STRONG: Expected profit={exp_pnl:.0f}c per trade is high")
        score += 15
    elif exp_pnl > 3:
        reasons.append(f"ACCEPTABLE: Expected profit={exp_pnl:.0f}c justifies the risk")
        score += 5
    else:
        reasons.append(f"WEAK: Expected profit={exp_pnl:.0f}c barely covers spread")
        score -= 10

    # Volume confirms liquidity
    if vol > 1000:
        reasons.append(f"GOOD: Volume={vol:.0f} — liquid market, easy entry/exit")
        score += 10
    elif vol > 100:
        reasons.append(f"ACCEPTABLE: Volume={vol:.0f} — moderate liquidity")
        score += 5
    else:
        reasons.append(f"CONCERN: Volume={vol:.0f} — thin market, slippage risk")
        score -= 5

    return min(max(score, 0), 100), reasons


def bear_argument(proposal):
    """Bear agent argues AGAINST the trade."""
    reasons = []
    score = 50.0  # Start neutral (higher = more bearish)

    bt_wr = proposal.get("bt_wr", 0)
    bt_pnl = proposal.get("bt_pnl", 0)
    bt_n = proposal.get("bt_markets", 0)
    exp_pnl = proposal.get("expected_pnl", 0)
    vol = proposal.get("vol", 0)
    ticker = proposal.get("ticker", "")
    side = proposal.get("side", "")

    # Overfitting risk
    if bt_n < 10:
        reasons.append(f"RISK: Only {bt_n} backtest trades — likely overfitting")
        score += 20
    elif bt_wr >= 0.95 and bt_n < 20:
        reasons.append(f"RISK: {bt_wr:.0%} WR on only {bt_n} trades screams overfitting")
        score += 25

    # Fee drag
    fee_per_trade = 2  # 2c spread cost
    if exp_pnl < fee_per_trade * 2:
        reasons.append(f"RISK: Expected profit ({exp_pnl:.0f}c) barely beats fees ({fee_per_trade}c). No room for error")
        score += 15

    # Market maker trap
    if vol < 50:
        reasons.append(f"RISK: Volume={vol:.0f} — too thin, market maker will eat you")
        score += 20
    elif vol < 200:
        reasons.append(f"CONCERN: Volume={vol:.0f} — market maker might trap you")
        score += 10

    # Binary option risk
    reasons.append(f"CONCERN: Binary options — 100% loss if wrong, capped gain")
    score += 5

    # Specific strategy risks
    strategy = proposal.get("strategy", "")
    if "no" in strategy.lower() and side == "no":
        reasons.append(f"CONCERN: Buying NO — paying {100 - float(proposal.get('yes_bid', 0))*100:.0f}c to win little")
        score += 10

    return min(max(score, 0), 100), reasons


def debate_proposals(conn):
    """Debate all undebated proposals from research."""
    rows = conn.execute("""
        SELECT ts, ticker, side, strategy, yes_bid, yes_ask, vol, 
               bt_markets, bt_wr, bt_pnl, bt_sharpe, expected_pnl, 
               proposal_score, verdict, details
        FROM research_proposals
        WHERE ts > ?
        ORDER BY proposal_score DESC
    """, (int(time.time()) - 3600,)).fetchall()

    # Find already-debated tickers (last 30 min)
    debated = set()
    debated_rows = conn.execute("""
        SELECT ticker FROM debate_decisions WHERE ts > ?
    """, (int(time.time()) - 1800,)).fetchall()
    for (t,) in debated_rows:
        debated.add(t)

    results = 0
    for row in rows:
        proposal = {
            "ts": row[0], "ticker": row[1], "side": row[2], "strategy": row[3],
            "yes_bid": row[4], "yes_ask": row[5], "vol": row[6],
            "bt_markets": row[7], "bt_wr": row[8], "bt_pnl": row[9],
            "bt_sharpe": row[10], "expected_pnl": row[11],
            "proposal_score": row[12], "verdict": row[13], "details": row[14],
        }

        t = proposal["ticker"]
        if t in debated:
            continue
        debated.add(t)

        bull_score, bull_reasons = bull_argument(proposal)
        bear_score, bear_reasons = bear_argument(proposal)

        # Consensus: Both must agree. Final score = bull - bear (higher = better for trade)
        consensus = bull_score - bear_score
        verdict = "PASS" if (consensus > 20 and bull_score > 60 and bear_score < 40) else "FAIL"

        conn.execute(
            "INSERT INTO debate_decisions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), proposal["ticker"], proposal["side"],
             proposal["strategy"], bull_score, " | ".join(bull_reasons),
             bear_score, " | ".join(bear_reasons),
             consensus, verdict))

        symbol = "✅" if verdict == "PASS" else "❌"
        log.info(f"  {symbol} {t} {proposal['side']} | "
                 f"Bull: {bull_score:.0f} Bear: {bear_score:.0f} Consensus: {consensus:.0f} → {verdict}")
        results += 1

    conn.commit()
    return results


def main_loop():
    conn = init_db()
    log.info("=" * 70)
    log.info("DEBATE TEAM AGENT — Bull vs Bear on every signal")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 70)

    cycle = 0
    while True:
        cycle += 1
        log.info(f"\n--- Debate Cycle {cycle} ---")

        try:
            results = debate_proposals(conn)
            if results > 0:
                log.info(f"  Debated {results} proposals this cycle")
            else:
                log.info(f"  No new proposals to debate")
        except Exception as e:
            log.error(f"  Debate error: {e}")

        time.sleep(30)  # Check every 30 seconds


if __name__ == "__main__":
    main_loop()
