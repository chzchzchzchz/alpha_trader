"""
Sentiment Reader analyst node.

Classifies overall market sentiment (bullish / neutral / bearish) from
Reuters RSS headlines using the LLMForecaster's OpenRouter integration.
"""
from __future__ import annotations

import logging
import os
import re

import requests

from agents.state import MacroCycleState

logger = logging.getLogger("trading")

_SENTIMENTS = ("bullish", "neutral", "bearish")

_PROMPT_TEMPLATE = """You are a financial market sentiment analyst.

Read these recent financial headlines and classify the overall market sentiment.

HEADLINES:
{sentiment_summary}

Instructions:
Classify the current market sentiment as: bullish, neutral, or bearish.
Consider the tone, events described, and economic implications.

Respond ONLY in this exact format:
SENTIMENT: <bullish|neutral|bearish>
RATIONALE: <one sentence>"""


def sentiment_reader_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: classify market sentiment from RSS headlines.

    Reads:  state["sentiment_summary"]
    Writes: state["market_sentiment"]
    """
    sentiment_summary = state.get("sentiment_summary", "No headlines available.")
    new_errors: list[str] = []

    logger.info("[SentimentReader] Classifying market sentiment")

    sentiment = _classify_sentiment(sentiment_summary, new_errors)

    logger.info("[SentimentReader] sentiment=%s", sentiment)
    return {
        "market_sentiment": sentiment,
        "errors":           new_errors,
    }


def _classify_sentiment(summary: str, errors: list[str]) -> str:
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        try:
            return _llm_sentiment(summary, openrouter_key)
        except Exception as exc:
            msg = f"SentimentReader LLM failed: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return _keyword_sentiment(summary)


def _llm_sentiment(summary: str, api_key: str) -> str:
    prompt = _PROMPT_TEMPLATE.format(sentiment_summary=summary)
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
        "max_tokens":  80,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body, headers=headers, timeout=20,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]

    for line in text.splitlines():
        if line.strip().upper().startswith("SENTIMENT:"):
            raw = line.split(":", 1)[1].strip().lower()
            for s in _SENTIMENTS:
                if s in raw:
                    return s

    return "neutral"


def _keyword_sentiment(summary: str) -> str:
    """Simple keyword fallback when LLM is unavailable."""
    text = summary.lower()
    bullish_words = ["rally", "gain", "surge", "growth", "record", "rise", "bull"]
    bearish_words = ["crash", "fall", "decline", "recession", "loss", "bear", "sell-off"]

    bull_count = sum(text.count(w) for w in bullish_words)
    bear_count = sum(text.count(w) for w in bearish_words)

    if bull_count > bear_count + 2:
        return "bullish"
    if bear_count > bull_count + 2:
        return "bearish"
    return "neutral"
