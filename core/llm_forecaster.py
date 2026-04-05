"""
LLM Probability Forecaster with Platt Scaling.

Sources:
  - yigitcankzl/PolymarketSignalAgent (3-model ensemble + Platt scaling)
  - defidaddydavid/polyswarm (12-agent debate, 26 aggregation methods)
  - stormulv/PolyMarket-AI-agent-trading (superforecasting + RAG)

Key insight from research: raw LLM probability outputs systematically
hedge toward 50%.  Platt scaling with α=1.5 corrects this bias.

Pipeline:
  1. Fetch context (news headlines, market info)
  2. Query multiple LLM models independently
  3. Extract probability estimates
  4. Aggregate via median (robust to outliers)
  5. Apply Platt scaling to sharpen estimates
  6. Compare to market price → calculate edge

Models (via OpenRouter for cost efficiency):
  - Primary:  claude-sonnet-4-6 (strong reasoning)
  - Secondary: meta-llama/llama-3.3-70b-instruct (cheap, fast)
  - Tertiary:  qwen/qwen3-32b (diversity of view)

Uses OpenRouter to route cheap calls to budget models and only uses
the heavy model when reasoning depth is needed — from the vibe coding post.
"""
from __future__ import annotations

import logging
import os
import re
import statistics
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger("trading")

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENAI_BASE     = "https://api.openai.com/v1"

# Platt scaling parameter — corrects LLM 50%-bias
# Derived from yigitcankzl research: α=1.5 works well for prediction markets
_PLATT_ALPHA = 1.5


@dataclass
class ForecastResult:
    question: str
    model_estimates: dict[str, float]   # model_name -> probability
    raw_aggregate: float                # median of raw estimates
    calibrated: float                   # after Platt scaling
    confidence: float                   # std dev of estimates (lower = more agreement)
    edge: float                         # calibrated - market_price
    context_used: str                   # headlines/news used


