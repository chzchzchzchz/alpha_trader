"""
Lagging Indicators Researcher node.

Fetches Reuters RSS headlines for market sentiment context, and also pulls
FRED lagging/coincident indicators (CPI, unemployment) to confirm cycle phase.
"""
from __future__ import annotations

import logging

from agents.state import MacroCycleState
from macro.fred_client import FredMacroEngine, LAGGING_SERIES
from macro.reuters_rss import ReutersRSSReader

logger = logging.getLogger("trading")


def lagging_indicators_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: fetch FRED lagging indicators + Reuters headlines.

    Writes:
      state["fred_snapshot"]      — merges lagging series into existing snapshot
      state["macro_summary"]      — appended with lagging indicator values
      state["headlines"]          — list of {title, source, link} dicts
      state["sentiment_summary"]  — formatted headlines string for LLM prompts
    """
    logger.info("[LaggingIndicators] Fetching FRED lagging indicators + RSS headlines")

    engine = FredMacroEngine()
    rss = ReutersRSSReader()
    new_errors: list[str] = []

    # ── FRED lagging indicators ───────────────────────────────────────
    snapshot: dict = dict(state.get("fred_snapshot") or {})
    for series_id in LAGGING_SERIES:
        try:
            snapshot[series_id] = engine.fetch_series(series_id, limit=3)
        except ValueError as exc:
            msg = f"LaggingIndicators: {exc}"
            logger.warning(msg)
            new_errors.append(msg)
            break
        except Exception as exc:
            msg = f"LaggingIndicators: failed to fetch {series_id}: {exc}"
            logger.warning(msg)
            new_errors.append(msg)

    # Rebuild full macro summary with both leading + lagging
    macro_summary = engine.format_for_prompt(snapshot) if snapshot else (
        state.get("macro_summary", "Macro data unavailable.")
    )

    # ── Reuters RSS headlines ─────────────────────────────────────────
    headlines = rss.fetch_headlines(max_items=15)
    sentiment_summary = rss.format_for_prompt(headlines)

    logger.info(
        "[LaggingIndicators] Fetched %d headlines; macro lines: %d",
        len(headlines),
        len(macro_summary.splitlines()),
    )
    return {
        "fred_snapshot":    snapshot,
        "macro_summary":    macro_summary,
        "headlines":        headlines,
        "sentiment_summary": sentiment_summary,
        "errors":           new_errors,
    }
