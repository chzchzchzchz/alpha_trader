# alpha_trader

A Python-based algorithmic trading system with a **Macro Cycle Engine** that
uses a LangGraph multi-agent pipeline to perform data-driven sector rotation.
LLMs reason over live FRED macroeconomic data and Reuters RSS headlines;
deterministic Python handles all position sizing and risk management.

---

## Architecture Overview

```
FRED API ──► leading_indicators ──► lagging_indicators
                                           │
                              ┌────────────▼────────────┐
                              │   cycle_economist        │  ← deep-think LLM
                              │   (qwen/qwen3-plus:free) │    (Yield Curve,
                              └────────────┬────────────┘     CPI, UNRATE)
                                           │
                              ┌────────────▼────────────┐
                              │   sentiment_reader       │  ← quick-think LLM
                              │(step-3.5-flash:free)     │    (Reuters RSS)
                              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │   sector_specialist      │  ← maps phase → ETF
                              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │   portfolio_vault        │  ← Kelly sizing
                              │   (circuit breaker)      │    VIX check
                              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │   trader_executor        │  ← Alpaca order
                              └─────────────────────────┘
```

The pipeline runs sequentially so every agent reads the complete state written
by all prior agents — no fan-in complexity.

---

## Quick Start

### 1 — Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.13 |
| pip | bundled with Python |

```bash
pip install -r requirements.txt
```

### 2 — Environment variables

Copy the sample and fill in your keys:

```bash
cp .env.sample .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `FRED_API_KEY` | Yes | Free from [fred.stlouisfed.org](https://fred.stlouisfed.org/) |
| `OPENROUTER_API_KEY` | Recommended | Free tier at [openrouter.ai](https://openrouter.ai/) |
| `ALPACA_API_KEY` | Yes (live/paper) | [alpaca.markets](https://alpaca.markets/) |
| `ALPACA_SECRET_KEY` | Yes (live/paper) | Alpaca secret |
| `ALPACA_BASE_URL` | No | Defaults to paper-trading URL |
| `TELEGRAM_BOT_TOKEN` | No | For trade & circuit-breaker alerts |
| `TELEGRAM_CHAT_ID` | No | Your Telegram chat ID |
| `DEEP_THINK_LLM` | No | Override the Cycle Economist model |
| `QUICK_THINK_LLM` | No | Override the Sentiment Analyst model |
| `THOUGHT_SIGNALS` | No | Set `true` to enable chain-of-thought logging |

### 3 — Run directly

```bash
python macro_main.py
```

Exit codes: `0` = success / trade approved, `2` = vault blocked the trade,
`1` = unhandled exception.

---

## Docker (Recommended for 24/7 operation)

Docker isolates your API keys and guarantees the Python 3.13 environment
stays pristine. The `restart: always` policy brings the engine back online
automatically after a crash or VPS reboot.

```bash
# Build and start in the background
docker compose up -d

# Tail live logs
docker compose logs -f

# Stop
docker compose down
```

Logs are persisted to `./logs/` on the host even after container restarts.

---

## Smart Routing — Two-Tier LLM Selection

The engine uses two purpose-built models via [OpenRouter](https://openrouter.ai/):

| Role | Default model | Purpose |
|------|---------------|---------|
| **Deep Thinker** (`DEEP_THINK_LLM`) | `qwen/qwen3-plus:free` | Cycle Economist — reasons over Yield Curve inversions, CPI, and Unemployment |
| **Quick Thinker** (`QUICK_THINK_LLM`) | `stepfun/step-3.5-flash:free` | Sentiment Analyst — fast summarisation of Reuters RSS headlines |

Both models are free on OpenRouter. Override them in `.env` or `docker-compose.yml`
without touching code.

### Thought Signals (chain-of-thought audit)

Set `THOUGHT_SIGNALS=true` in your environment. The Cycle Economist will emit a
`THINKING:` block in its response — citing `T10Y2Y`, `CPI`, and `UNRATE` values
— before its final verdict. This lets you audit *why* the bot classifies a phase
as "Late Cycle" rather than taking its word for it.

```
THINKING: T10Y2Y=-0.42 (inverted → contraction signal); CPIAUCSL=3.2 (elevated,
  confirms peak pressure); UNRATE=3.9 (still low — lagging indicator trap risk:
  unemployment lags the cycle; do not over-weight this alone)
PHASE: contraction
CONFIDENCE: 0.68
RATIONALE: Inverted yield curve (-0.42) and elevated CPI (3.2%) confirm late-
  cycle contraction; unemployment not yet confirming but T10Y2Y takes precedence.
