# alpha_trader Documentation

## Quick Start

1. Clone the repository.
2. Copy `.env.sample` to `.env` at the project root and fill in your keys.
3. (Python) Install dependencies: `pip install -r requirements.txt`
4. (Java) Compile: `./scripts/build.sh`
5. Start the system: `./scripts/run.sh`

## Sample .env

```
PUSHBULLET_TOKEN=your-pushbullet-token-here
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-smtp-user
SMTP_PASS=your-smtp-password
ALPACA_KEY=your-alpaca-key
ALPACA_SECRET=your-alpaca-secret
VAR_THRESHOLD=0.03
```

## Prometheus/Grafana Stack

To start monitoring stack:

```
docker-compose up -d prometheus grafana
```

## Tailing Logs

```
tail -f logs/trading.log
```

## Notes
- All dependencies are pinned in requirements.txt and pom.xml.
- No Homebrew or sudo required for any step.
- SQLite DB is at cache/historical.db.
- All logs are in logs/.
- For more, see docs/ARCHITECTURE.md and docs/OPERATIONS.md.
