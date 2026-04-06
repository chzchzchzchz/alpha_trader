import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run_research(tickers):
    from core.sources import get_etf_signals
    sep = '=' * 60
    print('')
    print(sep)
    print(' STEP 1: RESEARCH - Real-Time Market Data')
    print(sep)
    signals = get_etf_signals(tickers)
    for s in signals:
        print(f'  [LIVE] {s.topic} -> {s.sentiment.value} (conf: {s.confidence:.0%})')
    print(f'  -> {len(signals)} signals fetched')
    return signals


def run_skeptic(signals):
    from core.skeptic import SkepticAgent
    sk = SkepticAgent()
    print('')
    print('=' * 60)
    print(' STEP 2: SKEPTIC - Data Quality Check')
    print('=' * 60)
    verdict = sk.check_data(signals)
    print('  Overall: ' + verdict)
    if 'REJECT' in verdict:
        print('  ABORT: Skeptic rejected. Not trading.')
        return False
    for s in signals:
        v = sk.check_signal({'confidence': s.confidence})
        marker = '[PASS]' if 'PASS' in v or 'CAUT' in v else '[FAIL]'
        print(f'  {marker} {s.topic[:30]}: {v}')
    return True


def run_backtest(tickers):
    from backtest.engine import BacktestEngine
    print('')
    print('=' * 60)
    print(' STEP 3: BACKTEST - Real Historical Data')
    print('=' * 60)
    engine = BacktestEngine(slippage=0.001, commission=0.001)
    best_ticker = None
    best_alpha = -999
    for tk in tickers:
        try:
            result = engine.run_momentum_strategy(tk, '1y')
            if 'error' not in result:
                ret = result.get('total_return_pct', 0)
                sharpe = result.get('sharpe_ratio', 0)
                wr = result.get('win_rate', 'N/A')
                bm = result.get('benchmark_return_pct', 0)
                alpha = result.get('alpha_pct', 0)
                print(f'  {tk}: Return {ret:+.1f}% | BM {bm:+.1f}% | Alpha {alpha:+.1f}% | Sharpe {sharpe:.2f} | WR {wr}')
                if alpha > best_alpha:
                    best_alpha = alpha
                    best_ticker = tk
        except Exception as e:
            print(f'  {tk}: Backtest error - {e}')
    macro = engine.run_macro_strategy()
    if 'error' not in macro:
        trades_n = macro.get('trades', 0)
        wr_m = macro.get('win_rate', 'N/A')
        print(f'  MACRO: Trades {trades_n} | WR {wr_m}')
    return best_ticker


def run_risk_and_sizing(signals, best_ticker, capital=10000):
    from core.kelly_fix import KellySizer
    from core.skeptic import SkepticAgent
    print('')
    print('=' * 60)
    print(' STEP 4: RISK ENGINE + KELLY SIZING')
    print('=' * 60)
    kelly = KellySizer(fraction=0.25)
    sk = SkepticAgent()
    plan = None
    for s in signals:
        cond1 = best_ticker and best_ticker in s.topic
        if cond1 or not best_ticker:
            prob = max(0.5, min(0.85, s.confidence))
            size_pct = kelly.sizing(sig_prob=prob)
            v = sk.check_signal({'confidence': prob})
            if 'REJECT' not in v and size_pct > 0.01:
                ds = capital * size_pct
                contracts = int(ds / 50)
                print(f'  {s.topic}')
                print(f'    Signal prob: {prob:.0%}')
                ds_fmt = '${:,.0f}'.format(ds)
                print(f'    Kelly size: {size_pct:.1%} ({ds_fmt})')
                print(f'    Contracts: {contracts}')
                plan = {
                    'ticker': s.topic.split(':')[0],
                    'size': size_pct,
                    'confidence': prob,
                    'contracts': contracts,
                }
            else:
                print(f'  {s.topic}: REJECTED (low confidence or no edge)')
    return plan


def run_decision(signals, backtest_ticker, plan):
    print('')
    print('=' * 60)
    print(' STEP 5: UNIFIED TRADING DECISION')
    print('=' * 60)
    bull = sum(1 for s in signals if s.sentiment.value == 'bullish')
    bear = sum(1 for s in signals if s.sentiment.value == 'bearish')
    total = len(signals)
    neut = total - bull - bear
    print(f'  Signal Summary: {bull} Bullish / {bear} Bearish / {neut} Neutral')
    print(f'  Best Backtest Ticker: {backtest_ticker}')
    if plan:
        t = plan['ticker']
        sz = plan['size']
        ct = plan['contracts']
        conf = plan['confidence']
        print('')
        print('  [EXECUTE] ' + t)
        print('  Allocation: {:.1%} of capital ({} contracts)'.format(sz, ct))
        print(f'  Confidence: {conf:.0%}')
        print('  Risk: Kelly sized, slippage modeled')
        print('  Pipeline: RESEARCH -> SKEPTIC -> BACKTEST -> RISK -> EXECUTE')
        print('  STATUS: GREEN - Ready for Kalshi/Alpaca')
    else:
        print('')
        print('  [HOLD] No trades recommended.')
        print('  Reason: Insufficient edge or skeptic rejection')
        print('  STATUS: WAIT - Better opportunities may arise')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Alpha Trader')
    parser.add_argument('--tickers', default='SPY,QQQ,IWM,TLT,GLD')
    parser.add_argument('--capital', default=10000, type=float)
    args = parser.parse_args()
    tickers = args.tickers.split(',')
    start = time.time()
    print('')
    print('=' * 60)
    print('  ALPHA TRADER - UNIFIED TRADING MACHINE')
    print('  Capital: ${:,.0f} | Tickers: {}'.format(args.capital, ', '.join(tickers)))
    print('=' * 60)
    print('')
    signals = run_research(tickers)
    if not run_skeptic(signals):
        print('')
        print('>>> PIPELINE STOPPED BY SKEPTIC')
        return
    best_ticker = run_backtest(tickers)
    plan = run_risk_and_sizing(signals, best_ticker, args.capital)
    run_decision(signals, best_ticker, plan)
    elapsed = time.time() - start
    print(f'')
    print(f'  Pipeline completed in {elapsed:.1f}s.')
    print('=' * 60)
    print('')


if __name__ == "__main__":
    main()
