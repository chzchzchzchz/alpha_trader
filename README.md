# alpha_trader

Autonomous prediction-market trading system for [Kalshi](https://kalshi.com)
(CFTC-regulated, US-legal). Multi-agent research → backtest validation →
risk-gated execution, with a hard interlock so nothing trades real money by
accident.

![CI](https://github.com/mrc2256/alpha_trader/actions/workflows/ci.yml/badge.svg)

## What's in here

| Area | Entry point | Notes |
|---|---|---|
| Strategy engine | `kalshi_main.py` | 10 strategies in `kalshi/strategies/`, wallet analyzer, executor |
| Swarm trader | `autonomous_trader.py` | 250-agent opinion swarm scores weather markets; every signal is backtest-validated before an order |
| Weather oracle | `weather_oracle_v22.py` | NOAA/NWS forecast vs. market-implied temperature thresholds |
| Research agents | `research_agent.py`, `debate_team.py`, `self_improve.py` | LLM agents (OpenRouter) propose, debate and refine strategies |
| Arb / snipe scanners | `arb_scanner.py`, `arb_sniper.py`, `snipe_scanner.py`, `bracket_scanner.py` | Cross-market and late-window opportunity detection |
| Risk | `core/risk_engine.py`, `core/kelly_sizer.py`, `core/trading_mode.py` | Daily loss cap, Kelly sizing, live-trading interlock |
| Java port | `src/`, `pom.xml` | Earlier Alpaca equities version with JUnit/PIT tests |

## Quick start

```bash
pip install -r requirements-dev.txt
cp .env.sample .env        # fill in keys

python kalshi_main.py --scan      # dry-run: print opportunities, no orders
python kalshi_main.py --profile   # category win-rate profile
python kalshi_main.py             # paper trade against the Kalshi demo API
pytest                            # run the test suite
```

### Environment

```bash
KALSHI_API_KEY_ID=...                       # Kalshi key id
KALSHI_API_KEY_FILE=/path/to/private.pem   # RSA key (never committed)
OPENROUTER_API_KEY=sk-or-...               # optional, LLM agents
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...# optional alerts
```

## Live-trading interlock

Nothing in this repo places a real order unless **both** hold:

1. the script asks for live mode (`demo=False`), **and**
2. `LIVE_TRADING_ARMED=I_ACCEPT_REAL_MONEY_LOSS` is in the environment.

The environment can always force paper (`KALSHI_DEMO=true`,
`TRADING_MODE=paper`) but can never force live. Reads, balances and order
*cancellation* are never blocked, so `emergency_cancel.py` works regardless
of arming state. See `core/trading_mode.py` and `tests/test_trading_mode.py`.

## Strategies (`kalshi/strategies/`)

| Strategy | Edge | Holding period |
|---|---|---|
| Near-Zero Accumulation | Smart money at 2–8c | 5–45 days |
| Category Specialist | Win-rate based category rotation | 1–30 days |
| 7-Filter Convergence | Multi-factor probability scoring | ≤14 days |
| Late-Window Snipe | Near-certainty in final 90 s | <2 min |
| Flash Crash Reversion | Mean reversion on 30c+ drops | <10 min |
| Longshot Diversification | Cheap contracts across 50+ markets | 1–30 days |
| Overreaction Reversal, Panic Sniper, Smart Money, Time Sniper | see module docstrings | — |

## Risk management

- Daily loss circuit breaker (configurable, cents)
- Per-strategy position limits and per-ticker cooldowns
- Fractional-Kelly sizing (0.25 default)
- Backtest validation gate on every swarm signal
- Stop-loss on Near-Zero and Flash Crash

## Layout

```
kalshi/            REST client (RSA-PSS auth), scanner, wallet analyzer, strategies/
core/              risk engine, Kelly sizer, trading-mode interlock, settings
agents/            LangGraph research / debate / executor agents
backtest/          historical replay + validation layer
gui/, gateway/     FastAPI dashboard and API
tests/             pytest suite
src/               Java (Maven) equities version
```

## Status

Runs against the Kalshi **demo** API by default. Live trading has been
exercised on a small real account; see git history for the trade logs that
motivated the interlock above.

## License

MIT — see [LICENSE](LICENSE).
