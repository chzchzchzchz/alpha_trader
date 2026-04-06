# PRD: Autonomous Kalshi Trading System v17 — The Complete Stack

## Vision
Build a fully autonomous trading machine with 4 independent agents running 24/7:
1. **RESEARCHER** — Always scanning 9489 Kalshi series, backtesting strategies on REAL historical data, proposing validated alpha signals
2. **CEMBER (Debate Team)** — Bull and Bear agents argue every proposed signal, only trades with consensus pass
3. **EXECUTOR** — Live trading with proper price logic, anti-spam, stale cleanup, portfolio coherence
4. **SELF-IMPROVE** — Auto-adjusts strategy parameters based on backtest results, disables losing strategies, enables winning ones

## Current State (v16)
- ✅ Trader executing with backtest validation and 5 safety rules
- ✅ Research subagent scanning all 9489 series, found first alpha (KXHIGHCHI 100% WR)
- ✅ Balance: $9.90 (from $10.00)
- ❌ No debate/validation layer for signals
- ❌ No self-improvement loop
- ❌ No real orderbook/HFT sniping
- ❌ Research proposals don't flow to trader automatically

## Architecture

### Agent 1: RESEARCH (research_subagent.py — already running)
- Scans Kalshi markets in real-time
- Runs backtests on settled market history
- Outputs: `{ticker, side, strategy, bt_wr, bt_pnl, expected_pnl, score}`

### Agent 2: DEBATE TEAM — NEW
- Receives proposals from Research
- Bull agent argues FOR the trade (catalysts, edge, asymmetric risk)
- Bear agent argues AGAINST (risks, fees, overfitting, market maker traps)
- Only trades with Bull + Bear consensus execute

### Agent 3: EXECUTOR (autonomous_trader.py — already running, needs debate integration)
- Pulls approved signals from debate team
- Executes orders with proper price logic
- Tracks fills, stale orders, daily PnL

### Agent 4: SELF-IMPROVE (cron, every 6h)
- Re-runs all backtests with newest data
- Auto-disables strategies with declining WR
- Auto-adjusts entry/exit thresholds
- Writes performance updates to DB

## User Stories

### US1: Research Subagent (DONE - v16)
- [x] Scans all 9489 Kalshi series
- [x] Backtests strategies on settled data
- [x] Proposes validated signals to DB

### US2: Debate Team Agent (TODO)
- [ ] Bull agent: argues for each proposal with data
- [ ] Bear agent: argues against with risk analysis  
- [ ] Consensus scoring (bull_score + bear_score ≥ threshold)
- [ ] Only approved signals reach Executor

### US3: Executor Integration (TODO)
- [ ] Executor reads approved signals from debate table
- [ ] Proper NO price calculation (100 - bid_cents)
- [ ] Max 1 order per contract per cycle
- [ ] Anti-spam: if no fill after 3 cycles, cancel and reassess

### US4: Self-Improvement Loop (TODO)
- [ ] Every 6h, re-run all strategy backtests
- [ ] If WR drops <50% → disable strategy
- [ ] If new strategy passes → enable it
- [ ] Auto-adjust entry thresholds based on fill rates

### US5: HFT Micro-Strategy (TODO)
- [ ] Monitor orderbook for mispriced bids/asks
- [ ] Snipe when spread > 10c on liquid markets
- [ ] Auto-cancel if not filled within 10 seconds

## Success Criteria
- $9.90 → $15.00 within 7 days
- Zero contradictory positions
- Fill rate >20% (currently ~3%)
- All signals pass 4-layer validation: Research → Debate → Backtest → CEO approval
- 24/7 autonomous operation with zero manual intervention

## Technical Implementation

### Database Schema (additions)
```sql
CREATE TABLE debate_decisions (
    ts INTEGER, 
    ticker TEXT, 
    side TEXT, 
    strategy TEXT,
    bull_score REAL, 
    bull_reasons TEXT,
    bear_score REAL, 
    bear_reasons TEXT,
    consensus_score REAL,
    verdict TEXT -- PASS, FAIL, WATCH
);
```

### File Structure
```
alpha_trader/
├── autonomous_trader.py      # Executor agent
├── research_subagent.py      # Research agent (running)
├── debate_team.py             # NEW: Bull/Bear agents
├── self_improve.py            # NEW: Auto-adjustment loop
├── hft_sniper.py              # NEW: Orderbook micro-strategy
├── backtest_validation_layer.py
├── gui/dashboard.py
└── data/autonomous.db
```
