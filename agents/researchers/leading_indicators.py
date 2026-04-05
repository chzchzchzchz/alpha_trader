"""
Leading Indicators Researcher node.

Fetches FRED leading macro indicators (yield curve, industrial production,
housing starts, consumer sentiment) and stores a formatted summary in
the LangGraph state for downstream analyst agents.
"""
from __future__ import annotations

import logging

from agents.state import MacroCycleState
from macro.fred_client import FredMacroEngine, LEADING_SERIES

logger = logging.getLogger("trading")


def leading_indicators_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: fetch FRED leading indicators.

    Writes:
      state["fred_snapshot"]  — raw FRED data keyed by series ID
      state["macro_summary"]  — human-readable string for LLM prompts
    """
    logger.info("[LeadingIndicators] Fetching FRED leading indicators")

    engine = FredMacroEngine()
    new_errors: list[str] = []

    snapshot: dict = {}
    for series_id in LEADING_SERIES:
        try:
            snapshot[series_id] = engine.fetch_series(series_id, limit=3)
        except ValueError as exc:
            # Missing API key — skip gracefully so the graph can still run
            msg = f"LeadingIndicators: {exc}"
            logger.warning(msg)
            new_errors.append(msg)
            break
        except Exception as exc:
            msg = f"LeadingIndicators: failed to fetch {series_id}: {exc}"
            logger.warning(msg)
            new_errors.append(msg)

    macro_summary = engine.format_for_prompt(snapshot) if snapshot else (
        "Leading indicator data unavailable (check FRED_API_KEY)."
    )

    logger.info("[LeadingIndicators] Summary:\n%s", macro_summary)
    return {
        "fred_snapshot": snapshot,
        "macro_summary": macro_summary,
        "errors":        new_errors,
    }
