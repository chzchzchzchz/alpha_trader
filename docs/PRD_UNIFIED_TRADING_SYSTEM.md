# PRD: Unified Autonomous Kalshi Trading System

## Overview
A single, unified, 24/7 autonomous trading system for Kalshi prediction markets. Integrates 6 strategies, institutional risk management, real-time reconciliation, auto-exits, CRM-based personalization, and continuous self-improvement.

## Core Objectives
- **Single Repo**: All code in github.com/mrc2256/alpha_trader
- **Live Trading**: $10 → $1000, Kalshi-only (US geo-blocked, Polymarket excluded)
- **Zero Stubs**: Every component production-ready, fully edge-tested
- **24/7 Operation**: Cron-driven continuous loops, self-healing
- **Audit Trail**: Complete trade blotters, PnL, strategy attribution

## System Architecture

### 1. Main Loop: autonomous_loop.py
- Runs every minute via cron
- Fetches open Kalshi weather markets (extensible to all series)
- Calls MiroFish swarm predictor (250 agents)
- Invokes **Strategy Orchestrator**:
  - Instantiates all 6 strategies
  - Each strategy returns `should_trade()` decision
  - Selects highest-scoring strategy per market
- Builds signal dict with `strategy` key
- Executes buys via executor_v18.py
- Records signals in DB (`signals` table)

### 2. Six Kalshi Strategies
All strategies in `kalshi/strategies/`:
1. **near_zero**: Accumulation under 8¢ with smart-money volume; exits at 3× or -60% stop
2. **category_specialist**: Learns our per-category win rates; concentrates capital in >55% WR categories
3. **convergence**: Plays mean-reversion on overreactions detected via order book imbalance
4. **late_window**: Enters in final 24h with momentum and liquidity analysis
5. **flash_crash**: Buys panic dips with volume spike detection, exits on recovery
6. **longshot**: High-multiple lotto on low-probability but high-ROI mispricings

Each strategy implements:
- `should_trade(market_context, swarm_result) → bool`
- `get_position_size() → int`
- Optional `check_exits(markets_by_ticker) → list[ticker]` for active monitoring

### 3. Position Manager: position_manager.py
- Runs every minute (parallel to main loop)
- Queries all open trades from DB
- Fetches current market mids
- For each open position:
  - Calls the originating strategy's `check_exits()` if available
  - Falls back to generic exit rules: take profit 2×, stop loss -50%
- Issues market sell orders
- Updates trades with `exit_ts` and `exit_price_cents`

### 4. Position Reconciliation: position_reconciliation.py
- Runs every 5 minutes via cron
- Fetches positions directly from Kalshi API
- Compares with local DB positions (`trades` where status='open')
- Logs:
  - Missing in local (Kalshi has, DB doesn't)
  - Missing in Kalshi (DB has, API doesn't)
  - Count mismatches (side/count differences)
- Writes snapshot JSON on >10 mismatches
- Alerts via log at ERROR/CRITICAL levels

### 5. Backtest Validation Layer
- `backtest_validation.py` uses `kalshi/data_loader.py` to fetch historical
- Each strategy must pass: Sharpe > 0.7, max drawdown < 25%, win rate > 50% on sample
- Results stored in `strategy_performance` table
- Debate team weights strategies based on backtest win rate

### 6. Debate Team: debate_team.py
- Aggregates proposals from multiple agents (research_agent, executor, strategies)
- Weighting: strategy_performance.bt_wr scales proposal scores
- Fallback to heuristics if no backtest data
- Picks top-N signals for execution

### 7. Executor: executor_v18.py
- Receives signals from autonomous_loop
- Validates against current balance and position sizing
- Places orders via KalshiClient
- Writes trade to DB with `strategy` attribution
- Handles order status polling and fills

### 8. Security
- All credentials via environment variables:
  - `KALSHI_API_KEY_ID`
  - `KALSHI_API_KEY_FILE` (default `~/.kalshi/private_key.pem`)
  - `KALSHI_DEMO` (`true`/`false`)
- No hardcoded keys in code
- `.env` file ignored by git
- 1Password integration for key rotation

### 9. CRM Integration (Second Brain)
- `config.py` reads from `~/.hermes/second_brain/query.py` (or API)
- Enforces user preferences:
  - `max_trades_per_day`
  - `max_daily_loss`
  - `tax_lot_method` (FIFO/LIFO)
- Overrides strategy defaults if needed

### 10. Edge Testing & Chaos Drills
- `chaos_drill.sh`:
  - Simulate API 5xx errors
  - Simulate rate limits
  - Network dropouts
  - Database corruption
  - Kill processes randomly
- Validates recovery: retries, circuit breaker, graceful degradation

## Deployment Pipeline
1. Pre-flight: security audit, lint, tests
2. DB migrations: ensure schema up to date
3. Build: compile any deps, ensure virtualenv
4. Deploy: update crontab with new wrapper, restart agents via `scripts/start_alpha_trader.sh`
5. Smoke test: run one cycle synchronously, verify trades recorded
6. Monitor: tail logs, Grafana dashboard (optional)
7. Alert: Discord/Slack on critical errors (p excess drawdown, reconciliation failures)

## Monitoring & Alerting
- Log files: `logs/autonomous.log`, `logs/executor.log`, `logs/position_manager.log`, `logs/recon.log`
- Daily blotter: `logs/blotter_YYYY-MM-DD.csv` generated at midnight
- Key metrics:
  - Total PnL, strategy-specific PnL
  - Win rate, Sharpe ratio
  - Reconciliation discrepancy rate
  - Order fill rate, latency

## Success Criteria
- Live trading with real money, no manual intervention > 7 days
- All 6 strategies producing actionable signals daily
- Auto-reconciliation shows < 0.1% mismatch rate
- No hardcoded secrets anywhere
- System survives chaos drills with < 5 minute downtime

## Future Work (Out of Scope)
- Integration with other repos (comedy-writers-room, EdgeClaw) as separate services
- Switching to Polymarket (legal restrictions)
- Moving to Kubernetes (single-machine sufficient)

---
*Document Version: 1.0 — 2025-04-08*