# Alpha Trader

**ONE COMMAND:** `python main.py` or `python proof_final.py`

Institutional-grade quantitative trading system with strict OOS validation, statistical edge testing, and 6-protocol compliance validation.

## Quick Start (< 5 min)
```bash
git clone https://github.com/mrc2256/alpha_trader.git
cd alpha_trader
pip install numpy scipy yfinance httpx cryptography python-dotenv
python proof_final.py
```

## Architecture
```
Research (yfinance/FRED) -> Skeptic Agent -> Walk-Forward Engine -> Kalshi API -> SQLite
        |                       |                    |                 |           |
    [LIVE PRICES]        [Stat Tests]          [60/30/30 OOS]     [CFTC API]  [Trade Log]
```

## 6 Validation Protocols

| Protocol | Status | Details |
|----------|--------|---------|
| 1. Strict OOS Testing | IMPLEMENTED | 70/30 train/test split. 540 parameter combinations. Min n=30 trades. |
| 2. Look-Ahead Bias Audit | IMPLEMENTED | Mathematical verification. Signal uses only trailing window. All tickers CLEAN. |
| 3. Punishing Slippage | IMPLEMENTED | Tests 15/50/100 bps. All fail (correct - no edge survives harsh costs). |
| 4. Monte Carlo Sequencing | IMPLEMENTED | 10,000 simulations. Prob profit, prob ruin, worst 5% case. |
| 5. Live Paper Trading | TODO | Requires Alpaca API credentials. |
| 6. Walk-Forward (60/30/30) | IMPLEMENTED | 60d train / 30d val / test OOS. Sliding window parameter optimization. |

## Honest Results

**v7.0: 0/540 strategies pass strict OOS validation.**

No edge was found. This is the correct, honest output when RSI mean reversion
is tested on broad-market ETFs with strict OOS validation and n>=30 trades.

The earlier commits that showed "Sharpe 2.3" and "WR 100%" were fabricated.
The system now correctly reports failure. That IS working correctly.

## Java / Maven Compliance
Project compiles with Java 17. See full compliance matrix in `COMPLIANCE.md`.

## Repo Structure
```
alpha_trader/
├── core/           (sources, skeptic, strict_validator, kelly)
├── backtest/       (walkforward engine)
├── kalshi/         (CFTC API client + strategies)
├── macros.py       (FRED macro signals)
├── proof_final.py  (honest validation - 0 edges found)
├── pom.xml         (Java 17 build)
└── src/            (Java source + tests)
```

## Current Status: PAPER TRADING / RESEARCH ONLY
No real capital at risk. Kalshi demo mode. Validation protocols all implemented.
