"""
LangGraph state definition for the Macro Cycle Engine.

All agents read from and write into this single TypedDict, which
LangGraph passes through every node in the StateGraph.
"""
from __future__ import annotations

from typing import Any, Optional
from typing_extensions import Annotated, TypedDict


def _merge_errors(left: list[str], right: list[str]) -> list[str]:
    """Reducer: accumulate errors from all nodes."""
    return (left or []) + (right or [])


class MacroCycleState(TypedDict, total=False):
    # ── Research layer ────────────────────────────────────────────────
    # Raw FRED snapshot keyed by series ID (set by leading_indicators node)
    fred_snapshot: dict[str, Any]
    # Formatted macro text for LLM prompts (set by leading_indicators node)
    macro_summary: str
    # Raw Reuters/Google News headlines (set by lagging_indicators node)
    headlines: list[dict[str, str]]
    # Formatted sentiment text for LLM prompts (set by lagging_indicators node)
    sentiment_summary: str

    # ── Analyst layer ─────────────────────────────────────────────────
    # Determined cycle phase: "expansion" | "peak" | "contraction" | "trough"
    cycle_phase: str
    # Confidence score for cycle_phase (0.0 – 1.0)
    cycle_confidence: float
    # Overall market sentiment: "bullish" | "neutral" | "bearish"
    market_sentiment: str
    # Recommended sector ETF ticker (e.g. "XLK", "XLV", "XLU")
    recommended_ticker: str
    # Rationale for the sector recommendation
    sector_rationale: str

    # ── Trade layer ───────────────────────────────────────────────────
    # Fraction of buying power to allocate (0.0 – 1.0)
    allocation_fraction: float
    # Dollar amount to trade
    notional_value: float
    # Whether the portfolio vault approved the trade
    trade_approved: bool
    # Reason the vault blocked the trade (if trade_approved is False)
    vault_block_reason: str
    # Alpaca order ID after execution (empty string if not executed)
    order_id: str
    # Final human-readable summary of the run
    run_summary: str

    # ── Housekeeping ──────────────────────────────────────────────────
    # Errors accumulated during the run — uses a reducer so concurrent
    # nodes can each append without overwriting each other.
    errors: Annotated[list[str], _merge_errors]
