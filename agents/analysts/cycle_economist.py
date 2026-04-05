"""
Cycle Economist analyst node.

Uses the deep-think LLM (default: qwen/qwen3-plus:free via OpenRouter) to
determine the current macro cycle phase (expansion / peak / contraction /
trough) from FRED indicator data.

Key design choices
------------------
* Model selection:  reads DEEP_THINK_LLM env var; falls back to the value set
  in config.yaml macro.deep_think_llm; final default is qwen/qwen3-plus:free.
* Thought signals:  when THOUGHT_SIGNALS=true the prompt asks the model to
  emit a THINKING block before its verdict, enabling audit of the reasoning.
* Lagging Indicator Trap guard:  the prompt explicitly requires the 10Y-2Y
  spread (T10Y2Y) to confirm any cycle-phase transition before committing.
"""
from __future__ import annotations

import logging
import os
import re

import requests

from agents.state import MacroCycleState

logger = logging.getLogger("trading")

_CYCLE_PHASES = ("expansion", "peak", "contraction", "trough")

# Default model; overridden by DEEP_THINK_LLM env var.
_DEFAULT_DEEP_THINK_LLM = "qwen/qwen3-plus:free"

_PROMPT_BASE = """You are a Senior Quant Researcher specialising in macro cycle analysis.
You do not use emotional language. Your outputs must prioritise Risk-Adjusted
Returns over raw profit.

FRED DATA SNAPSHOT:
{macro_summary}

Instructions — follow all rules without exception:
1. Identify the cycle phase: expansion, peak, contraction, or trough.
2. You MUST cite the specific T10Y2Y (Yield Curve 10Y-2Y spread), CPIAUCSL
   (CPI), and UNRATE (Unemployment) values from the snapshot above to justify
   your classification. Do not assert a phase transition unless T10Y2Y
   confirms it — this is the Lagging Indicator Trap guard.
3. Provide a confidence score (0.0–1.0) reflecting data quality and signal
   agreement.
4. Give a one-sentence rationale that names the specific data points used."""

_PROMPT_NO_THINKING = (
    _PROMPT_BASE
    + """

Respond ONLY in this exact format (no other text):
PHASE: <expansion|peak|contraction|trough>
CONFIDENCE: <0.0-1.0>
RATIONALE: <one sentence citing T10Y2Y, CPI, and Unemployment values>"""
)

_PROMPT_WITH_THINKING = (
    _PROMPT_BASE
    + """

Respond ONLY in this exact format (no other text):
THINKING: <cite T10Y2Y=[value], CPI=[value], UNRATE=[value]; explain how each \
supports or contradicts the phase; flag the Lagging Indicator Trap if present>
PHASE: <expansion|peak|contraction|trough>
CONFIDENCE: <0.0-1.0>
RATIONALE: <one sentence citing T10Y2Y, CPI, and Unemployment values>"""
)


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


def _thought_signals_enabled() -> bool:
    return os.getenv("THOUGHT_SIGNALS", "false").lower() in ("true", "1", "yes")


def _deep_think_model() -> str:
    return os.getenv("DEEP_THINK_LLM", _DEFAULT_DEEP_THINK_LLM)


def _llm_cycle_phase(macro_summary: str, api_key: str) -> tuple[str, float]:
    """Call OpenRouter deep-think LLM and parse the structured response."""
    use_thinking = _thought_signals_enabled()
    template = _PROMPT_WITH_THINKING if use_thinking else _PROMPT_NO_THINKING
    prompt = template.format(macro_summary=macro_summary)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer":  "https://alpha-trader",
        "X-Title":       "alpha_trader",
        "Content-Type":  "application/json",
    }
    body = {
        "model":       _deep_think_model(),
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens":  400 if use_thinking else 150,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body, headers=headers, timeout=30,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]

    phase = "expansion"
    confidence = 0.5
    for line in text.splitlines():
        line = line.strip()
        upper = line.upper()
        if upper.startswith("THINKING:") and use_thinking:
            logger.info("[CycleEconomist] Reasoning: %s", line.split(":", 1)[1].strip())
        elif upper.startswith("PHASE:"):
            raw = line.split(":", 1)[1].strip().lower()
            for p in _CYCLE_PHASES:
                if p in raw:
                    phase = p
                    break
        elif upper.startswith("CONFIDENCE:"):
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
