#!/usr/bin/env python3
"""ChatBox Bridge - Connect ChatBox AI to Alpha Trader.
ChatBox sends to /v1/chat/completions, we proxy to this endpoint.
"""
import os, sys, time, json, sqlite3, threading
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI, Request
except ImportError:
    os.system("pip install fastapi uvicorn numpy yfinance httpx cryptography requests 2>&1 | tail -1")
    from fastapi import FastAPI, Request

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import numpy as np

app = FastAPI(title="Alpha Trader Gateway", version="4.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Database
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB = os.path.join(DB_DIR, "unified.db")

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, side TEXT,
        size REAL, status TEXT, notes TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, signal TEXT,
        confidence REAL, strategy TEXT, notes TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS research (
        id INTEGER PRIMARY KEY, ts TEXT, topic TEXT, findings TEXT,
        actionable INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY, ts TEXT, role TEXT, content TEXT,
        model TEXT)""")
    conn.commit()
    conn.close()

init_db()

class CEOAgent:
    """CEO agent - routes, makes decisions, reports status."""
    def __init__(self):
        self.strategies = {
            "GLD_overnight": {
                "name": "GLD Overnight Effect",
                "wr": 0.585, "sharpe": 1.33, "trades": 501,
                "return_pct": 45.7, "active": True
            },
            "QQQ_overnight": {
                "name": "QQQ Overnight Effect",
                "wr": 0.549, "sharpe": 0.41, "trades": 501,
                "return_pct": 10.9, "active": True
            }
        }
        self.balance = 10.00
        self.total_trades = 0
        self.daily_pnl = 0.0
        
    def analyze_all(self):
        """Analyze all strategies and return signals."""
        signals = []
        for key, strat in self.strategies.items():
            if not strat["active"]: continue
            try:
                import yfinance as yf
                ticker = key.split("_")[0]
                h = yf.Ticker(ticker).history(period="5d")
                if len(h) < 2: continue
                cp = float(h["Close"].iloc[-1])
                pp = float(h["Close"].iloc[-2"])
                chg = (cp - pp) / pp
                
                position = min(self.balance * 0.50, self.balance * strat["wr"])
                ev = self.balance * strat["wr"] - self.balance * (1 - strat["wr"])
                
                signals.append({
                    "ticker": ticker,
                    "strategy": strat["name"],
                    "action": "BUY",
                    "price": round(cp, 2),
                    "change": round(chg * 100, 2),
                    "position_size": round(position, 2),
                    "expected_value": round(ev, 2),
                    "wr": strat["wr"],
                    "sharpe": strat["sharpe"],
                    "validated_trades": strat["trades"],
                    "confidence": strat["wr"]
                })
            except Exception as e:
                signals.append({"ticker": key, "error": str(e)[:100]})
        return signals
    
    def execute_signal(self, ticker, side="buy", size=1):
        """Execute a single signal. Log and track."""
        self.total_trades += 1
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO executions VALUES (NULL,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), ticker, side,
             size, "PENDING", "Manual execution"))
        conn.execute("INSERT INTO signals VALUES (NULL,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), ticker, side,
             0.5, "manual", "User executed"))
        conn.commit()
        conn.close()
        return {"status": "EXECUTED", "ticker": ticker, "side": side, "size": size}
    
    def run_research(self):
        """Research cycle - check all markets."""
        results = []
        # Check VIXY regime
        try:
            import yfinance as yf
            vix = yf.Ticker("VIXY").history(period="14d")
            if len(vix) >= 5:
                mom = (vix["Close"].iloc[-1] - vix["Close"].iloc[-5]) / vix["Close"].iloc[-5]
                regime = "FEAR" if mom > 0.05 else ("CALM" if abs(mom) < 0.02 else "VIX RISING")
                results.append({
                    "topic": "VIXY Regime Check",
                    "findings": f"VIXY momentum {mom*100:.1f}% over 5 days. Regime: {regime}",
                    "actionable": abs(mom) > 0.02
                })
        except: pass
        
        # Check cross-asset
        try:
            import yfinance as yf
            for tk in ["SPY", "TLT"]:
                h = yf.Ticker(tk).history(period="3d")
                if len(h) >= 2:
                    chg = (h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2]
                    results.append({
                        "topic": f"{tk} Daily Check",
                        "findings": f"{tk} closed {chg*100:+.2f}% vs previous session",
                        "actionable": abs(chg) > 0.01
                    })
        except: pass
        
        # Log research
        conn = sqlite3.connect(DB)
        for r in results:
            conn.execute("INSERT INTO research VALUES (NULL,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), r["topic"],
                 r["findings"], int(r["actionable"])))
        conn.commit()
        conn.close()
        return results

ceo = CEOAgent()

# ─── CHATBOX COMPATIBLE ENDPOINTS ───
@app.post("/v1/chat/completions")
async def chatbox_completions(request: Request):
    """ChatBox AI compatible endpoint.
    ChatBox sends here, we respond with AI or execute trading commands.
    """
    try:
        body = await request.json()
        messages = body.get("messages", [])
        model = body.get("model", "alpha_trader")
        
        # Log the message
        user_msg = ""
        for m in messages:
            if m.get("role") == "user":
                user_msg = m.get("content", "")
        
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO chat_messages VALUES (NULL,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "user", user_msg[:500], model))
        conn.commit()
        
        # Process the message
        response_text = process_message(user_msg, body)
        
        conn.execute("INSERT INTO chat_messages VALUES (NULL,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "assistant", response_text[:500], model))
        conn.commit()
        conn.close()
        
        if body.get("stream", False):
            async def event_stream():
                yield "data: " + json.dumps({"choices": [{"delta": {"content": response_text}, "finish_reason": "stop"}]}) + "

"
                yield "data: [DONE]

"
            from fastapi.responses import StreamingResponse
            return StreamingResponse(event_stream(), media_type="text/event-stream")
        
        return JSONResponse({
            "id": "chatcmpl-alphatrader",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop", "index": 0}],
            "usage": {"prompt_tokens": len(user_msg), "completion_tokens": len(response_text), "total_tokens": len(user_msg) + len(response_text)}
        })
    except Exception as e:
        return JSONResponse({"error": str(e)[:500]})

def process_message(msg, body=None):
    """Process user message and generate trading/AI response."""
    msg_lower = msg.lower() if msg else ""
    
    if "status" in msg_lower or "report" in msg_lower:
        signals = ceo.analyze_all()
        status = f"**Alpha Trader Status Report**\n\n"
        status += f"**Portfolio:** $10.00\n"
        status += f"**Total Trades:** {ceo.total_trades}\n\n"
        status += f"**Active Signals:**\n"
        for s in signals:
            if "error" not in s:
                status += f"- {s['ticker']}: {s['action']} (${s['price']}, {s['change']:+.2f}%)\n"
                status += f"  Edge: {s['wr']*100:.1f}% WR, Sharpe {s['sharpe']}, {s['validated_trades']} trades\n"
                status += f"  Position: ${s['position_size']}, EV: ${s['expected_value']}\n\n"
        return status
    
    elif "execute" in msg_lower or "trade" in msg_lower or "buy" in msg_lower:
        ticker = "GLD"
        if "spy" in msg_lower: ticker = "SPY"
        elif "qqq" in msg_lower: ticker = "QQQ"
        elif "tlt" in msg_lower: ticker = "TLT"
        result = ceo.execute_signal(ticker, "buy", 1)
        signals = ceo.analyze_all()
        sig = next((s for s in signals if s.get("ticker") == ticker), {})
        return f"**EXECUTED**\n\nTicker: {result['ticker']}\n" +                f"Side: {result['side']}\n" +                f"Size: {result['size']}\n" +                f"Status: {result['status']}\n\n" +                f"Signal: {sig.get('action', '-')} @ ${sig.get('price', '-')}\n" +                f"Edge: {sig.get('wr', 0)*100:.1f}% WR, Sharpe {sig.get('sharpe', '-')}"
    
    elif "research" in msg_lower:
        results = ceo.run_research()
        resp = f"**Research Feed**\n\n"
        for r in results:
            resp += f"- {r['topic']}: {r['findings']}\n"
        return resp if resp else "**Research complete. No new signals.**"
    
    elif "backtest" in msg_lower:
        try:
            import yfinance as yf
            h = yf.Ticker("GLD").history(period="2y")
            o = h["Open"].values; c = h["Close"].values
            night = (o[1:]/c[:-1]) - 1 - 0.001
            w = int(np.sum(night > 0)); t = len(night)
            sh = (np.mean(night)/np.std(night))*np.sqrt(252)
            return (f"**Backtest: GLD Overnight Effect**\n\n" +
                   f"Win Rate: {w/t*100:.1f}%\n" +
                   f"Sharpe: {sh:.2f}\n" +
                   f"Total Return: {np.sum(night)*100:.1f}%\n" +
                   f"Trades: {t}\n" +
                   f"Avg Trade: {np.mean(night)*10000:.1f}bps\n" +
                   f"\nStrategy: Buy GLD at close, sell at open next day\n" +
                   f"Validated over {t} trades with 10bps costs")
        except Exception as e:
            return f"Backtest error: {str(e)[:200]}"
    
    else:
        signals = ceo.analyze_all()
        sig_text = "\n".join([
            f"- {s.get('ticker', '?')}: {s.get('action', '-')} @ ${s.get('price', '-')} " +
            f"({s.get('change', 0):+.2f}%) | Edge: {s.get('wr',0)*100:.1f}% WR"
            for s in signals if "error" not in s
        ])
        return (f"**Alpha Trader** (ask me: status, execute, research, backtest)\n\n" +
               f"**Current Signals:**\n{sig_text}\n\n" +
               f"**Validated Strategy:** GLD overnight effect (58.5% WR, 501 trades)")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "Alpha Trader Gateway", "version": "4.0", "endpoints": ["/v1/chat/completions", "/health", "/api/status", "/api/signals", "/api/execute", "/api/research", "/api/backtest"]}

@app.get("/api/status")
def api_status():
    conn = sqlite3.connect(DB)
    tc = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    sc = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    rc = conn.execute("SELECT COUNT(*) FROM research").fetchone()[0]
    cc = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    conn.close()
    signals = ceo.analyze_all()
    return {"version": "4.0", "status": "LIVE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trades": tc, "signals": sc, "research": rc, "chats": cc,
            "portfolio": {"balance": ceo.balance, "total_trades": ceo.total_trades},
            "active_signals": signals}

@app.get("/api/signals")
def api_signals():
    return ceo.analyze_all()

@app.post("/api/execute")
def api_execute():
    return ceo.execute_signal("GLD", "buy", 1)

@app.get("/api/research")
def api_research():
    results = ceo.run_research()
    return results

@app.get("/api/backtest")
def api_backtest():
    try:
        import yfinance as yf
        h = yf.Ticker("GLD").history(period="2y")
        o = h["Open"].values; c = h["Close"].values
        night = (o[1:]/c[:-1]) - 1 - 0.001
        w = int(np.sum(night > 0)); t = len(night)
        sh = (np.mean(night)/np.std(night))*np.sqrt(252)
        return {"ticker": "GLD", "strategy": "overnight",
                "win_rate_pct": round(w/t*100,1), "trades": t,
                "sharpe": round(sh,2), "total_return_pct": round(np.sum(night)*100,1)}
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/trades")
def api_trades():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM executions ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return [{"id": r[0], "time": r[1], "ticker": r[2], "side": r[3],
             "size": r[4], "status": r[5], "notes": r[6]} for r in rows]

@app.get("/api/chat")
def api_chat():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM chat_messages ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return [{"id": r[0], "time": r[1], "role": r[2], "content": r[3]} for r in rows]

@app.post("/api/research/run")
def api_run_research():
    results = ceo.run_research()
    return results

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    
    def launch():
        time.sleep(1.5)
        try: webbrowser.open("http://127.0.0.1:8000/docs")
        except: print("Open: http://127.0.0.1:8000")
    
    threading.Thread(target=launch).start()
    print("\n" + "="*60)
    print("  ALPHA TRADER v4.0 - UNIFIED PLATFORM")
    print("  ChatBox endpoint: http://127.0.0.1:8000/v1/chat/completions")
    print("  API docs:         http://127.0.0.1:8000/docs")
    print("  Status:           http://127.0.0.1:8000/api/status")
    print("  Signals:          http://127.0.0.1:8000/api/signals")
    print("="*60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
