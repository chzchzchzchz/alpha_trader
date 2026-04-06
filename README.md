# Kalshi Trading Bot

Institutional-grade Kalshi prediction market trading system.

US-legal. CFTC-regulated. Kalshi-native only.

## Quick Start

```bash
cd kalshi-trading-bot
pip install -r requirements.txt

# Dry-run scan
python kalshi_main.py --scan

# Profile view
python kalshi_main.py --profile

# Live trading (demo mode)
python kalshi_main.py
```

## Environment Setup

```bash
# Kalshi (required)
export KALSHI_API_KEY_ID=your-key-id
export KALSHI_API_KEY_FILE=/path/to/rsa-private-key.pem
export KALSHI_DEMO=true

# Optional: LLM forecasting
export OPENROUTER_API_KEY=sk-or-...

# Optional: Telegram alerts
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
```

## 6 Trading Strategies

| Strategy | Edge | Holding Period |
|---|---|---|
| **Near-Zero Accumulation** | Smart money at 2-8c | 5-45 days |
| **Category Specialist** | Win-rate based category rotation | 1-30 days |
| **7-Filter Convergence** | Multi-factor probability scoring | <=14 days |
| **Late-Window Snipe** | Near-certainty in final 90s | <2 min |
| **Flash Crash Reversion** | Mean reversion on 30c+ drops | <10 min |
| **Longshot Diversification** | Cheap contracts across 50+ markets | 1-30 days |

## Architecture

```
kalshi_main.py
├── WalletAnalyzer (market data, opportunity detection)
├── KalshiExecutor (order placement, position tracking)
├── KalshiClient (RSA-signed REST API)
│
├── strategies/
│   ├── near_zero.py           (buy 2-8c, sell at 3x)
│   ├── category_specialist.py (win-rate based rotation)
│   ├── convergence.py         (7-filter multi-factor)
│   ├── late_window.py         (snipe final 90 seconds)
│   ├── flash_crash.py         (mean reversion on panic)
│   └── longshot.py            (cheap contract diversification)
```

## Risk Management

- Max daily loss circuit breaker ($50 default)
- Per-strategy position limits
- Kelly-based sizing (0.25 fraction)
- Stop-loss on NearZero and Flash Crash strategies

## Status: DEMO

Running on Kalshi demo API. No real money at risk.
