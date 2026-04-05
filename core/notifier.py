"""
Telegram notifier + health endpoint.

From the vibe coding post: "Telegram alerts every time it finds an edge or places a trade"

Sends alerts for:
  - Trade executions
  - Arb opportunities found
  - Circuit breaker triggers
  - Daily PnL summaries
  - Error conditions

Setup:
  1. Create a bot via @BotFather on Telegram → get TELEGRAM_BOT_TOKEN
  2. Get your chat ID: message the bot, then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates
  3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Health endpoint extended in metrics server: /health returns JSON status.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger("trading")

_TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self,
                 token: str | None = None,
                 chat_id: str | None = None,
                 min_interval_seconds: float = 5.0):
        self._token   = token   or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID",   "")
        self._min_interval = min_interval_seconds
        self._last_sent: float = 0.0
        self._session = requests.Session()
        self._queue: list[str] = []
        self._lock   = threading.Lock()

        if not self._token or not self._chat_id:
            logger.info("Telegram not configured — alerts disabled (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    # ------------------------------------------------------------------
    # Public alert methods
    # ------------------------------------------------------------------

    def trade(self, strategy: str, ticker: str, side: str,
              price: float, size: float, pnl: float | None = None) -> None:
        side_emoji = "🟢" if side.upper() in ("BUY", "YES") else "🔴"
        pnl_str = f"  PnL: ${pnl:+.2f}" if pnl is not None else ""
        self._send(
            f"{side_emoji} *TRADE* [{strategy}]\n"
            f"`{ticker}`  {side.upper()}  ${size:.2f} @ {price:.3f}{pnl_str}"
        )

    def arb(self, arb_type: str, ticker: str, profit_usdc: float,
            roi: float) -> None:
        self._send(
            f"⚡ *ARB* [{arb_type}]\n"
            f"`{ticker}`  profit=${profit_usdc:.4f}  ROI={roi:.1%}"
        )

    def signal(self, strategy: str, question: str, edge: float,
               price: float, size: float) -> None:
        self._send(
            f"📡 *SIGNAL* [{strategy}]\n"
            f"{question[:60]}\n"
            f"edge={edge:+.1%}  price={price:.3f}  size=${size:.2f}"
        )

    def circuit_breaker(self, reason: str, daily_pnl: float) -> None:
        self._send(
            f"🛑 *CIRCUIT BREAKER*\n"
            f"{reason}\n"
            f"Daily PnL: ${daily_pnl:+.2f}"
        )

    def daily_summary(self, pnl: float, trades: int,
                      win_rate: float, equity: float) -> None:
        trend = "📈" if pnl >= 0 else "📉"
        self._send(
            f"{trend} *DAILY SUMMARY*\n"
            f"PnL: ${pnl:+.2f}  |  Trades: {trades}  |  WR: {win_rate:.0%}\n"
            f"Equity: ${equity:.2f}"
        )

    def error(self, component: str, message: str) -> None:
        self._send(f"❗ *ERROR* [{component}]\n`{message[:200]}`")

    def startup(self, mode: str, strategies: list[str]) -> None:
        strat_list = "\n".join(f"  • {s}" for s in strategies)
        self._send(
            f"🚀 *BOT STARTED* [{mode}]\n"
            f"Strategies:\n{strat_list}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        if not self.enabled:
            logger.debug("Telegram [disabled]: %s", text[:60])
            return

        # Rate limiting
        now = time.time()
        if now - self._last_sent < self._min_interval:
            with self._lock:
                self._queue.append(text)
            return

        self._dispatch(text)

    def _dispatch(self, text: str) -> None:
        try:
            url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
            self._session.post(url, json={
                "chat_id":    self._chat_id,
                "text":       text,
                "parse_mode": "Markdown",
            }, timeout=5)
            self._last_sent = time.time()
        except Exception as e:
            logger.debug("Telegram send failed: %s", e)

    def flush_queue(self) -> None:
        """Call periodically to drain the rate-limited queue."""
        with self._lock:
            pending = self._queue[:]
            self._queue.clear()
        for msg in pending:
            self._dispatch(msg)
            time.sleep(self._min_interval)


# ------------------------------------------------------------------
# Null notifier (for dry-run / testing — same interface, no network calls)
# ------------------------------------------------------------------

class NullNotifier:
    """Drop-in replacement when Telegram is not configured."""
    enabled = False

    def trade(self, *a, **kw): pass
    def arb(self, *a, **kw): pass
    def signal(self, *a, **kw): pass
    def circuit_breaker(self, *a, **kw): pass
    def daily_summary(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def startup(self, *a, **kw): pass
    def flush_queue(self): pass


def make_notifier() -> TelegramNotifier | NullNotifier:
    """Return a configured notifier or NullNotifier if creds missing."""
    n = TelegramNotifier()
    return n if n.enabled else NullNotifier()
