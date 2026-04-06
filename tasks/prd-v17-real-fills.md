# PRD: Autonomous Kalshi Engine v17 — Real Fills, Real P&L

## Problem
The autonomous trader (v16) has a critical price logic bug: it was placing NO orders at 1c when the actual NO ask was 89c. Result: 0 fills in 10+ cycles despite finding valid signals with 75-94% backtest WR.

## Root Cause
The execute() method calculated NO buy price as `int(swarm_yes * 100)` — when swarm says 0% YES, it placed NO at 0c. The REAL NO price is `100 - yes_bid_cents` = 89c.

## Fix Applied (v17)
- YES buys: pay yes_ask_cents (capped at 15c)
- NO buys: pay `100 - yes_bid_cents` (the actual NO ask)
- Skip NO-side trades where NO is expensive (>85c = market leaning YES)
- Only trade NO when NO is cheap (<=30c = market leaning NO)

## Success Criteria
1. At least 3 orders FITTED (not just placed) within 2 cycles
2. P&L moves from $0 to positive after fills settle
3. Backtest validation continues to work (all signals validated before trade)
4. Dashboard shows real fill data not just "resting" orders

## Risk Controls (unchanged)
- $1.50 daily loss cap
- 30min cooldown per ticker
- Portfolio coherence checks
- Every signal backtest-validated first

## Execution Steps
1. Kill old trader processes
2. Deploy v17 with fixed price logic
3. Verify orders fill on cycle 1-2
4. Check settlement/PnL after markets resolve
5. Iterate on any new bugs
