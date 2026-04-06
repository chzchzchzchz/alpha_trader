# PRD: Autonomous Kalshi Trading System v13 — Proof of Utility

## Overview
Build a fully autonomous Kalshi trading system that scans markets, backtests strategies on REAL data, and runs continuous 24/7 trading loops. No stubs, no fake data, no permission asks.

## Current State
- Auth: WORKING (RSA-PSS with correct prefix). Balance $9.93.
- Client: v4 complete — balance, positions, orders, fills, market data all verified.
- Strategies: 6 original + 4 FIFA-UT psychology (panic_sniper, time_sniper, overreaction_reversal, smart_money)
- Problem: None of the strategies have been backtested on REAL data. None have proven they print money.

## Goal
Go from $9.93 to $1000 through autonomous trading. Every strategy must pass honest backtest before deployment.

## User Stories

### US1: Real Backtest Engine
As a quant, I need a backtest engine that uses REAL Kalshi historical candlestick data and REAL orderbook data so I know strategies actually work before deploying.

Acceptance:
- Fetches real candlesticks from Kalshi API for settled markets
- Simulates trades with real spread costs (3c per trade)
- Reports honest WR, Sharpe, PnL per strategy
- Marks strategies PASS/FAIL clearly
- Zero synthetic data, zero fabricated results

### US2: Strategy Fix & Optimization
As a quant, I need broken strategies fixed and working strategies optimized against real data.

Acceptance:
- All 10 strategies compile and run without errors
- Strategy configs are tuned based on backtest results
- Best parameters found through grid search (not hand-tuned)

### US3: Autonomous Scan Mode
As a trader, I want the system to scan Kalshi every 60 seconds, find signals, print opportunities.

Acceptance:
- Runs `kalshi_main.py --scan` with real data
- Shows top signals from all 10 strategies
- Shows expected value per signal
- Runs unattended

### US4: Autonomous Trading Loop
As a trader, I want the system to place orders autonomously 24/7 with risk controls.

Acceptance:
- Max $50 daily loss circuit breaker
- Kelly-based position sizing
- Strategies that PASS backtest trade automatically
- Strategies that FAIL don't trade
- Trades logged to SQLite

### US5: Self-Improvement Loop
As a quant, I want the system to auto-retest strategies every 6 hours and update what works.

Acceptance:
- Cron job runs every 6h
- Re-runs backtest on newest data
- Enables strategies that newly pass, disables those that regress
- Logs performance delta

## Technical Constraints
- Kalshi API: api.elections.kalshi.com/trade-api/v2
- Auth: RSA-PSS, key_id=REDACTED_KALSHI_KEY_ID
- Balance: $9.93 — micro-size everything ($1-3 trades)
- Kalshi candles: 1min, 60min, 1440min available
- Spread: minimum 1c each way = 2c round trip

## Success Metrics
- At least 3 strategies PASS backtest with WR>52%, Sharpe>0.3, trades>20
- Scan mode shows real, actionable signals
- At least 1 trade placed in autonomous mode
- System runs for 24h without human intervention
