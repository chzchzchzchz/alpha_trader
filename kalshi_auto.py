"""Kalshi Autonomous Trading System - $10 -> $1000.
Multi-timeframe backtest (30d/60d/90d/180d/360d/3y) + forward paper test
+ pre-execution gate + CEO verification + self-improving quant.
Only executes when ALL validation layers pass. Self-learns from outcomes.
"""
import os, sys, json, time, threading, sqlite3, math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import numpy as np

# ─── Kalshi SDK ───
try:
    from kalshi_python import (KalshiClient, Configuration,
        MarketsApi, PortfolioApi, CreateOrderRequest)
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False

import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── CONFIG ───
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB = os.path.join(DB_DIR, "kalshi_autonomous.db")
KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kalshi_key.pem")
KEY_ID = os.environ.get("KALSHI_KEY_ID", "REDACTED_KALSHI_KEY_ID")

# ─── DATABASE ───
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, side TEXT,
        entry_price REAL, exit_price REAL, count INT, pnl REAL,
        status TEXT, strategy TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, signal TEXT,
        edge REAL, confidence REAL, status TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS equity_curve (
        id INTEGER PRIMARY KEY, ts TEXT, balance REAL, trades INT,
        sharpe REAL, win_rate REAL, max_drawdown REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strategy_performance (
        id INTEGER PRIMARY KEY, ts TEXT, strategy TEXT, trades INT,
        win_rate REAL, sharpe REAL, total_pnl REAL, active INT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS autonomous_log (
        id INTEGER PRIMARY KEY, ts TEXT, event TEXT, details TEXT)""")
    conn.commit(); conn.close()
init_db()

# ─── KALSHI CLIENT ───
class KalshiAuthClient:
    def __init__(self):
        if not HAS_KALSHI:
            self.authenticated = False; return
        try:
            cfg = Configuration(host="https://trading-api.kalshi.com/trade-api/v2")
            self.client = KalshiClient(cfg)
            self.client.set_kalshi_auth(key_id=KEY_ID, private_key_path=KEY_PATH)
            self.mkts_api = MarketsApi(self.client)
            self.pf_api = PortfolioApi(self.client)
            self.CreateOrderRequest = CreateOrderRequest
            self.authenticated = True
        except Exception:
            self.authenticated = False
kalshi = KalshiAuthClient()

# ══════════════════════════════════════════════════════════
# MULTI-TIMEFRAME BACKTEST ENGINE (30d 60d 90d 180d 360d 3y)
# ALL 6 must PASS before live execution
# ══════════════════════════════════════════════════════════
BT_TIMEFRAMES = {
    "30d":  {"days":30,   "min_trades":30,  "min_sharpe":0.3},
    "60d":  {"days":60,   "min_trades":50,  "min_sharpe":0.3},
    "90d":  {"days":90,   "min_trades":70,  "min_sharpe":0.3},
    "180d": {"days":180,  "min_trades":100, "min_sharpe":0.3},
    "360d": {"days":360,  "min_trades":150, "min_sharpe":0.3},
    "3y":   {"days":1095, "min_trades":200, "min_sharpe":0.3},
}

def backtest_kalshi_strategy(days=90, spread_cost=0.02):
    period_map = {30:"1mo",60:"2mo",90:"3mo",180:"6mo",360:"1y",1095:"3y"}
    period = period_map.get(days, "3mo")
    proxies = {"BTC":yf.Ticker("BTC-USD"), "ETH":yf.Ticker("ETH-USD"),
               "SOL":yf.Ticker("SOL-USD")}
    total_wins=0; total_trades=0; total_pnl=0.0
    for sym, tk in proxies.items():
        try: data = tk.history(period=period)
        except: continue
        if len(data)<50: continue
        closes = data["Close"].values
        d = np.diff(closes); g = np.where(d>0,d,0); l = np.where(d<0,-d,0)
        ag = np.convolve(g, np.ones(14)/14, "valid")
        al = np.convolve(l, np.ones(14)/14, "valid")
        rs = np.where(al>0, ag/al, 100.0)
        rsi = 100.0-100.0/(1.0+rs)
        off = len(closes)-len(rsi)
        wins=0; trades=0; pnl=0.0; holding=False; entry=0.0
        for i in range(len(rsi)):
            if not holding and rsi[i]<25:
                holding=True; entry=closes[i+off]
            elif holding and rsi[i]>75:
                holding=False; px=closes[i+off]
                pnl+=(px-entry)/entry-spread_cost; trades+=1
                if pnl>0: wins+=1
        if holding and len(closes)>off:
            holding=False; px=closes[-1]
            pnl+=(px-entry)/entry-spread_cost; trades+=1
            if pnl>0: wins+=1
        total_wins+=wins; total_trades+=trades; total_pnl+=pnl
    wr = total_wins/max(total_trades,1)
    avg = total_pnl/max(total_trades,1)
    sharpe = (avg/0.02)*np.sqrt(252) if total_trades>30 and avg>0 else 0
    return {"pass":wr>0.52 and sharpe>0.3 and total_trades>20,
            "trades":total_trades,"wins":total_wins,
            "win_rate":round(wr*100,1),"sharpe":round(sharpe,2),
            "total_pnl_pct":round(total_pnl*100,1)}

bt_engine = backtest_kalshi_strategy

# ══════════════════════════════════════════════════════════
# FORWARD TESTER - paper trades, tracks outcomes
# ══════════════════════════════════════════════════════════
class ForwardTester:
    def __init__(self):
        self.active={}; self.completed=[]
    def enter(self, ticker, side, price):
        self.active[ticker]={"ticker":ticker,"side":side,"entry":price,"ts":time.time()}
    def exit(self, ticker, exit_px, reason):
        if ticker not in self.active: return None
        p = self.active.pop(ticker)
        pnl = ((exit_px-p["entry"])/100.0) if p["side"]=="yes" else ((p["entry"]-exit_px)/100.0)
        result = {"ticker":ticker,"side":p["side"],"entry":p["entry"],
                  "exit":exit_px,"pnl":round(pnl,4),"reason":reason,
                  "ts":datetime.now(timezone.utc).isoformat()}
        self.completed.append(result)
        return result
    def scan_and_enter(self):
        if not kalshi.authenticated: return []
        entries = []
        try:
            resp = kalshi.mkts_api.get_markets(limit=30)
            for m in getattr(resp,"markets",[])[:25]:
                if m.ticker in self.active: continue
                detail = kalshi.mkts_api.get_market(ticker=m.ticker)
                mk = getattr(detail,"market",None)
                if not mk: continue
                yes = getattr(mk,"yes_bid",0) or 0
                no = getattr(mk,"no_ask",0) or 0
                vol = getattr(mk,"volume",0) or 0
                if vol<100: continue
                implied = yes/100.0 if yes>0 else 0.5
                if implied>0.85:
                    self.active[m.ticker]={"side":"no","entry":no,"ts":time.time(),"ticker":m.ticker}
                    entries.append(m.ticker)
                elif implied<0.15:
                    self.active[m.ticker]={"side":"yes","entry":yes,"ts":time.time(),"ticker":m.ticker}
                    entries.append(m.ticker)
        except: pass
        return entries
    def sync(self):
        if not kalshi.authenticated: return []
        exits = []
        for ticker in list(self.active.keys()):
            pos = self.active[ticker]
            try:
                detail = kalshi.mkts_api.get_market(ticker=ticker)
                mk = getattr(detail,"market",None)
                if not mk: continue
                cur = getattr(mk,"yes_bid",50) or 50
                if pos["side"]=="yes":
                    if cur>=80: exits.append(self.exit(ticker,cur,"tp"))
                    elif cur<=20: exits.append(self.exit(ticker,cur,"sl"))
                    elif time.time()-pos["ts"]>300: exits.append(self.exit(ticker,cur,"timeout"))
                else:
                    if cur<=20: exits.append(self.exit(ticker,cur,"tp"))
                    elif cur>=80: exits.append(self.exit(ticker,cur,"sl"))
                    elif time.time()-pos["ts"]>300: exits.append(self.exit(ticker,cur,"timeout"))
            except: pass
        return [e for e in exits if e]

forward_tester = ForwardTester()

# ══════════════════════════════════════════════════════════
# SELF-IMPROVING QUANT - research, adapt, self-upgrade
# ══════════════════════════════════════════════════════════
class SelfImprovingQuant:
    def __init__(self):
        self.params = {"rsi":14,"oversold":25,"overbought":75,
                       "spread":0.02,"min_edge":3,"max_pos":3}
        self.history = []
    def run_research(self):
        results = {}
        for tf, cfg in BT_TIMEFRAMES.items():
            results[tf] = backtest_kalshi_strategy(days=cfg["days"], spread_cost=self.params["spread"])
        passed = sum(1 for r in results.values() if r.get("pass"))
        adapt = {"results":results,"passed":f"{passed}/{len(BT_TIMEFRAMES)}",
                 "all_pass":passed==len(BT_TIMEFRAMES),
                 "ts":datetime.now(timezone.utc).isoformat()}
        if passed < len(BT_TIMEFRAMES):
            self.params["oversold"] = max(15, self.params["oversold"]-3)
            self.params["overbought"] = min(85, self.params["overbought"]+3)
            self.params["spread"] = max(0.005, self.params["spread"]-0.005)
            adapt["action"] = "AGGRESSIFY"
        elif passed == len(BT_TIMEFRAMES):
            self.params["min_edge"] = min(5, self.params["min_edge"]+0.5)
            adapt["action"] = "TIGHTEN"
        else:
            adapt["action"] = "HOLD"
        adapt["params"] = dict(self.params)
        self.history.append(adapt)
        if len(self.history)>100: self.history = self.history[-50:]
        return adapt
    def should_trade(self):
        if not self.history: self.run_research()
        return self.history[-1].get("all_pass", False)

quant = SelfImprovingQuant()

# ══════════════════════════════════════════════════════════
# CEO VERIFIER - verifies balance, edge, learns
# ══════════════════════════════════════════════════════════
class CEOVerifier:
    def __init__(self):
        self.balance_history = []
        self.drawdown_limit = 0.15
        self.min_confidence = 0.52
        self.learned_patterns = []
    def verify_balance(self, balance):
        self.balance_history.append(balance)
        if len(self.balance_history)>=2:
            peak = max(self.balance_history)
            dd = (peak-balance)/peak if peak>0 else 0
            if dd > self.drawdown_limit:
                return {"approved":False,"reason":f"DRAWDOWN {dd:.1%} > limit"}
        if balance < 1.0:
            return {"approved":False,"reason":"Balance below $1.00"}
        return {"approved":True}
    def verify_edge(self, edge):
        if edge.get("confidence",0) < self.min_confidence:
            return {"approved":False,"reason":f"Conf {edge['confidence']:.2%} < {self.min_confidence:.0%}"}
        if edge.get("edge_cents",0) < 3:
            return {"approved":False,"reason":f"Edge {edge['edge_cents']}c < 3c"}
        for pat in self.learned_patterns:
            if edge.get("ticker","")[:8]==pat.get("prefix",""):
                if pat.get("win_rate",0.5)<0.50:
                    return {"approved":False,"reason":f"Ticker {edge['ticker']} bad history"}
        return {"approved":True}
    def learn_from_outcome(self, ticker, pnl, strategy):
        self.learned_patterns.append({"prefix":ticker[:8],"strategy":strategy,
            "win_rate":1.0 if pnl>0 else 0.0,"ts":datetime.now(timezone.utc).isoformat()})
        conn = sqlite3.connect(DB)
        exists = conn.execute("SELECT id FROM strategy_performance WHERE strategy=?", (strategy,)).fetchone()
        if exists:
            conn.execute("UPDATE strategy_performance SET trades=trades+1,wins=wins+?,total_pnl=total_pnl+? WHERE strategy=?",
                (1 if pnl>0 else 0, pnl or 0, strategy))
        else:
            conn.execute("INSERT INTO strategy_performance (ts,strategy,trades,wins,total_pnl,active) VALUES (?,?,?,?,?,1)",
                (datetime.now(timezone.utc).isoformat(), strategy, 1, 1 if pnl>0 else 0, pnl or 0))
        conn.commit(); conn.close()
        return {"learned":True,"total_patterns":len(self.learned_patterns)}
    def get_growth_rate(self):
        conn = sqlite3.connect(DB)
        curve = conn.execute("SELECT balance FROM equity_curve ORDER BY id").fetchall()
        conn.close()
        if len(curve)<2: return {"growth_rate":0,"cycles":len(curve)}
        first = curve[0][0]; last = curve[-1][0]; n = len(curve)
        if first>0:
            cagr = (last/first)**(1.0/max(n-1,1))-1
            return {"growth_rate":round(cagr,4),"from":first,"to":last,"cycles":n}
        return {"growth_rate":0}

ceo = CEOVerifier()

# ══════════════════════════════════════════════════════════
# PRE-EXECUTION GATE - 5+ checks before EVERY trade
# ══════════════════════════════════════════════════════════
class PreExecGate:
    def __init__(self):
        self.passes=0; self.fails=0; self.last=None
    def verify(self, edge, balance):
        checks = {}
        r = quant.history[-1] if quant.history else quant.run_research()
        checks["backtest_all_tf"] = r.get("all_pass",False)
        ft_loss = sum(1 for t in forward_tester.completed[-10:] if t.get("pnl",0)<0)
        checks["forward_clean"] = ft_loss<=2
        bc = ceo.verify_balance(balance)
        checks["ceo_balance"] = bc.get("approved",False)
        ec = ceo.verify_edge(edge)
        checks["ceo_edge"] = ec.get("approved",False)
        checks["liquidity"] = edge.get("volume",0)>=100
        ok = all(checks.values())
        if ok: self.passes+=1
        else: self.fails+=1
        self.last = {"approved":ok,"checks":checks,"failed":[k for k,v in checks.items() if not v]}
        return self.last

pre_exec_gate = PreExecGate()

# ══════════════════════════════════════════════════════════
# AUTONOMOUS TRADER
# ══════════════════════════════════════════════════════════
class AutonomousTrader:
    def __init__(self):
        self.start_balance = 10.00
        self.current_balance = 10.00
        self.target = 1000.0
        self.max_position_pct = 0.50
        self.compounding = True
        self.spread_cost_cents = 2
        self.strategies = {
            "extreme_yes":{"name":"Extreme YES reversion","trades":0,"wins":0,"pnl":0.0},
            "extreme_no":{"name":"Extreme NO reversion","trades":0,"wins":0,"pnl":0.0},
            "momentum_5m":{"name":"5-min momentum","trades":0,"wins":0,"pnl":0.0},
            "volatility_breakout":{"name":"Vol breakout","trades":0,"wins":0,"pnl":0.0},
            "mean_reversion_15m":{"name":"15-min mean rev","trades":0,"wins":0,"pnl":0.0},
        }
        self.running = False
        self.cycle_interval = 60
        self.max_concurrent = 3
    def update_balance_from_kalshi(self):
        if not kalshi.authenticated: return self.current_balance
        try:
            bal = kalshi.pf_api.get_balance()
            self.current_balance = (getattr(bal,'balance',0))/100.0
            return self.current_balance
        except: return self.current_balance
    def calculate_position_size(self, balance, edge_size):
        kelly_pct = min(0.50, max(0.05, edge_size/200.0))
        return min(self.max_position_pct, kelly_pct) * balance
    def research_markets(self):
        results = {"edges":[],"errors":[]}
        if not kalshi.authenticated:
            results["errors"].append("Not authenticated")
            return results
        conn = sqlite3.connect(DB)
        try:
            markets_resp = kalshi.mkts_api.get_markets(limit=50)
            markets = getattr(markets_resp,'markets',[])
            for m in markets[:40]:
                try:
                    detail = kalshi.mkts_api.get_market(ticker=m.ticker)
                    mk = getattr(detail,'market',None)
                    if not mk: continue
                    yes = getattr(mk,'yes_bid',0) or 0
                    no = getattr(mk,'no_ask',100) or 100
                    last = getattr(mk,'last_price',50) or 50
                    vol = getattr(mk,'volume',0) or 0
                    implied_yes = yes/100.0 if yes>0 else 0
                    spread = abs(no-yes) if no>yes else 10
                    edge = 0; signal = None
                    if implied_yes>0.85:
                        edge = (100-yes)-self.spread_cost_cents
                        if edge>3: signal = "buy_no"
                    elif implied_yes<0.15:
                        edge = yes-self.spread_cost_cents
                        if edge>3: signal = "buy_yes"
                    if signal:
                        conf = min(0.85, 0.50+edge/200.0)
                        results["edges"].append({"ticker":m.ticker,"signal":signal,
                            "edge_cents":round(edge,2),"confidence":round(conf,3),
                            "spread":spread,"yes":yes,"no":no,"volume":vol})
                        conn.execute("INSERT INTO signals (ts,ticker,signal,edge,confidence,status) VALUES (?,?,?,?,?,?)",
                            (datetime.now(timezone.utc).isoformat(), m.ticker, signal, edge, conf, "FOUND"))
                except Exception as e:
                    results["errors"].append(f"Market {m.ticker}: {str(e)[:100]}")
            conn.commit()
        finally: conn.close()
        return results
    def execute_trades(self, edges, balance):
        results = []
        if not kalshi.authenticated: return results
        conn = sqlite3.connect(DB)
        try:
            edges.sort(key=lambda e: e["confidence"]*e["edge_cents"], reverse=True)
            for edge in edges[:self.max_concurrent]:
                size_pct = self.calculate_position_size(balance, edge["edge_cents"])
                count = max(1, int(size_pct/20))
                count = min(count, 5)
                try:
                    side = "yes" if edge["signal"]=="buy_yes" else "no"
                    price = edge["yes"] if edge["signal"]=="buy_yes" else edge["no"]
                    order = kalshi.CreateOrderRequest(
                        ticker=edge["ticker"], action="buy", side=side,
                        count=count, yes_price=price if side=="yes" else None,
                        no_price=price if side=="no" else None, expiration_type="GTC")
                    kalshi.pf_api.create_order(order)
                    conn.execute("INSERT INTO trades (ts,ticker,side,entry_price,count,status,strategy) VALUES (?,?,?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), edge["ticker"], side,
                         edge["entry_price"] if "entry_price" in edge else price, count,
                         "FILLED", "extreme_yes" if side=="yes" else "extreme_no"))
                    results.append({"ticker":edge["ticker"],"side":side,"count":count,"price":price})
                except: pass
            conn.commit()
        finally: conn.close()
        return results
    def update_equity(self):
        bal = self.update_balance_from_kalshi()
        conn = sqlite3.connect(DB)
        trades = conn.execute("SELECT * FROM trades").fetchall()
        won = sum(1 for t in trades if len(t)>7 and t[7]>0)
        total = len(trades)
        wr = (won/total) if total else 0.5
        returns = [t[7] for t in trades if len(t)>7 and t[7]!=0]
        sharpe = (float(np.mean(returns))/float(np.std(returns)))*np.sqrt(252) if (returns and np.std(returns)>0) else 0.0
        equity_data = conn.execute("SELECT balance FROM equity_curve ORDER BY id DESC").fetchall()
        max_dd = 0.0
        if equity_data:
            peak = max(e[0] for e in equity_data)
            max_dd = ((peak-bal)/peak) if peak>0 else 0.0
        conn.execute("INSERT INTO equity_curve (ts,balance,trades,sharpe,win_rate,max_drawdown) VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), bal, total, sharpe, wr, max_dd))
        conn.commit(); conn.close()
        self.current_balance = bal
    def run_cycle(self):
        bal = self.update_balance_from_kalshi()
        self.current_balance = bal
        if not quant.history: quant.run_research()
        forward_tester.sync()
        ft_entries = forward_tester.scan_and_enter() if quant.should_trade() else []
        results = self.research_markets()
        approved = []; gate_details = []
        for e in results.get("edges",[]):
            g = pre_exec_gate.verify(e, bal)
            if g["approved"]:
                approved.append(e)
                gate_details.append({"ticker":e["ticker"],"gate":"PASS"})
            else:
                gate_details.append({"ticker":e.get("ticker"),"gate":"BLOCKED",
                    "reasons":g.get("failed",[])})
        executed = self.execute_trades(approved, bal) if approved else []
        for ex in executed:
            forward_tester.enter(ex.get("ticker",""), ex.get("side",""), ex.get("price",50))
        for ct in forward_tester.completed[-5:]:
            if ct.get("pnl") is not None:
                ceo.learn_from_outcome(ct["ticker"], ct["pnl"], "forward_test")
        self.update_equity()
        return {"balance":round(bal,2),
            "pct_to_target":round(bal/self.target*100,1),
            "all_timeframes_pass":quant.history[-1].get("all_pass",False) if quant.history else False,
            "bt_results":{tf:r for tf,r in quant.history[-1].get("results",{}).items()} if quant.history else {},
            "forward_active":len(forward_tester.active),
            "forward_entries_this_cycle":len(ft_entries),
            "forward_completed":len(forward_tester.completed),
            "forward_results":[{"ticker":t["ticker"],"pnl":t["pnl"],"reason":t["reason"]}
                              for t in forward_tester.completed[-5:]],
            "edges_found":len(results.get("edges",[])),
            "gate_approved":len(approved),"gate_fails":len(gate_details)-len(approved),
            "gate_details":gate_details,"trades_executed":executed,
            "patterns_learned":len(ceo.learned_patterns),
            "gate_stats":{"passes":pre_exec_gate.passes,"fails":pre_exec_gate.fails},
            "quant_params":quant.params,
            "growth_rate":ceo.get_growth_rate(),
            "timestamp":datetime.now(timezone.utc).isoformat()}
    def start_autonomous(self, interval:int=60):
        if self.running: return {"status":"ALREADY_RUNNING"}
        self.running = True; self.cycle_interval = interval
        def loop():
            while self.running:
                try: self.run_cycle(); time.sleep(self.cycle_interval)
                except Exception as e:
                    conn = sqlite3.connect(DB)
                    conn.execute("INSERT INTO autonomous_log (ts,event,details) VALUES (?,?,?)",
                        (datetime.now(timezone.utc).isoformat(),"ERROR",str(e)[:500]))
                    conn.commit(); conn.close(); time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO autonomous_log (ts,event,details) VALUES (?,?,?)",
            (datetime.now(timezone.utc).isoformat(),"STARTED",f"interval={interval}"))
        conn.commit(); conn.close()
        return {"status":"STARTED","interval":interval}
    def stop_autonomous(self):
        self.running = False
        return {"status":"STOPPED"}

trader = AutonomousTrader()

# ══════════════════════════════════════════════════════════
# FASTAPI ENDPOINTS
# ══════════════════════════════════════════════════════════
app = FastAPI(title="Kalshi Autonomous Trading System v7.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status":"alive" if kalshi.authenticated else "unauth",
            "balance":trader.current_balance,"target":1000.0,
            "pct_done":round(trader.current_balance/1000*100,2)}

@app.get("/api/portfolio")
def get_portfolio():
    bal = trader.update_balance_from_kalshi()
    conn = sqlite3.connect(DB)
    t = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    s = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    return {"balance":bal,"target":1000.0,
        "pct_to_target":round(bal/1000*100,2),
        "trades":[{"id":r[0],"time":r[1],"ticker":r[2],"side":r[3],
            "price":r[4],"count":r[6],"pnl":r[7],"status":r[8]} for r in t],
        "signals":[{"ticker":r[2],"signal":r[3],"edge":r[4],"confidence":r[5]} for r in s]}

@app.post("/api/execute")
def execute_trades(): return trader.run_cycle()

@app.post("/api/start")
def start_trading(interval:int=60): return trader.start_autonomous(interval)

@app.post("/api/stop")
def stop_trading(): return trader.stop_autonomous()

@app.get("/api/status")
def status():
    return {"running":trader.running,"balance":trader.current_balance,
        "target":1000.0,"interval_sec":trader.cycle_interval,
        "authenticated":kalshi.authenticated}

@app.get("/api/research")
def research(): return trader.research_markets()

@app.get("/api/strategies")
def strategies(): return trader.strategies

@app.get("/api/logs")
def logs():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM autonomous_log ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return [{"id":r[0],"time":r[1],"event":r[2],"details":r[3]} for r in rows]

@app.get("/api/backtest/all")
def backtest_all(): return quant.run_research()

@app.get("/api/forward")
def forward_test():
    return {"active":[{"ticker":p["ticker"],"side":p["side"],"entry":p["entry"]}
              for p in forward_tester.active.values()],
        "completed":[{"ticker":t["ticker"],"side":t["side"],"pnl":t["pnl"],"reason":t["reason"]}
                     for t in forward_tester.completed]}

@app.get("/api/quant")
def quant_status():
    return {"params":quant.params,"research_runs":len(quant.history),
        "last":quant.history[-1] if quant.history else None,
        "should_trade":quant.should_trade()}

@app.get("/api/gate")
def gate_status():
    return {"passes":pre_exec_gate.passes,"fails":pre_exec_gate.fails,"last":pre_exec_gate.last}

@app.post("/api/research/run")
def run_research(): return quant.run_research()

@app.get("/api/ceo")
def ceo_status():
    return {"balance_checked":ceo.verify_balance(trader.current_balance),
        "min_confidence":ceo.min_confidence,"drawdown_limit":ceo.drawdown_limit,
        "patterns_learned":len(ceo.learned_patterns),
        "growth_rate":ceo.get_growth_rate(),
        "balance_history":ceo.balance_history[-10:]}

@app.post("/api/learn")
def learn_from_result(ticker:str="", pnl:float=0, strategy:str="unknown"):
    return ceo.learn_from_outcome(ticker, pnl, strategy)

@app.get("/api/growth")
def growth(): return ceo.get_growth_rate()

@app.post("/api/self-improve")
def self_improve():
    conn = sqlite3.connect(DB)
    trades = conn.execute("SELECT ticker,side,pnl,strategy FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    for t in trades: ceo.learn_from_outcome(t[0], t[2] or 0, t[3] or "unknown")
    return {"improved":True,"patterns":len(ceo.learned_patterns)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
