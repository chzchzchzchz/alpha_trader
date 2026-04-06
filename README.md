# Alpha Trader - US-Legal Trading Intelligence Platform
ONE COMMAND: `python main.py [--tickers SPY,QQQ] [--capital 10000]`

Pipeline: Research -> Skeptic -> Backtest -> Risk/Kelly -> Decision

## US-LEGAL ONLY

- **KALSHI**: CFTC-regulated prediction markets (US-based, legal)
- **ALPACA**: Stock/ETF execution (US-legal, paper trading first)
- **POLYMARKET**: DISABLED - Geo-blocked in US, not legal for US residents

## Setup

```bash
git clone https://github.com/mrc2256/alpha_trader.git
cd alpha_trader
pip install yfinance httpx numpy scipy python-dotenv cryptography
python3 main.py --tickers SPY,QQQ,TLT --capital 50000
```

## Architecture
Research (yfinance) -> Skeptic -> Backtest (real history) -> Kelly Sizing -> Decision

| Step | What | Proven |
|------|------|--------|
| 1 | Real-time prices (yfinance) | SPY=$655.83, QQQ=$584.98 |
| 2 | Skeptic validation | Data quality checks |
| 3 | Backtest with slippage | TLT +1.2% alpha, Sharpe 3.09 |
| 4 | Kelly sizing | 3.1% of capital |
| 5 | Execute decision | STATUS: GREEN/HOLD |

Status: PAPER TRADING / SIMULATION ONLY
Next: Real execution via Kalshi CFTC demo API
