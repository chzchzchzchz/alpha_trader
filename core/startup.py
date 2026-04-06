"""
Startup validation and security hardening.

Addresses the "20 things that sink vibe-coded apps":
  #11 — env var validation at startup (silent breaks in prod)
  #17 — health check endpoint
  #18 — logging in production
  #1  — rate limiting awareness

Call validate_environment() before starting any strategy.
If required vars are missing, the process exits with a clear error
rather than silently misbehaving.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

logger = logging.getLogger("trading")


# ---------------------------------------------------------------------------
# Environment variable spec
# ---------------------------------------------------------------------------

@dataclass
class EnvSpec:
    name: str
    required: bool
    description: str
    redact: bool = True   # don't log the value


_KALSHI_VARS = [
    EnvSpec("KALSHI_API_KEY_ID",  required=True,  description="Kalshi API key ID"),
    EnvSpec("KALSHI_API_KEY_FILE", required=True,  description="Path to Kalshi RSA PEM key"),
]


_LLM_VARS = [
    EnvSpec("OPENAI_API_KEY",      required=False, description="OpenAI API key"),
    EnvSpec("OPENROUTER_API_KEY",  required=False, description="OpenRouter API key (cheaper routing)"),
]

_TELEGRAM_VARS = [
    EnvSpec("TELEGRAM_BOT_TOKEN", required=False, description="Telegram bot token"),
    EnvSpec("TELEGRAM_CHAT_ID",   required=False, description="Telegram chat ID for alerts"),
]

_ALPACA_VARS = [
    EnvSpec("ALPACA_KEY",    required=False, description="Alpaca API key"),
    EnvSpec("ALPACA_SECRET", required=False, description="Alpaca secret key"),
]

ALL_VARS = _KALSHI_VARS + _LLM_VARS + _TELEGRAM_VARS + _ALPACA_VARS


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_environment(
    required_groups: list[str] | None = None,
    exit_on_failure: bool = True,
) -> dict[str, bool]:
    """
    Validate required environment variables at startup.

    required_groups: list of "kalshi", "llm", "telegram", "alpaca"
                     If None, only checks REQUIRED vars from all groups.

    Returns: dict of {group -> all_present}
    Exits process if exit_on_failure=True and required vars are missing.
    """
    group_map = {
        "kalshi":     _KALSHI_VARS,
            "llm":        _LLM_VARS,
        "telegram":   _TELEGRAM_VARS,
        "alpaca":     _ALPACA_VARS,
    }

    groups_to_check = required_groups or list(group_map.keys())
    missing_required: list[str] = []
    warnings: list[str] = []
    results: dict[str, bool] = {}

    for group_name in groups_to_check:
        specs = group_map.get(group_name, [])
        group_ok = True
        for spec in specs:
            val = os.getenv(spec.name, "")
            if not val:
                if spec.required:
                    missing_required.append(f"  {spec.name} — {spec.description}")
                    group_ok = False
                else:
                    warnings.append(f"  {spec.name} not set — {spec.description} (optional)")
            else:
                display = "<set>" if spec.redact else val
                logger.debug("  %s = %s", spec.name, display)
        results[group_name] = group_ok

    # Warn about optional missing vars
    for w in warnings:
        logger.info("Optional env var missing: %s", w.strip())

    # Hard fail on required missing vars
    if missing_required:
        msg = "Missing required environment variables:\n" + "\n".join(missing_required)
        logger.critical(msg)
        if exit_on_failure:
            print(f"\n[STARTUP FAILURE]\n{msg}\n", file=sys.stderr)
            sys.exit(1)

    logger.info("Environment validation passed for groups: %s", groups_to_check)
    return results


def check_key_files() -> list[str]:
    """Verify that referenced PEM/key files actually exist."""
    errors = []
    pem = os.getenv("KALSHI_API_KEY_FILE", "")
    if pem and not os.path.exists(pem):
        errors.append(f"KALSHI_API_KEY_FILE points to non-existent file: {pem}")
    return errors


# ---------------------------------------------------------------------------
# Health check endpoint (addresses #17 from the list)
# ---------------------------------------------------------------------------

_health_status: dict = {
    "status": "starting",
    "strategies": [],
    "uptime_seconds": 0,
    "trades_today": 0,
    "daily_pnl": 0.0,
    "errors_today": 0,
}
_start_time: float = 0.0
_health_callbacks: list[Callable[[], dict]] = []


def register_health_callback(fn: Callable[[], dict]) -> None:
    """Register a callable that returns health data to merge into /health."""
    _health_callbacks.append(fn)


def update_health(key: str, value) -> None:
    _health_status[key] = value


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        import time
        if self.path == "/health":
            data = dict(_health_status)
            data["uptime_seconds"] = int(time.time() - _start_time) if _start_time else 0
            for cb in _health_callbacks:
                try:
                    data.update(cb())
                except Exception:
                    pass
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_health_server(port: int = 8080) -> None:
    """
    Start /health endpoint on a background thread.
    Returns immediately.
    """
    import time
    global _start_time
    _start_time = time.time()
    update_health("status", "running")

    server = HTTPServer(("", port), _HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    t.start()
    logger.info("Health endpoint: http://localhost:%d/health", port)
