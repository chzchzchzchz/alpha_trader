# PRD: Autonomous Kalshi Trading System — Full Stack Build

## Executive Summary
Building a 4-agent autonomous trading system on Kalshi. Currently 12/997 fills. Need to fix research, debate, executor, and self-improvement pipeline.

## Current State
- **Balance**: $9.16 cash + $2.55 exposure = $11.71 total (UP $1.71)
- **Trades**: 12 filled, 985 resting junk orders
- **Executors**: 5 agents running but mostly broken
- **Problems**: Research finds nothing, debate has nothing to debate, executor spams bad orders

## What We Have
✅ autonomous_trader.py — Works but has order spam bug
✅ research_subagent.py — Can't backtest (API returns settled prices not historical)
✅ debate_team.py — Written, runs, but no proposals
✅ self_improve.py — Written, runs, but no data
✅ backtest_validation_layer.py — Written but no real historical data available
✅ emergency_cancel.py — Cancels all resting orders
✅ gui/dashboard.py — Live dashboard

## What We Need
1. **Research Agent** — Find alpha in open markets, propose signals
2. **Debate Team** — Bull/Bear argue, only consensus passes
3. **Executor** — Only execute approved signals, proper price logic
4. **Self-Improve** — Auto-adjust based on real fill rates

## Plan
1. Kill all existing processes
2. Cancel all resting orders
3. Build research agent that scans open markets and proposes
4. Build debate team that reads research and votes
5. Build executor that only executes passed debates
6. Wire them all together via SQLite DB
7. Test with small stakes
8. Deploy

## Timeline
- Today: Fix executor spam, get 1 real trade working end-to-end
- Tomorrow: Full 4-agent stack running autonomously
- Day 3: Autonomous self-improvement

## Success Criteria
- Each agent runs independently
- Research proposes, debate validates, executor executes
- Zero order spam (max 3 per cycle, 1 per contract)
- Positive PnL after fees