```

---

## Risk Management & Position Sizing

### Kelly Criterion

The Portfolio Vault sizes every rotation using **quarter-Kelly** (25 % of full
Kelly) to reduce variance while maintaining positive expected value:

```
f* = (p · (b + 1) − 1) / b        # full Kelly
allocation = f* × 0.25             # quarter-Kelly
```

Where `p` = `cycle_confidence` (from the Cycle Economist) and `b = 2.0`
(sector ETF rotation assumed to offer 2:1 upside).

### Circuit Breaker

Two conditions immediately halt trading and send a Telegram alert:

| Trigger | Threshold |
|---------|-----------|
| Kelly allocation too large | > 20 % of portfolio equity in one rotation |
| Market too volatile | VIX ≥ 35 (fetched from FRED `VIXCLS`) |

### Sharpe & Sortino Ratios

`core/risk_engine.RiskEngine` exposes static helpers for post-hoc analysis:

```python
from core.risk_engine import RiskEngine

# Sharpe: (mean_return - risk_free) / std(returns)
sharpe = RiskEngine.sharpe_ratio(daily_returns, risk_free_rate=0.0)

# Sortino: penalises only downside volatility
sortino = RiskEngine.sortino_ratio(daily_returns, risk_free_rate=0.0)

# Volatility scaling: reduce size proportionally when VIX spikes
scaled = RiskEngine.volatility_scaled_size(
    base_size=10_000, current_vol=0.35, target_vol=0.20
)
```

### Five-Gate Pre-Trade Risk Engine

Every Kalshi/prediction-market trade additionally passes through
`core/risk_engine.RiskEngine`:

1. **Kelly** — positive expected value above minimum threshold
2. **Liquidity** — sufficient 24 h volume to absorb the trade
3. **Correlation** — not over-exposed to correlated outcomes
4. **Concentration** — per-market, per-category, and total limits
5. **Drawdown** — within daily and total drawdown limits

---

## Sector Rotation Map

| Cycle Phase | Primary ETF | Alternatives |
|-------------|-------------|-------------|
| Expansion | XLK (Technology) | XLY |
| Peak | XLE (Energy) | XLB |
| Contraction | XLV (Healthcare) | XLP, XLU |
| Trough | XLF (Financials) | XLI, XLRE |

---

## Backtesting

```bash
# Set mode to "backtest" in config.yaml (already the default), then run:
python macro_main.py
```

**Date Fidelity ("Time Machine" test)** — inject a historical date via the
leading/lagging indicator nodes to ensure the agents only see data that was
available on that specific day. Useful for auditing whether the Cycle
Economist would have rotated into defensives before a market drawdown.

---

## Configuration Reference (`config.yaml`)

```yaml
macro:
  deep_think_llm: "qwen/qwen3-plus:free"       # Cycle Economist model
  quick_think_llm: "stepfun/step-3.5-flash:free"   # Sentiment Analyst model
  thought_signals: true                          # emit THINKING blocks
  max_debate_rounds: 3                           # Leading → Lagging → Trader
```

---

## Monitoring

```bash
# Tail live logs
tail -f logs/trading.log

# Or inside Docker
docker compose logs -f
```

Telegram alerts fire on:
- Trade executions
- Circuit breaker triggers (VIX spike or oversized rotation)
- Daily P&L summaries
- Error conditions

---

## Project Layout

```
alpha_trader/
├── agents/
│   ├── analysts/
│   │   ├── cycle_economist.py     # deep-think LLM, FRED data, thought signals
│   │   ├── sentiment_reader.py    # quick-think LLM, Reuters RSS
│   │   └── sector_specialist.py   # maps phase → sector ETF
│   ├── managers/
│   │   └── portfolio_vault.py     # Kelly sizing, circuit breaker, VIX check
│   ├── researchers/
│   │   ├── leading_indicators.py  # FRED: T10Y2Y, INDPRO, HOUST, UMCSENT
│   │   └── lagging_indicators.py  # FRED: CPI, UNRATE + Reuters RSS
│   ├── trader/
│   │   └── executor.py            # Alpaca order submission
│   ├── graph.py                   # LangGraph StateGraph pipeline
│   └── state.py                   # MacroCycleState TypedDict
├── core/
│   ├── risk_engine.py             # 5-gate risk engine + Sharpe/Sortino/vol scaling
│   ├── kelly_sizer.py             # fractional Kelly position sizer
│   ├── broker.py                  # Alpaca REST client
│   ├── notifier.py                # Telegram alerts
│   └── metrics.py                 # Prometheus-compatible metrics server
├── macro/
│   ├── fred_client.py             # FRED API wrapper
│   └── reuters_rss.py             # Reuters RSS reader
├── config.yaml                    # All configuration
├── macro_main.py                  # Entry point
├── Dockerfile                     # Python 3.13 image
└── docker-compose.yml             # restart: always, env_file, log volume
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

