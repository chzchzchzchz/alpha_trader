# PRD: Autonomous Kalshi Trading System v18 — Continuous Backtest + Research + Trade

## Overview
Build a fully autonomous Kalshi trading system with:
1. **CEMBER research agent** — ALWAYS running, ALWAYS backtesting strategies on real data
2. **CEO gateway** — only trades that pass backtest validation + CEO approval execute
3. **EXEC layer** — live trading with real price logic, anti-dup, stale cleanup
4. **SELF-IMPROVE** — auto-adjusts strategy params based on backtest results

## Current State (v17)
- ✅ Real backtest validation layer working (75-94% WR on real Kalshi data)
- ✅ Price logic fixed (NO now places at correct NO ask price)
- ✅ Stale order purge working
- ✅ Dashboard on port 8001
- ✅ 2 real fills executed
- ❌ No dedicated research subagent
- ❌ No CEO approval layer
- ❌ No self-improvement loop
- ❌ Only scanning 14 weather series

## v18 Architecture

### Agent 1: RESEARCH (Always Running)
- Runs in separate process, never stops
- Scans ALL 9464 Kalshi series for opportunities
- Downloads historical candlestick data
- Backtests every strategy variation
- Outputs validated signals to SQLite
- Auto-adjusts parameters when strategy regresses

### Agent 2: CEO GATEWAY (Decision Layer)
- Receives signals from Research + Trader + MiroFish + FUT
- Cross-validates: requires 2+ sources agree
- Only approves trade if:
  - Backtest WR >= 50% on >= 10 markets
  - Expected profit >= 5c after fees
  - Not in cooldown
  - Daily loss limit not hit
- Logs every decision (approve/reject + reason)

### Agent 3: EXECUTOR (Live Trading)
- ONLY executes CEO-approved signals
- Real price logic (YES ask, NO ask correct)
- Anti-dup, stale cleanup, portfolio coherence
- Real-time fill tracking

### Agent 4: SELF-IMPROVE (Cron, every 6h)
- Re-runs all backtests with fresh data
- Compares new WR/PnL vs historical baseline
- If strategy WR drops below threshold → disables strategy
- If new strategy passes → enables it
- Saves learnings to memory

## Success Metrics
- 3+ strategies with validated WR >= 50% on real data
- At least 10 real fills with positive cumulative PnL
- $9.84 → $15 within 7 days
- Zero crashes, runs continuously
