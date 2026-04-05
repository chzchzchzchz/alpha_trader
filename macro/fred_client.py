"""
FRED (Federal Reserve Economic Data) API client.

Pulls leading macro indicators for the Cycle Economist agent.
Requires a free API key from https://fred.stlouisfed.org/

Key series used by the Macro Cycle Engine:
  T10Y2Y   — Yield curve spread (10Y minus 2Y Treasury)
  CPIAUCSL — CPI inflation (all items, seasonally adjusted)
  UNRATE   — Unemployment rate
  INDPRO   — Industrial production index
  HOUST    — Housing starts
  UMCSENT  — University of Michigan consumer sentiment
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger("trading")

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Leading indicator series for macro cycle analysis
LEADING_SERIES: dict[str, str] = {
    "T10Y2Y":   "Yield Curve Spread (10Y-2Y)",
    "INDPRO":   "Industrial Production Index",
    "HOUST":    "Housing Starts",
    "UMCSENT":  "Consumer Sentiment",
}

# Lagging/coincident indicators that confirm cycle phase
LAGGING_SERIES: dict[str, str] = {
    "CPIAUCSL": "CPI Inflation (YoY)",
    "UNRATE":   "Unemployment Rate",
}


class FredMacroEngine:
    """
    Fetches macroeconomic time-series from the FRED API.

    Usage::

        engine = FredMacroEngine()
        data = engine.fetch_series("T10Y2Y", limit=5)
        snapshot = engine.fetch_cycle_snapshot()
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("FRED_API_KEY", "")
        self._session = requests.Session()

    def fetch_series(self, series_id: str, limit: int = 5) -> dict[str, Any]:
        """
        Fetch the most recent observations for a FRED series.

        Returns a dict with ``series``, ``description``, and
        ``latest_values`` (list of ``{date, value}`` dicts, newest first).

        Raises ``ValueError`` if FRED_API_KEY is not set.
        Raises ``requests.HTTPError`` on API errors.
        """
        if not self.api_key:
            raise ValueError("FRED_API_KEY environment variable not set.")

        params = {
            "series_id":  series_id,
            "api_key":    self.api_key,
            "file_type":  "json",
            "sort_order": "desc",
            "limit":      limit,
        }

        response = self._session.get(_FRED_BASE, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        values = [
            {"date": obs["date"], "value": float(obs["value"])}
            for obs in data.get("observations", [])
            if obs.get("value", ".") != "."
        ]

        all_series = {**LEADING_SERIES, **LAGGING_SERIES}
        description = all_series.get(series_id, series_id)

        logger.debug("FRED %s: fetched %d observations", series_id, len(values))
        return {
            "series":       series_id,
            "description":  description,
            "latest_values": values,
        }

    def fetch_cycle_snapshot(self, limit: int = 3) -> dict[str, Any]:
        """
        Fetch all leading and lagging indicator series in one call.

        Returns a dict keyed by series ID, each value being the result
        of ``fetch_series``.  Series that fail (e.g. bad API key) return
        an ``error`` key instead of ``latest_values``.
        """
        snapshot: dict[str, Any] = {}
        all_series = {**LEADING_SERIES, **LAGGING_SERIES}
        for series_id in all_series:
            try:
                snapshot[series_id] = self.fetch_series(series_id, limit=limit)
            except Exception as exc:
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)
                snapshot[series_id] = {
                    "series":      series_id,
                    "description": all_series[series_id],
                    "error":       str(exc),
                }
        return snapshot

    def format_for_prompt(self, snapshot: dict[str, Any]) -> str:
        """
        Convert a cycle snapshot into a compact, human-readable string
        suitable for injection into an LLM prompt.
        """
        lines: list[str] = []
        for series_id, info in snapshot.items():
            desc = info.get("description", series_id)
            if "error" in info:
                lines.append(f"  {desc} ({series_id}): [fetch error]")
                continue
            vals = info.get("latest_values", [])
            if not vals:
                lines.append(f"  {desc} ({series_id}): [no data]")
                continue
            latest = vals[0]
            lines.append(
                f"  {desc} ({series_id}): {latest['value']:.3f} as of {latest['date']}"
            )
        return "\n".join(lines)
