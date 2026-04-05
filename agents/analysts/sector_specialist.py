"""
Sector Specialist analyst node.

Maps the current business cycle phase + sentiment to the optimal SPDR
sector ETF for rotation, using research-backed cycle allocation tables
and LLM reasoning to refine the recommendation.

Classic business-cycle sector rotation (Fidelity/CFRA mapping):
  expansion  → Technology (XLK), Consumer Discretionary (XLY)
  peak       → Energy (XLE), Materials (XLB)
  contraction→ Healthcare (XLV), Consumer Staples (XLP), Utilities (XLU)
  trough     → Financials (XLF), Industrials (XLI), Real Estate (XLRE)
"""
from __future__ import annotations

import logging
import os

import requests

from agents.state import MacroCycleState

logger = logging.getLogger("trading")

# Primary sector ETF per cycle phase (first entry is default)
_PHASE_SECTORS: dict[str, list[str]] = {
    "expansion":   ["XLK", "XLY"],
    "peak":        ["XLE", "XLB"],
    "contraction": ["XLV", "XLP", "XLU"],
    "trough":      ["XLF", "XLI", "XLRE"],
}

_PROMPT_TEMPLATE = """You are a sector rotation specialist.

The current business cycle analysis shows:
  Phase:      {cycle_phase} (confidence: {cycle_confidence:.0%})
  Sentiment:  {market_sentiment}

Macro environment:
{macro_summary}

Recent headlines:
{sentiment_summary}

Standard cycle rotation candidates for {cycle_phase}:
{candidates}

Instructions:
Pick the single best sector ETF from the candidates above (or justify a different
one from XLK/XLY/XLE/XLB/XLV/XLP/XLU/XLF/XLI/XLRE if clearly superior).

Respond ONLY in this exact format:
TICKER: <ETF ticker>
RATIONALE: <one sentence>"""


def sector_specialist_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: select optimal sector ETF for rotation.

    Reads:  state["cycle_phase"], state["cycle_confidence"],
            state["market_sentiment"], state["macro_summary"],
            state["sentiment_summary"]
    Writes: state["recommended_ticker"], state["sector_rationale"]
    """
    cycle_phase = state.get("cycle_phase", "expansion")
    cycle_confidence = state.get("cycle_confidence", 0.5)
    market_sentiment = state.get("market_sentiment", "neutral")
    macro_summary = state.get("macro_summary", "")
    sentiment_summary = state.get("sentiment_summary", "")
    new_errors: list[str] = []

    logger.info(
        "[SectorSpecialist] Selecting sector for phase=%s sentiment=%s",
        cycle_phase, market_sentiment,
    )

    ticker, rationale = _select_sector(
        cycle_phase, cycle_confidence, market_sentiment,
        macro_summary, sentiment_summary, new_errors,
    )

    logger.info("[SectorSpecialist] recommended=%s  rationale=%s", ticker, rationale)
    return {
        "recommended_ticker": ticker,
        "sector_rationale":   rationale,
        "errors":             new_errors,
    }


def _select_sector(
    cycle_phase: str,
    cycle_confidence: float,
    market_sentiment: str,
    macro_summary: str,
    sentiment_summary: str,
    errors: list[str],
) -> tuple[str, str]:
    candidates = _PHASE_SECTORS.get(cycle_phase, ["XLK", "XLY"])

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key and cycle_confidence >= 0.4:
        try:
            return _llm_sector(
                cycle_phase, cycle_confidence, market_sentiment,
                macro_summary, sentiment_summary, candidates, openrouter_key,
            )
        except Exception as exc:
            msg = f"SectorSpecialist LLM failed: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return _rule_based_sector(cycle_phase, market_sentiment)


def _llm_sector(
    cycle_phase: str,
    cycle_confidence: float,
    market_sentiment: str,
    macro_summary: str,
    sentiment_summary: str,
    candidates: list[str],
    api_key: str,
) -> tuple[str, str]:
    prompt = _PROMPT_TEMPLATE.format(
        cycle_phase=cycle_phase,
        cycle_confidence=cycle_confidence,
        market_sentiment=market_sentiment,
        macro_summary=macro_summary or "No macro data.",
        sentiment_summary=sentiment_summary or "No headlines.",
        candidates=", ".join(candidates),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer":  "https://alpha-trader",
        "X-Title":       "alpha_trader",
        "Content-Type":  "application/json",
    }
    body = {
        "model":       "meta-llama/llama-3.3-70b-instruct",
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens":  100,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]

    ticker = candidates[0]
    rationale = "LLM-selected based on cycle phase and sentiment."
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("TICKER:"):
            ticker = line.split(":", 1)[1].strip().upper()
        elif line.upper().startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()

    return ticker, rationale


def _rule_based_sector(cycle_phase: str, market_sentiment: str) -> tuple[str, str]:
    """Deterministic fallback: pick first candidate, adjust for sentiment."""
    candidates = _PHASE_SECTORS.get(cycle_phase, ["XLK"])

    # If sentiment is bearish, prefer defensive sectors
    if market_sentiment == "bearish" and cycle_phase in ("expansion", "peak"):
        ticker = "XLV"
        rationale = (
            f"Rule-based: bearish sentiment overrides {cycle_phase} phase — "
            "rotating to defensive healthcare (XLV)."
        )
    else:
        ticker = candidates[0]
        rationale = (
            f"Rule-based: {cycle_phase} cycle phase maps to {ticker}."
        )
    return ticker, rationale
