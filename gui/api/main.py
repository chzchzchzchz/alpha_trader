"""Alpha Trader Desktop GUI - FastAPI backend."""
import os, sys, json, sqlite3, time, threading
from datetime import datetime, timezone
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
import numpy as np
import yfinance as yf

app = FastAPI(title="Alpha Trader", version="1.0.0")

# Trade log
trade_log = []
backtest_result = None
bt_running = False

# --- GUI ---
gui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "src")

def read_file(name):
    try:
        with open(os.path.join(gui_dir, name)) as f:
            return f.read()
    except: return ""

@app.get("/", response_class=HTMLResponse)
async def index():
    return read_file("index.html")

@app.get("/styles.css")
async def css():
    return Response(content=read_file("styles.css"), media_type="text/css")

@app.get("/app.js")
async def js():
    return Response(content=read_file("app.js"), media_type="text/javascript")

# --- API ---
@app.get("/api/status")
def api_status():
    return {"status": "LIVE", "version": "1.0.0", "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/api/portfolio")
def api_portfolio():
    try:
        from core.sources import get_etf_signals
        sigs = get_etf_signals(["SPY", "QQQ", "TLT", "IWM", "GLD"])
        prices = []
        for s in sigs:
            parts = s.topic.split(":")
            ticker = parts[0].strip() if parts else "?"
            price = s.data.get("price", 0)
            change = s.data.get("change", 0)
            sent = s.sentiment.value
            prices.append({"ticker": ticker, "price": price, "change": change, "sentiment": sent})
    except: prices = []
    return {
        "equity": 500.0, "pnl_today": 0.0, "open_positions": 0,
        "win_rate": 0.55, "live_prices": prices,
        "trades": [{"ts": t.get("ts","")[:19], "ticker": t.get("ticker",""),
                     "side": t.get("side",""), "size": t.get("size",0),
                     "result": t.get("status","")} for t in trade_log[-20:]]
    }

@app.get("/api/markets")
def api_markets():
    try:
        from kalshi.client import KalshiClient
        c = KalshiClient(
            key_id=os.environ.get("KALSHI_API_KEY_ID"),
            private_key_path=os.environ.get("KALSHI_API_KEY_FILE"),
            demo=os.environ.get("KALSHI_DEMO", "true").lower() == "true"
        )
        mkts = c.get_markets(limit=50)
        m15 = [m for m in mkts if '15M' in m.get('ticker','')]
        result = [{"ticker": m.get("ticker",""), "yes_bid": m.get("yes_bid",0),
                   "no_ask": m.get("no_ask",0), "edge": 0, "side": ""} for m in m15]
        return {"markets": result}
    except Exception as e:
        return {"markets": [], "error": str(e)[:100]}

@app.get("/api/backtest")
def api_backtest():
    if backtest_result:
        return backtest_result
    return {"best_symbol": "-", "best_wr": "-", "best_sharpe": "-", "verdict": "-", "trades_tested": 0}

@app.post("/api/run_backtest")
def api_run_backtest():
    global backtest_result, bt_running
    if bt_running: return {"status": "ALREADY_RUNNING"}
    bt_running = True
    def _run():
        global backtest_result, bt_running
        backtest_result = None
        try:
            symbols = {"BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana"}
            best = None
            for sym, name in symbols.items():
                try:
                    h = yf.Ticker(sym).history(period="60d", interval="15m")
                    closes = h["Close"].values
                    n = len(closes)
                    for mom_w in [24, 48, 96, 192]:
                        for thresh in [0.01, 0.02, 0.03, 0.04]:
                            wins = losses = total = 0
                            cost = 0.03
                            for i in range(mom_w, n-1):
                                mom = (closes[i]-closes[i-mom_w])/closes[i-mom_w]
                                if abs(mom) > thresh:
                                    next_r = (closes[i+1]-closes[i])/closes[i]
                                    outcome = 1 if (mom > 0) == (next_r > 0) else 0
                                    total += 1
                                    if outcome == 1: wins += 1
                                    else: losses += 1
                            if total < 100: continue
                            wr = wins/max(total,1)
                            sharpe = ((wr-0.5)/0.5)*np.sqrt(total) if total > 100 else 0
                            net_pnl = (wins*(1-cost) - losses*cost)
                            if best is None or sharpe > best["sharpe"]:
                                best = {"symbol": sym, "name": name, "wr": round(wr*100,1), "sharpe": round(sharpe,3),
                                       "trades": total, "wins": wins, "losses": losses,
                                       "net_pnl": round(net_pnl,2),
                                       "mom_window": mom_w, "threshold": round(thresh*100,1)}
                except: pass
            if best:
                verdict = "PASS" if best["sharpe"]>1.0 and best["wr"]>52 else "FAIL"
            else:
                verdict = "FAIL"
                best = {"symbol": "-", "sharpe": 0, "wr": 0, "trades": 0}
            backtest_result = {"best_symbol": best["symbol"], "best_wr": str(best["wr"]),
                             "best_sharpe": str(best["sharpe"]), "verdict": verdict,
                             "trades_tested": best["trades"], "net_pnl": best.get("net_pnl",0)}
        except Exception as e:
            backtest_result = {"best_symbol": "ERROR", "verdict": "ERROR", "error": str(e)[:200]}
        bt_running = False
    threading.Thread(target=_run).start()
    return {"status": "BACKTEST_STARTED"}

class TradeReq(BaseModel):
    ticker: str = "SOL"
    side: str = "yes"
    qty: int = 1

@app.post("/api/trade")
def api_trade(req: TradeReq):
    t = {"ts": datetime.now(timezone.utc).isoformat(), "ticker": req.ticker,
         "side": req.side, "size": req.qty, "status": "FILLED (demo)", "price": 0.52}
    trade_log.append(t)
    return t

@app.get("/api/trades")
def api_trades(): return trade_log

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    def open_browser(): webbrowser.open("http://127.0.0.1:8765")
    threading.Timer(1.0, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)
