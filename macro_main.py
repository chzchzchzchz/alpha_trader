"""
macro_main.py — Macro Cycle Engine entry point.

Runs the full LangGraph pipeline once and prints the run summary.
Designed to be invoked directly (python macro_main.py) or scheduled
via cron/APScheduler for periodic sector-rotation decisions.

Required environment variables:
  FRED_API_KEY       — free from https://fred.stlouisfed.org/
  OPENROUTER_API_KEY — for LLM agent calls (optional; falls back to rules)
  ALPACA_API_KEY     — Alpaca paper/live trading key
  ALPACA_SECRET_KEY  — Alpaca secret

Optional:
  ALPACA_BASE_URL    — defaults to paper trading endpoint
  TELEGRAM_BOT_TOKEN — for Telegram alerts
  TELEGRAM_CHAT_ID   — for Telegram alerts
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# ── Ensure repo root is on sys.path when run directly ────────────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.logger import setup_logger
from core.notifier import make_notifier
from agents.graph import build_macro_graph


def _bootstrap_logger() -> None:
    """Set up minimal console logging before settings are loaded."""

    class _MinimalCfg:
        level = "INFO"
        file = "logs/trading.log"
        max_file_size = 10_485_760
        backup_count = 5

    setup_logger(_MinimalCfg())


def main() -> int:
    _bootstrap_logger()
    logger = logging.getLogger("trading")
    notifier = make_notifier()

    logger.info("=== Macro Cycle Engine starting ===")
    notifier.startup(mode="macro_cycle", strategies=["MacroCycleEngine"])

    try:
        graph = build_macro_graph()
        final_state = graph.invoke({})
    except Exception as exc:
        logger.exception("Macro Cycle Engine failed: %s", exc)
        notifier.error("MacroCycleEngine", str(exc))
        return 1

    summary = final_state.get("run_summary", "No summary generated.")
    print(summary)
    logger.info(summary)

    errors = final_state.get("errors") or []
    if errors:
        logger.warning("Run completed with %d error(s):", len(errors))
        for err in errors:
            logger.warning("  %s", err)

    # Exit 0 if the trade was approved and executed (or not yet attempted
    # because the market is closed), 2 if the vault blocked it.
    if final_state.get("trade_approved") is False:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
