#!/usr/bin/env python3
import os, sys, time, sqlite3, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/recon.log")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [RECON] %(levelname)s %(message)s", handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()])
log = logging.getLogger("recon")
def get_kalshi_positions(client):
    try:
        resp = client.get_positions()
        pos = {}
        for p in resp.get("positions", []):
            t = p.get("ticker")
            yes = p.get("yes_position", 0)
            no = p.get("no_position", 0)
            if yes or no:
                pos[t] = {"yes": yes, "no": no}
        return pos
    except Exception as e:
        log.error(f"Fetch Kalshi positions failed: {e}")
        return {}
def get_local_positions(conn):
    rows = conn.execute("SELECT ticker, count, side FROM positions").fetchall()
    pos = {}
    for ticker, count, side in rows:
        pos[ticker] = {"count": count, "side": side}
    return pos
def reconcile():
    log.info("=== Position reconciliation cycle ===")
    client = KalshiClient(
        key_id=os.getenv("KALSHI_API_KEY_ID"),
        private_key_path=os.path.expanduser(os.getenv("KALSHI_API_KEY_FILE", "~/.kalshi/private_key.pem")),
        demo=os.getenv("KALSHI_DEMO", "true").lower() == "true",
    )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    k_pos = get_kalshi_positions(client)
    l_pos = get_local_positions(conn)
    k_tickers = set(k_pos.keys())
    l_tickers = set(l_pos.keys())
    missing_local = k_tickers - l_tickers
    missing_kalshi = l_tickers - k_tickers
    mismatches = []
    for ticker in k_tickers & l_tickers:
        k = k_pos[ticker]
        l = l_pos[ticker]
        if l["side"] == "yes" and l["count"] != k["yes"]:
            mismatches.append((ticker, f"local {l['count']} vs K {k['yes']}"))
        elif l["side"] == "no" and l["count"] != k["no"]:
            mismatches.append((ticker, f"local {l['count']} vs K {k['no']}"))
    log.info(f"Recon: K={len(k_tickers)}, L={len(l_tickers)}")
    if missing_local:
        log.warning(f"Missing in local: {sorted(missing_local)}")
    if missing_kalshi:
        log.warning(f"Missing in Kalshi: {sorted(missing_kalshi)}")
    if mismatches:
        log.error(f"Mismatches: {len(mismatches)} -> {mismatches[:10]}")
        if len(mismatches) > 10:
            snap = os.path.expanduser(f"~/alpha_trader/logs/recon_snap_{int(time.time())}.json")
            import json
            with open(snap, 'w') as f:
                json.dump({"kalshi": k_pos, "local": l_pos, "mismatches": mismatches}, f, indent=2)
            log.critical(f"Snapshot: {snap}")
    else:
        log.info("All positions match")
    conn.close()
if __name__ == "__main__":
    try:
        reconcile()
    except Exception as e:
        log.error(f"Recon crashed: {e}", exc_info=True)
        sys.exit(1)
