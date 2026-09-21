#!/usr/bin/env python3
"""
Dashboard — Quick status view for alpha_trader.
Shows: open positions, recent trades, metrics, system health.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

def format_cents(cents: int) -> str:
    return f"${cents/100:.2f}"

def format_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime('%H:%M:%S')

def print_header():
    print("\n" + "="*80)
    print(" ALPHA TRADER DASHBOARD")
    print("="*80)

def show_db_stats(db_path: Path):
    if not db_path.exists():
        print("DB not found")
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    print("\n📊 DATABASE")
    for table in ('trades', 'positions', 'signals'):
        try:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            count = cur.fetchone()[0]
            print(f"  {table:12} : {count:6}")
        except:
            print(f"  {table:12} : N/A")
    # Open positions summary
    try:
        cur.execute("SELECT COUNT(DISTINCT ticker), SUM(contracts) FROM positions WHERE status != 'closed'")
        tickers, contracts = cur.fetchone()
        print(f"  open tickers : {tickers or 0:3}")
        print(f"  total contracts : {contracts or 0:6}")
    except:
        pass
    conn.close()

def show_positions(db_path: Path, limit: int = 10):
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    print("\n📍 OPEN POSITIONS")
    try:
        cur.execute("""
            SELECT ticker, strategy, side, entry_price_cents, contracts, entry_ts
            FROM positions WHERE status != 'closed'
            ORDER BY entry_ts DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        if not rows:
            print("  None")
            return
        print(f"  {'TICKER':<16} {'STRATEGY':<16} {'SIDE':<4} {'ENTRY':>8} {'CONTRACTS':>8} {'TIME':<8}")
        for ticker, strat, side, ep, cnt, ts in rows:
            print(f"  {ticker:<16} {strat:<16} {side:<4} {format_cents(ep):>8} {cnt:>8} {format_dt(ts):<8}")
    except Exception as e:
        print(f"  Error: {e}")
    conn.close()

def show_recent_trades(db_path: Path, limit: int = 10):
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    print("\n💰 RECENT TRADES")
    try:
        cur.execute("""
            SELECT ticker, side, price_cents, contracts, status, ts
            FROM trades ORDER BY ts DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        if not rows:
            print("  None")
            return
        print(f"  {'TICKER':<16} {'SIDE':<4} {'PRICE':>8} {'CNT':>6} {'STATUS':<10} {'TIME':<8}")
        for ticker, side, price, cnt, status, ts in rows:
            print(f"  {ticker:<16} {side:<4} {format_cents(price):>8} {cnt:>6} {status:<10} {format_dt(ts):<8}")
    except Exception as e:
        print(f"  Error: {e}")
    conn.close()

def show_metrics(metrics_log: Path, limit: int = 5):
    if not metrics_log.exists():
        print("\n📈 METRICS: (no log)")
        return
    lines = metrics_log.read_text().strip().splitlines()
    if not lines:
        return
    print("\n📈 RECENT CYCLES")
    for line in lines[-limit:][::-1]:
        m = json.loads(line)
        status = "OK" if m.get('success') else "FAIL"
        print(f"  Cycle {m.get('start_ts')} : {status} markets={m.get('markets_fetched',0)} signals={m.get('raw_signals',0)} alloc={m.get('allocations',0)} exec={m.get('executed_orders',0)} exits={m.get('executed_exits',0)} time={m.get('cycle_time',0):.2f}s")

def show_log_tail(log_file: Path, lines: int = 20):
    if not log_file.exists():
        return
    content = log_file.read_text().splitlines()
    print(f"\n📋 LAST {lines} LOG LINES:")
    for line in content[-lines:]:
        print(f"  {line}")

def main():
    repo = Path(__file__).parent.parent
    db = repo / 'data' / 'alpha_trader.db'
    log = repo / 'logs' / 'autonomous_loop_current.log'
    metrics = repo / 'logs' / 'metrics.jsonl'

    print_header()
    show_db_stats(db)
    show_positions(db)
    show_recent_trades(db)
    show_metrics(metrics)
    show_log_tail(log, lines=10)

    print("\n" + "="*80)
    print(" To tail logs: tail -f logs/autonomous_loop_current.log")
    print(" To stop: kill $(cat logs/autonomous_loop.pid)")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
