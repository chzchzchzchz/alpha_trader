# Alpha Trader — Autonomous Trading System PRD

## 1. Overview

Alpha Trader is a fully autonomous Kalshi trading system that runs 24/7 without human intervention. It aggregates 10 strategies, manages risk, reconciles positions, and logs all activity to SQLite. The system is designed to scale capital from $10 → $1000 through consistent, small-edge trades.

## 2. Core Components

- **KalshiClient**: RSA-PSS signed API wrapper (Kalshi native authentication)
- **WalletAnalyzer**: Fetches markets, transforms API response into typed `MarketStats` objects with compatibility layer for dict access.
- **StrategyOrchestrator**: Loads all strategies (10 total), generates signals, deduplicates, and allocates capital.
- **RiskManager**: Enforces exposure limits (total capital, per-category 25%, per-strategy 20%, single position 10%).
- **AutoSalesEngine**: Universal exits: stop-loss -5c, take-profit +10c, max hold 30d, strategy-specific rules.
- **Reconciliation**: Validates DB vs. Kalshi positions each cycle, reports mismatches.
- **Autonomous Loop**: Main cycle (configurable interval, default 60s):
  1. Reconciliation
  2. Auto-sales scan + execute exits
  3. Fetch markets
  4. Generate signals
  5. Allocate capital (with risk filter)
  6. Place orders + log to DB
  7. Sleep

## 3. Strategies (10)

1. `near_zero`: Yes contracts <= 8¢, high volume, 5-45d to close. High Sharpe.
2. `category_specialist`: Concentrates capital in categories with >55% win rate from own fill history.
3. `convergence`: 60-96% probability markets, high volume, low spread, mean-reverting flow.
4. `late_window`: Snipe markets in final 90 seconds with YES bid >= 93¢. Small size.
5. `flash_crash`: Detect drops >=30c in 10s window, buy bounce, TP +10c, SL -5c.
6. `longshot`: Cheap (1-5¢) longshots across categories, 1 contract each, diversify.
7. `overreaction_reversal`: Fade news-driven moves, wait 2min, bet on partial recovery.
8. `panic_sniper`: Buy dip after cascading 20%+ drop, expect mean-reversion.
9. `smart_money`: Follow OpenRouter-predicted high edge trades (optional).
10. `time_sniper`: Exploit off-hours (3-6am ET) wide spreads.

All strategies output `UnifiedSignal(ticker, strategy, side, price, score, edge)`.

## 4. Data Model (SQLite)

- `trades`: Every order placed. Columns: ts, strategy, ticker, side, price_cents, contracts, order_id, status, demo, closing_trade, exit_ts, exit_price_cents, exit_status, pnl_cents.
- `positions`: Open positions view (populated from trades where closing_trade IS NULL). Columns: ticker (PK), strategy, side, entry_price_cents, contracts, entry_ts, order_id, status.
- `pnl_daily`: Rollup by date (gross, fees, net).
- `signals`: Signal audit trail.

## 5. Configuration

`.env` variables:

```
KALSHI_DEMO=true|false          # Use Kalshi demo or live
KALSHI_EMAIL=user@example.com
KALSHI_PASSWORD=secret
ALPHA_TRADER_DB=/path/to/alpha_trader.db
CYCLE_INTERVAL=60               # Seconds between cycles
MAX_RETRIES=3
CIRCUIT_BREAKER=5
CIRCUIT_BREAKER_TIMEOUT=300
CAPITAL=500.0                   # Starting capital in dollars
OPENROUTER_API_KEY=sk-...       # Optional for smart_money
```

## 6. Error Handling & Reliability

- Circuit breaker: After N consecutive failures, pause for timeout.
- Retry with exponential backoff on order placement.
- All exceptions caught and logged; cycle continues unless fatal.
- Graceful shutdown on SIGINT/SIGTERM: finish cycle then exit.

## 7. Deployment

- **Location**: `~/sandbox/alpha_trader_isolated/`
- **Install**: `python3 -m pip install -r requirements.txt` (includes `kalshi-python`, `python-dotenv`, `PyYAML`).
- **Run manually**: `python3 -m kalshi.autonomous_loop`
- **Cron**: `crontab -l` to install. Template in `setup_cron.sh`.

## 8. Monitoring

- Logs: `logs/autonomous_loop.log` (rotating, 10MB x5)
- DB queries:
  ```sql
  SELECT * FROM trades ORDER BY ts DESC LIMIT 10;
  SELECT ticker, SUM(CASE WHEN side='yes' THEN contracts ELSE -contracts END) as net FROM positions GROUP BY ticker;
  ```
- SMS alerts: Optional integration via TextBelt (add `TEXTBELT_KEY`).

## 9. Risk Controls

- Kelly-based sizing with score weighting.
- Per-category exposure cap 25%.
- Total exposure never exceeds available capital.
- Universal exits on every position.

## 10. Future Enhancements

- Polymarket migration (US geo-block circumvention pending).
- MiroFish swarm intelligence overlay.
- Real-time WebSocket market feed.
- Reinforcement learning optimizer.
- Multi-account rotation for scaling.

---

**Status**: Production-ready. All 10 strategies implemented, tested with mock data. Ready for live credentials + cron.
