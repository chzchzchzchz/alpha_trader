#!/usr/bin/env python3
"""Alpha Trader - The Unified Trading Machine.

ONE command does IT ALL:
  Research -> Skeptic -> Backtest -> Risk/Sizing -> Strategy -> Decision

Usage: python main.py [--tickers SPY,QQQ,IWM] [--capital 10000]
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run_research(tickers):
    """Step 1: Fetch real US-legal market data."""
    from core.sources import get_etf_signals
    signals = get_etf_signals(tickers)
    print("\n" + "=" * 60)
    print(" STEP 1: RESEARCH - REAL-TIME MARKET DATA")
    print("=" * 60)
    for s in signals:
        print(f"  [LIVE] {s.topic} -> {s.sentiment.value} (conf: {s.confidence:.0%})")
    print(f"  -> {len(signals)} real signals fetched")
    return signals


def run_skeptic(signals):
    """Step 2: Validate data quality."""
    from core.skeptic import SkepticAgent
    sk = SkepticAgent()
    print("\n" + "=" * 60)
    print(" STEP 2: SKEPTIC - DATA QUALITY CHECK")
    print("=" * 60)
    verdict = sk.check_data(signals)
    print(f"  Overall: {verdict}")
    if "REJECT" in verdict:
        print("  ABORT: Skeptic rejected the data. Not trading.")
        return False
    all_pass = True
    for s in signals:
        v = sk.check_signal({"confidence": s.confidence})
        marker = "[PASS]" if "PASS" in v or "CAUT" in v else "[FAIL]"
        print(f"  {marker} {s.topic[:30]}: {v}")
        if "REJECT" in v:
            all_pass = False
    return all_pass


def run_backtest(tickers):
    """Step 3: Backtest with REAL historical data + slippage."""
    from backtest.engine import BacktestEngine
    print("\n" + "=" * 60)
    print(" STEP 3: BACKTEST - REAL HISTORICAL DATA")
    print("=" * 60)
    engine = BacktestEngine(slippage=0.001, commission=0.001)
    best_ticker = None
    best_alpha = -999
    
    for tk in tickers:
        try:
            result = engine.run_momentum_strategy(tk, "1y")
            if "error" not in result:
                ret = result.get("total_return_pct", 0)
                bm = result.get("benchmark_return_pct", 0)
                alpha = result.get("alpha_pct", 0)
                sharpe = result.get("sharpe_ratio", 0)
                wr = result.get("win_rate", "N/A")
                trades = result.get("total_trades", 0)
                print(f"  {tk}: Return {ret:+.1f}% | BM {bm:+.1f}% | Alpha {alpha:+.1f}% | Sharpe {sharpe:.2f} | WR {wr} | {trades} trades")
                if alpha > best_alpha:
                    best_alpha = alpha
                    best_ticker = tk
            else:
                print(f"  {tk}: {result['error']}")
        except Exception as e:
            print(f"  {tk}: Backtest error - {e}")

    macro = engine.run_macro_strategy()
    if "error" not in macro:
        print(f"  MACRO: {macro.get('win_rate', 'N/A')} WR | {macro.get('trades', 0)} trades")
    
    return best_ticker


def run_risk_and_sizing(signals, best_ticker="SPY", capital=10000):
    """Step 4: Risk engine + Kelly sizing."""
    from core.kelly_fix import KellySizer
    print("\n" + "=" * 60)
    print(" STEP 4: RISK ENGINE + KELLY SIZING")
    print("=" * 60)
    kelly = KellySizer(fraction=0.25)
    
    plan = None
    for s in signals:
        if best_ticker in s.topic or best_ticker is None:
            prob = max(0.5, min(0.85, s.confidence))
            size_pct = kelly.sizing(sig_prob=prob, yes_price=55, no_price=45)
            if size_pct > 0:
                dollar_size = capital * size_pct
                contracts = int(dollar_size / 50)
                print(f"  {s.topic}")
                print(f"    Signal prob: {prob:.0%}")
                print(f"    Kelly fraction: {kelly.kelly_fraction(prob, 0.5, 0.5):.1%}")
                print(f"    Size: {size_pct:.1%} (${dollar_size:,.0f})")
                print(f"    Contracts: {contracts}")
                plan = {"ticker": s.topic.split(":")[0], "size": size_pct, "confidence": prob, "contracts": contracts}
            else:
                print(f"  {s.topic}: No edge (Kelly=0)")
    return plan


def run_decision(signals, backtest_ticker, plan):
    """Step 5: Final unified trading decision."""
    print("\n" + "=" * 60)
    print(" STEP 5: UNIFIED TRADING DECISION")
    print("=" * 60)
    
    bull = sum(1 for s in signals if s.sentiment.value == "bullish")
    bear = sum(1 for s in signals if s.sentiment.value == "bearish")
    total = len(signals)
    
    print(f"  Sentiment: {bull}B/{bear}b/{total-bull-bear}N")
    print(f"  Best backtest ticker: {backtest_ticker}")
    
    if plan:
        print(f"\n  [EXECUTE] {plan['ticker']}")
        print(f"  Size: {plan['size']:.1%} of capital ({plan['contracts']} contracts)")
        print(f"  Confidence: {plan['confidence']:.0%}")
        print(f"  Risk: Kelly sized, slippage modeled")
        print(f"  Pipeline: RESEARCH -> SKEPTIC -> BACKTEST -> RISK -> EXECUTE")
        print(f"  STATUS: GREEN - Ready for Kalshi/Alpaca/Polymarket")
    else:
        print(f"\n  [HOLD] No trade recommended.")
        print(f"  Reason: Insufficient edge or skeptic rejection")
        print(f"  STATUS: WAIT - Better opportunities may arise")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Alpha Trader Unified - Print Money Machine")
    parser.add_argument("--tickers", default="SPY,QQQ,IWM,TLT,GLD", help="ETF tickers to analyze")
    parser.add_argument("--capital", default=10000, type=float, help="Starting capital")
    args = parser.parse_args()
    
    tickers = args.tickers.split(",")
    start = time.time()
    
    print("\n" + "=" * 60)
    print("  ALPHA TRADER - UNIFIED TRADING MACHINE")
    print(f"  Capital: ${args.capital:,.0f} | Tickers: {', '.join(tickers)}")
    print("=" * 60)
    
    # PIPELINE
    signals = run_research(tickers)
    if not run_skeptic(signals):
        print("\n>>> PIPELINE STOPPED BY SKEPTIC")
        return
    
    best_ticker = run_backtest(tickers)
    plan = run_risk_and_sizing(signals, best_ticker, args.capital)
    run_decision(signals, best_ticker, plan)
    
    elapsed = time.time() - start
    print(f"\n  Pipeline completed in {elapsed:.1f} seconds.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
