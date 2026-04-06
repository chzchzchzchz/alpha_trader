#!/usr/bin/env python3
"""Alpha Trader - The Unified Trading Machine.
ONE COMMAND: python main.py [--tickers SPY,QQQ] [--capital 10000]
Flow: Research -> Skeptic -> Backtest -> Risk -> Execute -> Log
ALL US-LEGAL. No Polymarket (geo-blocked in US)."""
import sys, time, json, os, sqlite3
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '/tmp/at_work')

DB_PATH = Path('/tmp/at_work/data/trades.db')

def init_db():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute('''CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, ticker TEXT, side TEXT, size REAL,
        broker TEXT, strategy TEXT, confidence REAL,
        status TEXT, fill_price REAL, notes TEXT)''')
    conn.commit()
    return conn

def log_trade(conn, t, status, notes):
    conn.execute(
        'INSERT INTO executions (timestamp,ticker,side,size,broker,strategy,confidence,status,fill_price,notes) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (datetime.now(timezone.utc).isoformat(), t.get('ticker',''), t.get('side',''),
         t.get('size',0), t.get('broker',''), t.get('strategy',''), t.get('confidence',0),
         status, t.get('fill_price',0), notes[:200] if notes else ''))
    conn.commit()

def check_risk(t, p, c):
    cap = p.get('capital', 10000)
    if t.get('confidence', 0) < c.get('min_confidence', 0.60):
        return False, f'Confidence {t["confidence"]:.0%} < min {c.get("min_confidence",0.60):.0%}'
    if t.get('size', 0) < c.get('min_kelly_size', 0.01):
        return False, f'Kelly size {t["size"]:.1%} < min'
    today = datetime.now(timezone.utc).date().isoformat()
    conn = init_db()
    n = conn.execute('SELECT COUNT(*) FROM executions WHERE date(timestamp)=date(?)',(today,)).fetchone()[0]
    conn.close()
    if n >= c.get('max_trades', 10):
        return False, f'Max daily trades hit: {n}'
    return True, 'OK'

def connect_kalshi():
    try:
        from kalshi.client import KalshiClient
        key = os.environ.get('KALSHI_API_KEY', '')
        demo = os.environ.get('KALSHI_DEMO', 'true').lower() == 'true'
        if key:
            client = KalshiClient(key_id=key, private_key_path=None, demo=demo)
            return client, f'CONNECTED (demo={demo})'
        return None, 'DRY RUN - No Kalshi key'
    except Exception as e:
        return None, f'DRY RUN - Error: {str(e)[:100]}'

def run_research(tickers):
    from core.sources import get_etf_signals
    print('='*60)
    print(' STEP 1: RESEARCH - Real-Time Market Data')
    print('='*60)
    signals = get_etf_signals(tickers)
    for s in signals:
        print(f'  [LIVE] {s.topic} -> {s.sentiment.value} (conf: {s.confidence:.0%})')
    print(f'  -> {len(signals)} signals fetched')
    return signals

def run_skeptic(signals):
    from core.skeptic import SkepticAgent
    sk = SkepticAgent()
    print()
    print('='*60)
    print(' STEP 2: SKEPTIC - Data Quality Check')
    print('='*60)
    v = sk.check_data(signals)
    print(f'  Overall: {v}')
    if 'REJECT' in v:
        print('  ABORT: Skeptic rejected. Not trading.'); return False
    for s in signals:
        v2 = sk.check_signal({'confidence': s.confidence})
        mk = '[PASS]' if 'PASS' in v2 or 'CAUT' in v2 else '[FAIL]'
        print(f'  {mk} {s.topic[:30]}: {v2}')
    return True

def run_backtest(tickers):
    from backtest.engine import BacktestEngine
    print()
    print('='*60)
    print(' STEP 3: BACKTEST - Real Historical Data')
    print('='*60)
    engine = BacktestEngine(slippage=0.001, commission=0.001)
    best, best_alpha = None, -999
    for tk in tickers:
        try:
            r = engine.run_momentum_strategy(tk, '1y')
            if 'error' not in r:
                ret = r.get('total_return_pct',0)
                bm = r.get('benchmark_return_pct',0)
                alpha = r.get('alpha_pct',0)
                sharpe = r.get('sharpe_ratio',0)
                wr = r.get('win_rate','N/A')
                print(f'  {tk}: Return {ret:+.1f}% | BM {bm:+.1f}% | Alpha {alpha:+.1f}% | Sharpe {sharpe:.2f} | WR {wr}')
                if alpha > best_alpha: best_alpha, best = alpha, tk
        except Exception as e:
            print(f'  {tk}: Backtest error - {e}')
    macro = engine.run_macro_strategy()
    if 'error' not in macro:
        print(f'  MACRO: {macro.get("trades",0)} trades | WR {macro.get("win_rate","N/A")}')
    return best

