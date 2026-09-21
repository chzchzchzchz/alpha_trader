# Security

## Reporting a vulnerability

Please open a private security advisory on GitHub
(Security → Advisories → "Report a vulnerability") rather than a public issue.
You should get a response within a week.

## Secrets

No credentials are stored in this repository. Configure everything through
environment variables (see `.env.sample`):

| Variable | Purpose |
|---|---|
| `KALSHI_API_KEY_ID` | Kalshi API key identifier |
| `KALSHI_API_KEY_FILE` | Path to the RSA private key (`*.pem`, git-ignored) |
| `OPENROUTER_API_KEY` | LLM access for the research / debate agents |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional alerts |

## Live-trading safety interlock

Every order to the production Kalshi API passes through
`core/trading_mode.py`. Real orders are refused unless **both** the calling
script asks for live mode **and** the environment contains
`LIVE_TRADING_ARMED=I_ACCEPT_REAL_MONEY_LOSS`. The environment can force paper
mode (`KALSHI_DEMO=true` or `TRADING_MODE=paper`) but can never force live.
Reads, balance checks and order *cancellation* are never blocked, so the
emergency scripts (`emergency_cancel.py`, `cancel_all_orders.py`) always work.

Tests for the full truth table live in `tests/test_trading_mode.py`.
