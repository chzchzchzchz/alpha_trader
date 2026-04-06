#!/usr/bin/env python3
"""RUN LIVE: Autonomous Kalshi trading."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timezone

H = "=" * 70
print("")
print(H)
print("  ALPHA TRADER: AUTONOMOUS EXECUTION")
print("  Kalshi 15-min crypto direction markets")
print("  " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
print(H)

# 0. Connect to Kalshi
print("\n[1] CONNECTING TO KALSHI")
try:
    os.system("pip install cryptography requests httpx 2>/dev/null")
    from kalshi.client import KalshiClient
    c = KalshiClient(key_id="REDACTED_KALSHI_KEY_ID", private_key_path=None, demo=True)
    mkts = c.get_markets(limit=5)
    print("  CONNECTED: " + str(len(mkts)) + " markets")
    for m in mkts[:3]:
        tk = m.get("ticker", "?")
        yes = m.get("yes_bid", 0)
        no = m.get("no_ask", 0)
        print("    " + tk[:40] + ": YES " + str(yes) + "c / NO " + str(no) + "c")
except Exception as e:
    print("  FAIL: " + str(e))
    sys.exit(1)

# 1. Initialize strategy
print("\n[2] LOADING STRATEGY")
from strategies.kalshi_auto import KalshiAutonomous
stgt = KalshiAutonomous(c, min_edge=8, max_bet=15)
print("  Min edge: 8%")
print("  Max bet: 15 contracts")
print("  Capital: $500")

# 2. Run 3 cycles
print("\n[3] RUNNING 3 CYCLES")
results = []
for i in range(3):
    print("\n  --- Cycle " + str(i + 1) + " ---")
    r = stgt.run_cycle(capital=500)
    results.append(r)
    print("  -> " + str(r.get("status", "?")))

# 3. Summary
print("\n[4] SUMMARY")
executed = sum(1 for r in results if r.get("status") == "EXECUTED")
no_edge = sum(1 for r in results if r.get("status") == "NO_EDGES")
print("  Cycles: " + str(len(results)))
print("  Trades executed: " + str(executed))
print("  No edges found: " + str(no_edge))

# 4. Trade log
print("\n[5] TRADES")
trades = stgt.get_trades()
for t in trades:
    print("  " + t["ts"][:19] + " | " + t["ticker"] + " " + t["side"] + " x" + str(t["size"]) + " (edge " + str(t["edge"]) + "%)")

# 5. Database
print("\n[6] SQLITE LOG")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "live.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)
conn = sqlite3.connect(DB)
try:
    conn.execute("DROP TABLE live")
except Exception:
    pass
conn.execute("CREATE TABLE live (id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, side TEXT, size INT, edge REAL, result TEXT)")
conn.commit()
for t in trades:
    conn.execute("INSERT INTO live VALUES (NULL,?,?,?,?,?,?)",
        (t["ts"], t["ticker"], t["side"], t["size"], t["edge"], json.dumps(t.get("result", {}))[:500]))
conn.commit()
count = conn.execute("SELECT COUNT(*) FROM live").fetchone()[0]
print("  Logged: " + str(count) + " trades")
rows = conn.execute("SELECT * FROM live ORDER BY id DESC LIMIT 5").fetchall()
for rw in rows:
    rstr = rw[5][:50] if rw[5] else ""
    print("  #" + str(rw[0]) + " " + rw[1][:19] + " " + rw[2] + " " + rw[3] + " x" + str(rw[4]) + " | " + rstr)
conn.close()

print("\n" + H)
print("  DONE: " + str(executed) + " trades executed, " + str(no_edge) + " no edges")
print("  Status: AUTONOMOUS RUNNING")
print(H + "\n")
