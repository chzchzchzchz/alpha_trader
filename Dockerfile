# ── Alpha Trader — Macro Cycle Engine ────────────────────────────────────────
# Python 3.13 slim for a minimal, reproducible environment.
# Build:  docker build -t alpha_trader .
# Run:    docker run --env-file .env alpha_trader
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.13-slim

# Non-root user for least-privilege operation
RUN useradd --create-home --shell /bin/bash trader

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Ensure the logs directory exists and is writable by the trader user
RUN mkdir -p /app/logs && chown -R trader:trader /app

USER trader

# Default entry point: run the Macro Cycle Engine once.
# Override CMD to run a different entry point (e.g. python main.py).
CMD ["python", "macro_main.py"]
