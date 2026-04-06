#!/usr/bin/env python3
"""ChatBox Bridge — OpenAI-compatible endpoint for alpha_trader."""
import os, sys, time, json, sqlite3
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import numpy as np
import yfinance as yf

app = FastAPI(title="Alpha Trader Gateway", version="11.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB = os.path.join(DB_DIR, "unified.db")

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS chat_log(id INTEGER PRIMARY KEY,ts TEXT,role TEXT,content TEXT);
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,ts TEXT,tk TEXT,side TEXT,price REAL,cnt INT,status TEXT,strat TEXT,pnl REAL);
    """)
    c.commit(); c.close()
init_db()

# ─── Strategy Status ───
STRATEGIES = {
    "near_zero":        {"desc": "Buy contracts at 2-8 cents, sell at 3x", "enabled": True},
    "category_spec":    {"desc": "Win-rate based category rotation", "enabled": True},
    "convergence":      {"desc": "7-filter high-probability convergence", "enabled": True},
    "late_window":      {"desc": "Snipe final 90 seconds at >=93 cents", "enabled": True},
    "flash_crash":      {"desc": "Mean reversion on 30c+ drops", "enabled": True},
    "longshot":         {"desc": "Cheap contract diversification", "enabled": True},
}

@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    user_msg = ""
    for m in messages:
        if m.get("role") == "user": user_msg = m.get("content", "")

    c = sqlite3.connect(DB)
    c.execute("INSERT INTO chat_log (ts,role,content) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(), "user", user_msg[:500]))
    c.commit()

    response = handle_command(user_msg)

    c.execute("INSERT INTO chat_log (ts,role,content) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(), "assistant", response[:2000]))
    c.commit(); c.close()

    if body.get("stream"):
        from fastapi.responses import StreamingResponse
        async def stream():
            yield f"data: {json.dumps({'choices': [{'delta': {'content': response}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    return {"id": "at11", "object": "chat.completion", "created": int(time.time()),
            "model": "alpha_trader_v11", "choices": [{"message": {"role": "assistant", "content": response}, "finish_reason": "stop"}]}

def handle_command(msg: str) -> str:
    m = msg.lower().strip()
    if not m: return "Alpha Trader v11 — Kalshi-only prediction markets. Commands: status, scan, backtest, strategies, help"

    if "help" in m:
        return "**Alpha Trader v11 — Kalshi Autonomous Trading System**\n\nCommands:\n" + \
               "- `status` — portfolio overview\n" + \
               "- `scan` — current Kalshi opportunities\n" + \
               "- `backtest` — run backtest on all timeframes\n" + \
               "- `strategies` — list all 6 strategies\n" + \
               "- `help` — this message"

    if "status" in m or "report" in m:
        return "**Portfolio Status**\n" + \
               f"Target: $10 → $1000\n" + \
               f"Active strategies: 6/6 (Kalshi-native)\n" + \
               f"Mode: DEMO (paper trading)\n\n" + \
               "Strategies loaded:\n" + \
               "- near_zero: Buy at 2-8c, sell at 3x ✅\n" + \
               "- category_specialist: Win-rate rotation ✅\n" + \
               "- convergence: 7-filter convergence ✅\n" + \
               "- late_window: Final 90s snipe ✅\n" + \
               "- flash_crash: Mean-reversion ✅\n" + \
               "- longshot: Diversified cheap contracts ✅"

    if "strateg" in m:
        result = "**6 Strategies (Kalshi-native)**\n\n"
        for name, info in STRATEGIES.items():
            result += f"- **{name}**: {info['desc']}\n"
        return result

    if "backtest" in m:
        return "**Backtest Engine Ready**\n\nBacktest is run automatically by the system.\nLatest results are in the database.\nRun via: curl http://localhost:8000/bt"

    if "scan" in m:
        return "**Market Scanner**\n\nScan runs continuously.\nLatest results via API endpoint.\nRun via: curl http://localhost:8000/scan"

    return f"I hear you. Alpha Trader v11 running. 6 Kalshi strategies active. Say 'status' for portfolio overview."

@app.get("/")
def root():
    return {"service": "Alpha Trader v11", "strategies": 6, "endpoints": ["/v1/chat/completions", "/health", "/status"]}

@app.get("/health")
def health():
    return {"status": "ok", "version": "11.0", "strategies_active": sum(1 for s in STRATEGIES.values() if s["enabled"])}

@app.get("/status")
def status():
    c = sqlite3.connect(DB)
    tc = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    cc = c.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]
    c.close()
    return {"version": "11.0", "mode": "DEMO", "trades": tc, "chats": cc, "strategies": STRATEGIES}

@app.get("/trades")
def trades():
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 20").fetchall()
    c.close()
    return {"trades": rows}
if __name__ == "__main__":
    import uvicorn
    print("Alpha Trader v11 Gateway — ChatBox bridge on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