def run_sizing(signals, best, capital=10000):
    from core.kelly_fix import KellySizer
    from core.skeptic import SkepticAgent
    print()
    print('='*60)
    print(' STEP 4: RISK ENGINE + KELLY SIZING')
    print('='*60)
    kel = KellySizer(fraction=0.25)
    sk = SkepticAgent()
    plan = None
    for s in signals:
        if (best and best in s.topic) or not best:
            prob = max(0.5, min(0.85, s.confidence))
            sp = kel.sizing(sig_prob=prob)
            v = sk.check_signal({'confidence': prob})
            if 'REJECT' not in v and sp > 0.01:
                ds = capital * sp
                ct = int(ds / 50)
                print(f'  {s.topic}')
                print(f'    Prob: {prob:.0%} | Kelly: {sp:.1%} (${ds:,.0f}) | Contracts: {ct}')
                plan = {'ticker': s.topic.split(':')[0], 'side': 'buy', 'size': sp,
                        'confidence': prob, 'contracts': ct, 'broker': 'kalshi',
                        'strategy': 'etf_momentum'}
            else:
                print(f'  {s.topic}: REJECTED')
    return plan

def run_execute(plan, capital):
    print()
    print('='*60)
    print(' STEP 5: EXECUTION + SQLITE LOGGING')
    print('='*60)
    if not plan:
        print('  [HOLD] No trades.'); print('  STATUS: WAIT'); return
    conn = init_db()
    port = {'capital': capital, 'daily_pnl': 0}
    cfg = {'max_trades': 10, 'min_confidence': 0.60, 'min_kelly_size': 0.01}
    ok, reason = check_risk(plan, port, cfg)
    if not ok:
        print(f'  [BLOCKED] {reason}')
        log_trade(conn, plan, 'BLOCKED', reason)
        conn.close(); return
    client, status = connect_kalshi()
    print(f'  Broker: {status}')
    if client and 'DRY' not in status:
        try:
            tk = plan['ticker'].replace(' ','').upper()[:20]
            r = client.place_order(ticker=tk, action='buy', side='yes', count=plan.get('contracts',1))
            log_trade(conn, plan, 'FILLED', json.dumps(r)[:200])
            print(f'  [FILLED] {json.dumps(r)[:150]}')
        except Exception as e:
            log_trade(conn, plan, 'ERROR', str(e)[:200])
            print(f'  [ERROR] {e}')
    else:
        log_trade(conn, plan, 'DRY_RUN', status)
        print(f'  [DRY RUN] {plan["ticker"]} {plan["side"]} {plan["contracts"]} contracts')
    total = conn.execute('SELECT COUNT(*) FROM executions').fetchone()[0]
    conn.close()
    print(f'  Total trades logged: {total}')
    print(f'  STATUS: {"FILLED" if client else "DRY RUN"} - Ready for Kalshi live')

def show_dashboard():
    conn = init_db()
    print()
    print('='*60)
    print(' TRADE LOG (last 5)')
    print('='*60)
    rows = conn.execute('SELECT id,timestamp,ticker,status,notes FROM executions ORDER BY id DESC LIMIT 5').fetchall()
    if rows:
        for r in rows:
            print(f'  #{r[0]} [{r[1][:19]}] {r[2]} -> {r[3]} | {r[4][:60] if r[4] else ""}')
    else:
        print('  (empty)')
    conn.close()

def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description='Alpha Trader')
    parser.add_argument('--tickers', default='SPY,QQQ,IWM,TLT,GLD')
    parser.add_argument('--capital', default=10000, type=float)
    args = parser.parse_args()
    tickers = args.tickers.split(',')
    start = time.time()
    print()
    print('='*60)
    print('  ALPHA TRADER - UNIFIED TRADING MACHINE')
    print(f'  Capital: ${args.capital:,.0f} | Tickers: {", ".join(tickers)}')
    print('='*60)
    print()
    signals = run_research(tickers)
    if not run_skeptic(signals):
        print(''); print('>>> PIPELINE STOPPED BY SKEPTIC'); return
    best = run_backtest(tickers)
    plan = run_sizing(signals, best, args.capital)
    run_execute(plan, args.capital)
    show_dashboard()
    print(f'')
    print(f'  Pipeline completed in {time.time()-start:.1f}s.')
    print('='*60)
    print('')

if __name__ == "__main__":
    main()