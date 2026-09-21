#!/usr/bin/env python3
"""
Alpha Trader Dashboard — FastAPI
Shows live balance, positions, signals, trades, logs, start/stop.
Does NOT run the trader — just monitors and controls it.
Port: 8001
"""
import os, sys, time, json, sqlite3, subprocess, signal
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

LOG = os.path.expanduser("~/alpha_trader/logs/autonomous_trader.out")
DB = os.path.expanduser("~/alpha_trader/data/autonomous.db")
STATS = os.path.expanduser("~/alpha_trader/data/stats.json")
SCRIP = os.path.expanduser("~/alpha_trader/autonomous_trader.py")

app = FastAPI()

# ── helpers ──

def find_pids():
    r = subprocess.run(["pgrep","-f","autonomous_trader.py"], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split() if p.isdigit()] if r.stdout else []

def tail(n=200):
    try:
        return "".join(open(LOG).readlines()[-n:])
    except: return "No log."

def db_stats():
    if not Path(DB).exists(): return {}
    c = sqlite3.connect(DB)
    s = dict(
        scans = c.execute("SELECT COUNT(*) FROM scans").fetchone()[0],
        trades = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
        top_signals = c.execute("SELECT * FROM scans ORDER BY score DESC LIMIT 10").fetchall(),
        recent_trades = c.execute("SELECT ts,ticker,side,price_cents,status,order_id FROM trades ORDER BY ts DESC LIMIT 20").fetchall(),
    )
    c.close()
    return s

def file_stats():
    try: return json.loads(open(STATS).read())
    except: return {}

def parse_cycles(t):
    cyc = []
    for l in t.split("\n"):
        if "CYCLE" in l and "UTC" in l:
            parts = l.split("|")
            if len(parts)>=3:
                try:
                    n = int(parts[0].split("CYCLE")[1].strip())
                    bal = float(parts[-1].strip().replace("$",""))
                    cyc.append({"n":n, "bal":bal})
                except: pass
    return cyc

# ── API ──

@app.get("/api/status")
def status():
    pids = find_pids()
    log = tail(100)
    cyc = parse_cycles(log)
    ds = db_stats()
    fs = file_stats()
    return {
        "alive": bool(pids),
        "pid": pids[0] if pids else None,
        "pids": pids,
        "balance": cyc[-1]["bal"] if cyc else 0,
        "cycles": fs.get("cycles", len(cyc)),
        "total_trades": fs.get("total_trades", ds.get("trades", 0)),
        "total_scans": fs.get("total_scans", ds.get("scans", 0)),
        "top_signals": [{"ticker":r[1],"price":r[2],"score":r[6]} for r in (ds.get("top_signals") or [])],
        "recent_trades": [{"ts":r[0],"ticker":r[1],"side":r[2],"price":r[3],"status":r[4]} for r in (ds.get("recent_trades") or [])[:10]],
        "log": log[-3000:],
    }

@app.post("/api/start")
def start():
    if find_pids(): return {"ok":False,"msg":"already running"}
    subprocess.Popen(
        [sys.executable, str(SCRIP)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        stdout=open(LOG,"a"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"ok":True,"msg":"started"}

@app.post("/api/kill")
def kill():
    pids = find_pids()
    for p in pids:
        try: os.kill(p, signal.SIGTERM)
        except: pass
    return {"ok":True,"killed":pids}

@app.post("/api/restart")
def restart():
    kill()
    time.sleep(2)
    return start()

# ── HTML Dashboard ──

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Alpha Trader Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.bar{display:flex;align-items:center;gap:12px;padding:8px 16px;background:#161b22;border-bottom:1px solid #21262d}
.bar h1{font-size:16px;color:#58a6ff}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.dot.on{background:#3fb950;box-shadow:0 0 6px #3fb950}
.dot.off{background:#f85149}
.btn{padding:5px 12px;border:1px solid #30363d;background:#21262d;color:#c9d1d9;cursor:pointer;border-radius:5px;font-family:inherit;font-size:12px}
.btn:hover{background:#30363d} .btn.go{color:#3fb950;border-color:#238636} .btn.no{color:#f85149;border-color:#da3633}
.kpi{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;padding:12px 16px}
.card{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:12px;text-align:center}
.card .v{font-size:24px;font-weight:bold} .card .l{font-size:10px;color:#8b949e;margin-top:2px;text-transform:uppercase}
.g{color:#3fb950}.r{color:#f85149}.b{color:#58a6ff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 16px 12px}
.box{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:10px}
.box h3{font-size:11px;color:#8b949e;text-transform:uppercase;margin-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#8b949e;border-bottom:1px solid #21262d;font-weight:400;padding:2px 4px}
td{padding:2px 4px;border-bottom:1px solid #0d1117}
.log{margin:0 16px 12px;background:#161b22;border:1px solid #21262d;border-radius:6px;padding:8px;font-size:11px;color:#8b949e;max-height:280px;overflow-y:auto;white-space:pre-wrap;line-height:1.5}
</style></head><body>
<div class="bar">
  <div class="dot" id="dot"></div>
  <h1>Alpha Trader Dashboard</h1>
  <span id="clk" style="color:#484f58"></span>
  <button class="btn go" onclick="act('start')">▶ Start</button>
  <button class="btn no" onclick="act('kill')">■ Stop</button>
  <button class="btn" onclick="act('restart')">↻ Restart</button>
</div>
<div class="kpi" id="kpi"></div>
<div class="grid">
  <div class="box"><h3>Top Signals</h3><table><tr><th>Ticker</th><th>Price</th><th>Score</th></tr><tbody id="sig"></tbody></table></div>
  <div class="box"><h3>Recent Trades</h3><table><tr><th>Ticker</th><th>Side</th><th>Price</th><th>Status</th></tr><tbody id="trd"></tbody></table></div>
</div>
<div class="log" id="log"></div>
<script>
const A='/api';
async function G(){const r=await fetch(A+'/status');return r.json()}
async function P(a){fetch(A+'/'+a,{method:'POST'});setTimeout(R,1500)}
function T(u){const d=new Date(u*1000);return d?d.toLocaleTimeString():''}
async function R(){
  const d=await G();
  document.getElementById('dot').className='dot '+(d.alive?'on':'off');
  document.getElementById('clk').textContent=new Date().toLocaleTimeString();
  document.getElementById('kpi').innerHTML=[
    ['Balance','$'+d.balance.toFixed(2),true],
    ['Cycles',d.cycles],['Trades',d.total_trades,true],
    ['Scans',d.total_scans],['PID',d.pid?d.pid:'—'],
    ['Signals',d.total_scans?d.total_scans:'—']].map(([l,v,g])=>`<div class="card"><div class="v ${g?'g':'b'}">${v}</div><div class="l">${l}</div></div>`).join('');
  document.getElementById('sig').innerHTML=(d.top_signals||[]).map(s=>`<tr><td>${s.ticker}</td><td>${(s.price*100).toFixed(0)}¢</td><td>${s.score}</td></tr>`).join('');
  document.getElementById('trd').innerHTML=(d.recent_trades||[]).map(t=>`<tr><td>${t.ticker}</td><td class="${t.side=='yes'?'g':'r'}">${t.side}</td><td>${t.price}¢</td><td>${t.status}</td></tr>`).join('');
  const el=document.getElementById('log');el.textContent=d.log;el.scrollTop=el.scrollHeight;
}
function act(a){P(a)}
R();setInterval(R,5000);
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def home(): return HTML

if __name__ == "__main__":
    print(f"Dashboard: http://127.0.0.1:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
