# PRD: Autonomous Kalshi Trading System — Full Stack v2

## Executive Summary
Build a 4-agent autonomous trading system that runs 24/7, discovers alpha, validates signals via backtesting, debates every trade, and self-improves. Currently at $9.84 from $10 start. Goal: $15+.

## Current State (Honest Assessment)
- **Balance**: $9.84 (from $10.00) — down $0.16
- **Trades executed**: 8 fills (6x >42°F, 1x >55°, 1x 54-55°) — these are weather markets settling tonight/tomorrow
- **Trades placed**: ~50+ orders (many duplicates before fix)
- **Backtest validation**: Working — 75-94% WR on REAL historical data
- **Daily loss hit**: YES at $1.65 — the limit works

### What's Running (5 agents)
1. ✅ autonomous_trader.py — v15.1 with backtest validation, 5 safety rules
2. ✅ research_subagent.py — Finds alpha but BROKEN (API returns settlement prices not historical)
3. ✅ debate_team.py — Running but no proposals to debate
4. ✅ self_improve.py — Running, SQL schema fixed
5. ✅ gui/dashboard.py — Live on port 8001

### Critical Problems
1. **Research agent is useless**: Can't backtest because `status=settled` returns post-resolution prices (bid=0, ask=1), not historical trading data
2. **Trader placing bad NO orders**: Bought NO at 30c on markets where NO costs 70c+ (price logic bug partially fixed but orders still resting unfilled)
3. **No signal flow between agents**: Research finds nothing → no debate → trader falls back to its own scan
4. **Open market scanning doesn't work**: Research scans 2000 markets but the volume fields are empty for most (MVE sports markets)
5. **Strategy too concentrated**: ALL signals are "buy NO on cheap YES" — no diversification

## Architecture (How It Should Work)

```
┌─────────────────────┐     ┌──────────────────┐     ┌──────────────┐
│   RESEARCH AGENT    │────▶│  DEBATE TEAM     │────▶│   EXECUTOR   │
│ • Scans open markets│     │ • Bull/Bear args │     │ • Places     │
│ • Swarm analysis    │     │ • Consensus      │     │   orders     │
│ • Expected PnL calc │     │ • Risk scoring   │     │ • Tracks     │
│   (no fake BT)      │     │   thresholds     │     │   fills      │
└─────────────────────┘     └──────────────────┘     └──────────────┘
         │                         │                        │
         └─────────────────────────┼────────────────────────┘
                                   │
                          ┌────────────────┐
                          │ SELF-IMPROVE   │
                          │ • Re-evals     │
                          │   strategies   │
                          │ • Adjusts      │
                          │   params       │
                          └────────────────┘
```

## What Needs to Happen (In Order)

### 1. FIX Research Agent (15 min)
- Stop trying to backtest with settled market data (API doesn't support it)
- Instead: scan open markets, run swarm analysis, calculate expected PnL
- Output: `{ticker, side, strategy, expected_pnl, score}`
- Filter: ONLY high-conviction signals (swarm edge > 10%, expected PnL > 5c)

### 2. FIX Trader Execution (10 min)
- Real NO price: `100 - yes_bid_cents` (NOT `swarm_yes * 100`)
- If NO market price > 40c → SKIP (too expensive for binary options)
- If YES market price > 15c → only if swarm confidence > 60%
- Max 1 order per market, not per cycle
- Cancel unfilled orders after 2 cycles

### 3. Wire Debate Team (10 min)
- Read proposals from research DB
- Bull argues for (backtest pass + high expected PnL = bullish)
- Bear argues against (low volume, binary risk, fee drag = bearish)
- Only PASS signals (>70% consensus) reach executor

### 4. Wire Executor to Debate (5 min)
- Instead of scanning markets itself, READS from debate_decisions table
- Only executes verdict=PASS proposals
- Still applies own safety checks (cooldown, coherence, daily limit)

### 5. Self-Improve Integration (5 min)
- Every 10 min, analyze which strategies produced fills vs which just placed orders
- Auto-adjust entry thresholds based on real fill rates (not backtests)

### 6. HFT Micro-Strategy (Separate agent)
- Monitor orderbook for mispriced bids/asks
- Snipe when spread > 10c on liquid markets
- Auto-cancel if not filled within 10 seconds

## Success Metrics
- **7 days**: $9.84 → $15.00
- **Daily**: 3-5 validated trades with 60%+ win rate
- **Fill rate**: >30% of placed orders actually fill
- **Zero**: Contradictory positions, spam orders, crashes
- **Autonomous**: Runs 24/7 with zero manual intervention

## Risk Controls
- Daily loss cap: $1.50 (22% of bankroll at $9.84)
- Max concurrent orders: 3
- Max per-trade exposure: 15c
- Portfolio coherence: No opposing sides on same underlying
- Cooldown: 30min after filled trade on same ticker