class LLMForecaster:
    """
    Multi-model ensemble probability estimator for prediction market questions.
    """

    def __init__(self, use_openrouter: bool = True):
        self._openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self._openai_key     = os.getenv("OPENAI_API_KEY", "")
        self._session = requests.Session()
        self._use_openrouter = use_openrouter and bool(self._openrouter_key)

        # OpenRouter model routing:
        # cheap fast model for most calls, strong model for ambiguous ones
        self._models_cheap  = [
            "meta-llama/llama-3.3-70b-instruct",
            "qwen/qwen3-32b",
        ]
        self._model_strong = "anthropic/claude-sonnet-4-6"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self, question: str, market_price: float,
                 context: str = "") -> Optional[ForecastResult]:
        """
        Generate calibrated probability estimate for a yes/no question.
        Returns None if no API keys configured.
        """
        if not self._openrouter_key and not self._openai_key:
            logger.warning("No LLM API keys configured — skipping forecast")
            return None

        # Gather context if not provided
        if not context:
            context = self._fetch_news_context(question)

        # Get estimates from multiple models
        estimates: dict[str, float] = {}
        prompt = self._build_prompt(question, context, market_price)

        # Cheap models first (parallel would be ideal; sequential for simplicity)
        for model in self._models_cheap:
            est = self._query_model(model, prompt)
            if est is not None:
                estimates[model] = est

        # Use strong model only if cheap models disagree significantly
        if estimates and self._high_disagreement(list(estimates.values())):
            est = self._query_model(self._model_strong, prompt)
            if est is not None:
                estimates[self._model_strong] = est
        elif not estimates:
            # Fallback: use strong model if cheap ones all failed
            est = self._query_model(self._model_strong, prompt)
            if est is not None:
                estimates[self._model_strong] = est

        if not estimates:
            logger.warning("All models failed for: %s", question[:40])
            return None

        raw_vals = list(estimates.values())
        raw_agg  = statistics.median(raw_vals)
        calibrated = self._platt_scale(raw_agg)
        confidence = 1.0 - (statistics.stdev(raw_vals) if len(raw_vals) > 1 else 0.0)
        edge = calibrated - market_price

        logger.info(
            "Forecast: %s | raw=%.3f calibrated=%.3f market=%.3f edge=%.3f",
            question[:40], raw_agg, calibrated, market_price, edge,
        )

        return ForecastResult(
            question=question,
            model_estimates=estimates,
            raw_aggregate=raw_agg,
            calibrated=calibrated,
            confidence=confidence,
            edge=edge,
            context_used=context[:200],
        )

    def estimate_batch(self, questions: list[tuple[str, float]],
                       context_map: dict[str, str] | None = None) -> list[ForecastResult]:
        """
        Estimate probabilities for multiple questions.
        questions: list of (question_str, market_price)
        """
        results = []
        for question, price in questions:
            context = (context_map or {}).get(question, "")
            result = self.estimate(question, price, context)
            if result:
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # Platt Scaling
    # ------------------------------------------------------------------

    @staticmethod
    def _platt_scale(p: float, alpha: float = _PLATT_ALPHA) -> float:
        """
        Apply Platt scaling to sharpen a probability estimate.

        LLMs systematically output values near 0.5 (hedging bias).
        Platt scaling with α > 1 pushes probabilities away from 0.5.

        Formula: p' = p^α / (p^α + (1-p)^α)

        α=1.0 → identity (no change)
        α=1.5 → moderate sharpening (research-validated for prediction markets)
        α=2.0 → aggressive sharpening
        """
        p = max(0.001, min(0.999, p))
        num = p ** alpha
        den = num + (1 - p) ** alpha
        return num / den

    # ------------------------------------------------------------------
    # LLM querying
    # ------------------------------------------------------------------

    def _query_model(self, model: str, prompt: str) -> Optional[float]:
        """Query a model and extract a probability (0-1)."""
        try:
            if self._use_openrouter:
                return self._query_openrouter(model, prompt)
            else:
                return self._query_openai(prompt)
        except Exception as e:
            logger.debug("Model %s failed: %s", model, e)
            return None

    def _query_openrouter(self, model: str, prompt: str) -> Optional[float]:
        headers = {
            "Authorization": f"Bearer {self._openrouter_key}",
            "HTTP-Referer":  "https://alpha-trader",
            "X-Title":       "alpha_trader",
            "Content-Type":  "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 100,
        }
        r = self._session.post(
            f"{_OPENROUTER_BASE}/chat/completions",
            json=body, headers=headers, timeout=20,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        return self._extract_probability(text)

    def _query_openai(self, prompt: str) -> Optional[float]:
        from openai import OpenAI
        client = OpenAI(api_key=self._openai_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=100,
        )
        text = resp.choices[0].message.content
        return self._extract_probability(text)

    @staticmethod
    def _extract_probability(text: str) -> Optional[float]:
        """
        Extract a probability from model output.
        Handles: "0.73", "73%", "73 percent", "I estimate 73%"
        """
        text = text.strip()
        # Look for explicit probability formats
        patterns = [
            r"(\d+(?:\.\d+)?)\s*%",          # 73% or 73.5%
            r"0\.(\d+)",                       # 0.73
            r"probability[:\s]+(\d+(?:\.\d+)?)",
            r"estimate[:\s]+(\d+(?:\.\d+)?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = float(m.group(1) if "%" not in pat else m.group(1))
                if "%" in pat:
                    val /= 100
                return max(0.01, min(0.99, val))
        # Last resort: find any decimal between 0 and 1
        m = re.search(r"\b(0\.\d+)\b", text)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _build_prompt(question: str, context: str, market_price: float) -> str:
        return f"""You are a superforecaster.  Estimate the probability that the following will resolve YES.

Question: {question}

Current market price (implied probability): {market_price:.1%}

Context / recent news:
{context if context else "No additional context available."}

Instructions:
- Give a single probability estimate as a percentage (e.g., "73%")
- Be calibrated — avoid anchoring to the market price
- Consider base rates, recent evidence, and time remaining
- Output ONLY your probability estimate and a one-sentence rationale

Your estimate:"""

    @staticmethod
    def _high_disagreement(estimates: list[float], threshold: float = 0.15) -> bool:
        """Returns True if models disagree significantly."""
        if len(estimates) < 2:
            return False
        return max(estimates) - min(estimates) >= threshold

    def _fetch_news_context(self, question: str) -> str:
        """
        Fetch recent news headlines relevant to the question.
        Uses a simple RSS/news approach — pluggable with richer sources.
        """
        try:
            # Google News RSS (no API key required)
            import urllib.parse
            query = urllib.parse.quote(question[:100])
            url = f"https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"
            r = self._session.get(url, timeout=5)
            if r.status_code == 200:
                # Extract titles from RSS
                titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)
                titles = [t for t in titles if "Google News" not in t][:5]
                return "\n".join(f"- {t}" for t in titles)
        except Exception:
            pass
        return ""
