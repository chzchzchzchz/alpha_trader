"""
Cycle Economist analyst node.

Uses the LLMForecaster to determine the current macro cycle phase
(expansion / peak / contraction / trough) from FRED indicator data.
"""
from __future__ import annotations

import logging
import os
import re

import requests

from agents.state import MacroCycleState

logger = logging.getLogger("trading")

_CYCLE_PHASES = ("expansion", "peak", "contraction", "trough")

_PROMPT_TEMPLATE = """You are a macro cycle economist.

Based on the following leading and lagging economic indicators, determine
the current phase of the US business cycle.

ECONOMIC INDICATORS:
{macro_summary}

Instructions:
1. Identify the cycle phase: expansion, peak, contraction, or trough.
2. Provide a confidence score between 0.0 and 1.0.
3. Give a one-sentence rationale.

Respond ONLY in this exact format (no other text):
PHASE: <expansion|peak|contraction|trough>
CONFIDENCE: <0.0-1.0>
RATIONALE: <one sentence>"""


def cycle_economist_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: determine business cycle phase via LLM.

    Reads:  state["macro_summary"]
    Writes: state["cycle_phase"], state["cycle_confidence"]
    """
    macro_summary = state.get("macro_summary", "No macro data available.")
    new_errors: list[str] = []

    logger.info("[CycleEconomist] Analyzing macro cycle phase")

    phase, confidence = _query_cycle_phase(macro_summary, new_errors)

    logger.info(
        "[CycleEconomist] phase=%s confidence=%.2f", phase, confidence
    )
    return {
        "cycle_phase":      phase,
        "cycle_confidence": confidence,
        "errors":           new_errors,
    }


def _query_cycle_phase(
    macro_summary: str,
    errors: list[str],
) -> tuple[str, float]:
    """Query LLM for cycle phase; fall back to rule-based heuristic."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        try:
            return _llm_cycle_phase(macro_summary, openrouter_key)
        except Exception as exc:
            msg = f"CycleEconomist LLM failed: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return _heuristic_cycle_phase(macro_summary)


def _llm_cycle_phase(macro_summary: str, api_key: str) -> tuple[str, float]:
    """Call OpenRouter LLM and parse the structured response."""
    prompt = _PROMPT_TEMPLATE.format(macro_summary=macro_summary)
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
        "max_tokens":  150,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]

    phase = "expansion"
    confidence = 0.5
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("PHASE:"):
            raw = line.split(":", 1)[1].strip().lower()
            for p in _CYCLE_PHASES:
                if p in raw:
                    phase = p
                    break
        elif line.upper().startswith("CONFIDENCE:"):
            m = re.search(r"(\d+(?:\.\d+)?)", line)
            if m:
                val = float(m.group(1))
                confidence = val if val <= 1.0 else val / 100.0

    return phase, max(0.0, min(1.0, confidence))


def _heuristic_cycle_phase(macro_summary: str) -> tuple[str, float]:
    """
    Simple rule-based fallback when no LLM key is available.

    Checks yield curve spread direction as a primary signal:
      - Positive T10Y2Y → expansion leaning
      - Negative T10Y2Y → contraction leaning
    """
    text = macro_summary.lower()
    # Look for a numeric yield curve value in the summary
    m = re.search(r"t10y2y.*?(-?\d+\.\d+)", text)
    if m:
        spread = float(m.group(1))
        if spread > 0.5:
            return "expansion", 0.55
        if spread > 0.0:
            return "expansion", 0.45
        if spread > -0.5:
            return "contraction", 0.45
        return "contraction", 0.55

    # Default when no data
    return "expansion", 0.30
