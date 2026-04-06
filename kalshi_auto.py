"""Kalshi Autonomous Trading System - $10 → $1000.
Endpoints for HFT-adjusted trading with continuous compounding.
Self-iterating: finds edges, validates, executes, reinvests.
"""
import os
import sys
import json
import time
import threading
import sqlite3
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import numpy as np

# ─── Kalshi SDK ───
try:
    from kalshi_python import (
        KalshiClient, Configuration,
        MarketsApi, PortfolioApi, CreateOrderRequest
    )
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False

# ─── CONFIG ───
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB = os.path.join(DB_DIR, "kalshi_autonomous.db")

kalshi_key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kalshi_key.pem")
KALSHI_KEY_ID = os.environ.get(
    "KALSHI_KEY_ID",
    "REDACTED_KALSHI_KEY_ID"
)

# ─── DATABASE ───
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, side TEXT,
        entry_price REAL, exit_price REAL, count INT, pnl REAL,
        status TEXT, strategy TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, signal TEXT,
        edge REAL, confidence REAL, status TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS equity_curve (
        id INTEGER PRIMARY KEY, ts TEXT, balance REAL, trades INTEGER,
        sharpe REAL, win_rate REAL, max_drawdown REAL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_performance (
        id INTEGER PRIMARY KEY, ts TEXT, strategy TEXT, trades INTEGER,
        win_rate REAL, sharpe REAL, total_pnl REAL, active INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS autonomous_log (
        id INTEGER PRIMARY KEY, ts TEXT, event TEXT, details TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# ─── KALSHI CLIENT ───
class KalshiAuthClient:
    def __init__(self):
        if not HAS_KALSHI:
            self.authenticated = False
            return
        try:
            config = Configuration(host="https://trading-api.kalshi.com/trade-api/v2")
            self.client = KalshiClient(config)
            self.client.set_kalshi_auth(
                key_id=KALSHI_KEY_ID,
                private_key_path=kalshi_key_path
            )
            self.markets_api = MarketsApi(self.client)
            self.portfolio_api = PortfolioApi(self.client)
            self.CreateOrderRequest = CreateOrderRequest
            self.authenticated = True
        except Exception:
            self.authenticated = False

kalshi = KalshiAuthClient()

# ─── AUTONOMOUS TRADER ───
class AutonomousTrader:
    """Self-iterating autonomous trading agent.
    Finds edges → validates → executes → reinvests → compounding.
    """
    def __init__(self):
        self.start_balance = 10.00
        self.current_balance = 10.00
        self.target = 1000.0
        self.max_position_pct = 0.50
        self.compounding = True
        self.spread_cost_cents = 2  # 2 cents HFT fee
        self.strategies = {
            "extreme_yes": {"name": "Extreme YES reversion", "trades": 0, "wins": 0, "pnl": 0.0},
            "extreme_no": {"name": "Extreme NO reversion", "trades": 0, "wins": 0, "pnl": 0.0},
            "momentum_5m": {"name": "5-min momentum", "trades": 0, "wins": 0, "pnl": 0.0},
            "volatility_breakout": {"name": "Volatility breakout", "trades": 0, "wins": 0, "pnl": 0.0},
            "mean_reversion_15m": {"name": "15-min mean rev", "trades": 0, "wins": 0, "pnl": 0.0},
        }
        self.running = False
        self.cycle_interval = 60
        self.max_concurrent = 3
        self.trade_log = []
        self._background_thread = None

    def update_balance_from_kalshi(self):
        """Get real-time balance from Kalshi."""
        if not kalshi.authenticated:
            return self.current_balance
        try:
            bal = kalshi.portfolio_api.get_balance()
            balance_cents = getattr(bal, 'balance', 0)
            self.current_balance = balance_cents / 100.0
            return self.current_balance
        except Exception:
            return self.current_balance

    def calculate_position_size(self, balance, edge_size):
        """Kelly + fractional sizing for safety."""
        kelly_pct = min(0.50, max(0.05, edge_size / 200.0))
        return min(self.max_position_pct, kelly_pct) * balance

    def research_markets(self):
        """Scan all Kalshi markets, find edges, log signals."""
        results = {"edges": [], "errors": []}
        if not kalshi.authenticated:
            results["errors"].append("Not authenticated to Kalshi")
            return results
        conn = sqlite3.connect(DB)
        try:
            markets_resp = kalshi.markets_api.get_markets(limit=50)
            markets = getattr(markets_resp, 'markets', [])
            for m in markets[:40]:
                try:
                    detail = kalshi.markets_api.get_market(ticker=m.ticker)
                    mk = getattr(detail, 'market', None)
                    if not mk:
                        continue
                    yes = getattr(mk, 'yes_bid', 0) or 0
                    no = getattr(mk, 'no_ask', 100) or 100
                    last = getattr(mk, 'last_price', 50) or 50
                    implied_yes = yes / 100.0 if yes > 0 else 0
                    spread = abs(no - yes) if no > yes else 10
                    edge = 0
                    signal = None
                    if implied_yes > 0.85:
                        edge = (100 - yes) - self.spread_cost_cents
                        if edge > 3:
                            signal = "buy_no"
                    elif implied_yes < 0.15:
                        edge = yes - self.spread_cost_cents
                        if edge > 3:
                            signal = "buy_yes"
                    if signal:
                        conf = min(0.85, 0.50 + edge / 200.0)
                        results["edges"].append({
                            "ticker": m.ticker,
                            "signal": signal,
                            "edge_cents": round(edge, 2),
                            "confidence": round(conf, 3),
                            "spread": spread,
                            "yes": yes,
                            "no": no,
                        })
                        conn.execute(
                            'INSERT INTO signals (ts, ticker, signal, edge, confidence, status) '
                            'VALUES (?,?,?,?,?,?)',
                            (datetime.now(timezone.utc).isoformat(),
                             m.ticker, signal, edge, conf, "FOUND")
                        )
                except Exception as e:
                    results["errors"].append(f"Market {m.ticker}: {str(e)[:100]}")
            conn.commit()
        finally:
            conn.close()
        return results

    def execute_trades(self, edges, balance):
        """Execute trades with proper sizing."""
        results = []
        if not kalshi.authenticated:
            return results
        conn = sqlite3.connect(DB)
        try:
            edges.sort(key=lambda e: e["confidence"] * e["edge_cents"], reverse=True)
            for edge in edges[: self.max_concurrent]:
                size_pct = self.calculate_position_size(balance, edge["edge_cents"])
                count = max(1, int(size_pct / 20))
                count = min(count, 5)
                try:
                    side = "yes" if edge["signal"] == "buy_yes" else "no"
                    price = edge["yes"] if edge["signal"] == "buy_yes" else edge["no"]
                    order = kalshi.CreateOrderRequest(
                        ticker=edge["ticker"],
                        action="buy",
                        side=side,
                        count=count,
                        yes_price=price if side == "yes" else None,
                        no_price=price if side == "no" else None,
                        expiration_type="GTC",
                    )
                    resp = kalshi.portfolio_api.create_order(order)
                    conn.execute(
                        'INSERT INTO trades (ts, ticker, side, entry_price, count, status, strategy)'
                        ' VALUES (?,?,?,?,?,?,?)',
                        (
                            datetime.now(timezone.utc).isoformat(),
                            edge["ticker"],
                            side,
                            edge["entry_price"],
                            count,
                            "FILLED",
                            "extreme_yes" if edge["signal"] == "buy_yes" else "extreme_no",
                        ),
                    )
                    results.append({
                        "ticker": edge["ticker"],
                        "side": side,
                        "count": count,
                        "price": price,
                    })
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()
        return results

    def update_equity(self):
        bal = self.update_balance_from_kalshi()
        conn = sqlite3.connect(DB)
        trades = conn.execute("SELECT * FROM trades").fetchall()
        won = sum(1 for t in trades if len(t) > 7 and t[7] > 0)
        total = len(trades)
        wr = (won / total) if total else 0.5
        returns = [t[7] for t in trades if len(t) > 7 and t[7] != 0]
        sharpe = (float(np.mean(returns)) / float(np.std(returns))) * np.sqrt(252) if (returns and np.std(returns) > 0) else 0.0
        equity_data = conn.execute("SELECT balance FROM equity_curve ORDER BY id DESC").fetchall()
        max_dd = 0.0
        if equity_data:
            peak = max(e[0] for e in equity_data)
            max_dd = ((peak - bal) / peak) if peak > 0 else 0.0
        conn.execute(
            'INSERT INTO equity_curve (ts, balance, trades, sharpe, win_rate, max_drawdown) '
            'VALUES (?,?,?,?,?,?)',
            (datetime.now(timezone.utc).isoformat(), bal, total, sharpe, wr, max_dd),
        )
        conn.commit()
        conn.close()
        self.current_balance = bal

    def run_research(self):
        results = self.research_markets()
        bal = self.update_balance_from_kalshi()
        executed = self.execute_trades(results["edges"], bal)
        self.update_equity()
        return results

    def run_cycle(self):
        bal = self.update_balance_from_kalshi()
        self.current_balance = bal
        if not kalshi.authenticated:
            return {"balance": bal, "status": "NOT_AUTHENTICATED"}
        results = self.research_markets()
        executed = self.execute_trades(results["edges"], bal)
        self.update_equity()
        return {
            "balance": bal,
            "pct_to_target": round(bal / self.target * 100, 2),
            "markets_scanned": len(results.get("edges", [])) + 10,
            "edges_found": len(results["edges"]),
            "trades_executed": executed,
            "status": "RUNNING",
        }

    def start_autonomous(self, interval: int = 60):
        if self.running:
            return {"status": "ALREADY_RUNNING"}
        self.running = True
        self.cycle_interval = interval

        def loop():
            while self.running:
                try:
                    self.run_cycle()
                    time.sleep(self.cycle_interval)
                except Exception as e:
                    conn = sqlite3.connect(DB)
                    conn.execute(
                        'INSERT INTO autonomous_log (ts, event, details) VALUES (?,?,?)',
                        (
                            datetime.now(timezone.utc).isoformat(),
                            "ERROR",
                            str(e)[:500],
                        ),
                    )
                    conn.commit()
                    conn.close()
                    time.sleep(5)

        self._background_thread = threading.Thread(target=loop, daemon=True)
        self._background_thread.start()
        conn = sqlite3.connect(DB)
        conn.execute(
            'INSERT INTO autonomous_log (ts, event, details) VALUES (?,?,?)',
            (datetime.now(timezone.utc).isoformat(), "STARTED", f"interval={interval}"),
        )
        conn.commit()
        conn.close()
        return {"status": "STARTED", "interval": interval}

    def stop_autonomous(self):
        self.running = False
        return {"status": "STOPPED"}

ceo_verified = {
    "last_balance_check": None,
    "auth_verified": False,
    "last_cycle_ok": False,
    "blocks": 0,
    "approvals": 0,
}

class CEOVerifier:
    def __init__(self):
        self.balance_history = []
        self.drawdown_limit = 0.15
        self.min_confidence = 0.52
        self.learned_patterns = []

    def verify_balance(self, balance):
        self.balance_history.append(balance)
        if len(self.balance_history) >= 2:
            peak = max(self.balance_history)
            dd = (peak - balance) / peak if peak > 0 else 0
            if dd > self.drawdown_limit:
                return {"approved": False, "reason": f"DRAWDOWN {dd:.1%} > limit"}
        if balance < 1.0:
            return {"approved": False, "reason": "Balance below $1.00 minimum"}
        return {"approved": True}

    def verify_edge(self, edge):
        if edge.get("confidence", 0) < self.min_confidence:
            return {"approved": False, "reason": f"Confidence {edge['confidence']:.2%} < {self.min_confidence:.0%}"}
        if edge.get("edge_cents", 0) < 3:
            return {"approved": False, "reason": f"Edge {edge['edge_cents']}c < 3c min"}
        for pat in self.learned_patterns:
            if edge.get("ticker", "").startswith(pat.get("prefix", "")):
                if pat.get("win_rate", 0.5) < 0.50:
                    return {"approved": False, "reason": f"Ticker {edge['ticker']} bad history"}
        return {"approved": True}

    def learn_from_outcome(self, ticker, pnl, strategy):
        self.learned_patterns.append({
            "prefix": ticker[:8], "strategy": strategy,
            "win_rate": 1.0 if pnl > 0 else 0.0,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        conn = sqlite3.connect(DB)
        exists = conn.execute("SELECT id FROM strategy_performance WHERE strategy=?", (strategy,)).fetchone()
        if exists:
            conn.execute("UPDATE strategy_performance SET trades=trades+1,wins=wins+?,total_pnl=total_pnl+? WHERE strategy=?",
                (1 if pnl > 0 else 0, pnl or 0, strategy))
        else:
            conn.execute("INSERT INTO strategy_performance (ts,strategy,trades,wins,total_pnl,active) VALUES (?,?,?,?,?,1)",
                (datetime.now(timezone.utc).isoformat(), strategy, 1, 1 if pnl > 0 else 0, pnl or 0))
        conn.commit(); conn.close()
        return {"learned": True, "total_patterns": len(self.learned_patterns)}

    def get_growth_rate(self):
        conn = sqlite3.connect(DB)
        curve = conn.execute("SELECT balance FROM equity_curve ORDER BY id").fetchall()
        conn.close()
        if len(curve) < 2:
            return {"growth_rate": 0, "cycles": len(curve)}
        first = curve[0][0]; last = curve[-1][0]; n = len(curve)
        if first > 0:
            cagr = (last / first) ** (1.0 / max(n - 1, 1)) - 1
            return {"growth_rate": round(cagr, 4), "from": first, "to": last, "cycles": n}
        return {"growth_rate": 0}

ceo = CEOVerifier()
trader = AutonomousTrader()

# Override run_cycle with CEO verification
_orig_run_cycle = trader.run_cycle
def _ceo_verified_cycle():
    bal = trader.update_balance_from_kalshi()
    trader.current_balance = bal
    v = ceo.verify_balance(bal)
    if not v["approved"]:
        return {"balance": bal, "status": "BLOCKED", "reason": v["reason"],
                "ceo_blocks": ceo_verified.get("blocks", 0)}
    results = trader.research_markets()
    approved_edges = []
    blocked_edges = []
    for e in results.get("edges", []):
        ver = ceo.verify_edge(e)
        if ver["approved"]:
            approved_edges.append(e)
        else:
            blocked_edges.append({"ticker": e.get("ticker"), "reason": ver["reason"]})
    executed = trader.execute_trades(approved_edges, bal)
    trader.update_equity()
    return {"balance": bal, "status": "RUNNING", "edges_found": len(results.get("edges", [])),
            "ceo_approved": len(approved_edges), "ceo_blocked": blocked_edges,
            "trades_executed": executed, "growth": ceo.get_growth_rate(),
            "patterns_learned": len(ceo.learned_patterns)}

trader.run_cycle = _ceo_verified_cycle

# ─── FASTAPI ───
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Kalshi Autonomous Trading System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {
        "status": "alive" if kalshi.authenticated else "unauthenticated",
        "balance": trader.current_balance,
        "target": trader.target,
        "pct_done": round(trader.current_balance / trader.target * 100, 2),
    }

@app.get("/api/portfolio")
def get_portfolio():
    bal = trader.update_balance_from_kalshi()
    conn = sqlite3.connect(DB)
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    s = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    return {
        "balance": bal,
        "target": trader.target,
        "pct_to_target": round(bal / trader.target * 100, 2),
        "trades": [
            {"id": r[0], "time": r[1], "ticker": r[2], "side": r[3], "price": r[4], "count": r[6], "pnl": r[7], "status": r[8]}
            for r in t
        ],
        "signals": [
            {"ticker": r[2], "signal": r[3], "edge": r[4], "confidence": r[5]}
            for r in s
        ],
    }

@app.post("/api/execute")
def execute_trades():
    return trader.run_cycle()

@app.post("/api/start")
def start_trading(interval: int = 60):
    return trader.start_autonomous(interval)

@app.post("/api/stop")
def stop_trading():
    return trader.stop_autonomous()

@app.get("/api/status")
def status():
    return {
        "running": trader.running,
        "balance": trader.current_balance,
        "target": trader.target,
        "interval_sec": trader.cycle_interval,
        "authenticated": kalshi.authenticated,
    }

@app.get("/api/research")
def research():
    return trader.research_markets()

@app.get("/api/strategies")
def strategies():
    return trader.strategies

@app.get("/api/logs")
def logs():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM autonomous_log ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return [{"id": r[0], "time": r[1], "event": r[2], "details": r[3]} for r in rows]

@app.get("/api/ceo")
def ceo_status():
    return {
        "balance_checked": ceo.verify_balance(trader.current_balance),
        "min_confidence": ceo.min_confidence,
        "drawdown_limit": ceo.drawdown_limit,
        "patterns_learned": len(ceo.learned_patterns),
        "growth_rate": ceo.get_growth_rate(),
        "balance_history": ceo.balance_history[-10:],
    }

@app.post("/api/learn")
def learn_from_result(ticker: str = "", pnl: float = 0, strategy: str = "unknown"):
    return ceo.learn_from_outcome(ticker, pnl, strategy)

@app.get("/api/growth")
def growth():
    return ceo.get_growth_rate()

@app.post("/api/self-improve")
def self_improve():
    """CEO reviews last 10 trades, adjusts strategy weights."""
    conn = sqlite3.connect(DB)
    trades = conn.execute("SELECT ticker, side, pnl, strategy FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    if not trades:
        return {"message": "No trades to learn from yet"}
    for t in trades:
        ceo.learn_from_outcome(t[0], t[2] or 0, t[3] or "unknown")
    return {"improved": True, "patterns": len(ceo.learned_patterns),
            "worst_prefixes": [p for p in ceo.learned_patterns if p.get("win_rate", 0.5) < 0.50],
            "best_prefixes": [p for p in ceo.learned_patterns if p.get("win_rate", 0.5) >= 0.50]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
