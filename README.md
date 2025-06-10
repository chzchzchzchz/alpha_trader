# alpha_trader

## Quick Start (No Maven/Homebrew Required)

1. Download Java 17 (portable JDK, e.g. Adoptium) and extract to your user directory if not already installed.
2. Download all required JARs listed in `docs/MANUAL_DEPENDENCIES.md` and place them in `lib/` at the project root.
3. Copy `.env.sample` to `.env` and fill in your keys (see below).
4. Build the project:
   ```bash
   ./scripts/build.sh
   ```
5. Run the main class (example):
   ```bash
   java -cp "build/classes:lib/*" com.alpha_trader.Main
   ```

## Sample .env
```
ALPACA_KEY=YOUR_ALPACA_KEY_HERE
ALPACA_SECRET=YOUR_ALPACA_SECRET_HERE
VAR_THRESHOLD=0.03
SMTP_USER=your@email.com
SMTP_PASS=yourpassword
PUSHBULLET_TOKEN=your_pushbullet_token
```

## Prometheus/Grafana One-Liner
```
docker-compose -f docker-compose.yml up -d prometheus grafana
```

## Tailing Logs
```
tail -f logs/trading.log
```

For more, see `docs/ARCHITECTURE.md` and `docs/OPERATIONS.md`.

=======
# alpha_trader
>>>>>>> 7bc9b2253b0deb8814c3cfbd21189138d047277b
