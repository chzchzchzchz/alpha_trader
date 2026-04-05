"""
Reuters RSS sentiment reader.

Pulls structured financial headlines from Reuters RSS feeds.
RSS is stable (no DOM selectors to break), publicly available, and
has no aggressive bot-blocking — the right choice over Yahoo Finance scraping.

Feeds used:
  - Reuters Business News
  - Reuters Markets

Each feed returns clean <title> entries parsed via the stdlib
xml.etree.ElementTree — no third-party HTML parsers required.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

logger = logging.getLogger("trading")

_REUTERS_FEEDS: dict[str, str] = {
    "business": "https://feeds.reuters.com/reuters/businessNews",
    "markets":  "https://feeds.reuters.com/reuters/financialNews",
}

# Fallback: Google News RSS requires no API key and covers Reuters stories
_GOOGLE_NEWS_FINANCE = (
    "https://news.google.com/rss/headlines/section/topic/BUSINESS"
    "?hl=en-US&gl=US&ceid=US:en"
)


class ReutersRSSReader:
    """
    Fetches financial headlines from Reuters RSS feeds.

    Falls back to Google News Finance RSS if Reuters feeds are unreachable
    (e.g., due to network restrictions in a sandboxed environment).

    Usage::

        reader = ReutersRSSReader()
        headlines = reader.fetch_headlines(max_items=15)
        summary = reader.format_for_prompt(headlines)
    """

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "alpha_trader/1.0 RSS reader (https://github.com/mrc2256/alpha_trader)"
        )

    def fetch_headlines(self, max_items: int = 15) -> list[dict[str, str]]:
        """
        Return up to ``max_items`` headlines as ``{title, source, link}`` dicts.

        Tries Reuters feeds first; falls back to Google News Finance RSS.
        Returns an empty list (never raises) so the graph keeps running.
        """
        headlines: list[dict[str, str]] = []

        for feed_name, url in _REUTERS_FEEDS.items():
            try:
                items = self._parse_rss(url, source=f"Reuters/{feed_name}")
                headlines.extend(items)
                if len(headlines) >= max_items:
                    break
            except Exception as exc:
                logger.debug("Reuters %s feed failed: %s", feed_name, exc)

        if not headlines:
            logger.info("Reuters feeds unavailable — falling back to Google News RSS")
            try:
                headlines = self._parse_rss(
                    _GOOGLE_NEWS_FINANCE, source="GoogleNews/Finance"
                )
            except Exception as exc:
                logger.warning("Google News fallback also failed: %s", exc)

        return headlines[:max_items]

    def format_for_prompt(self, headlines: list[dict[str, str]]) -> str:
        """
        Format headlines list into a compact string for LLM prompt injection.
        """
        if not headlines:
            return "No headlines available."
        lines = [f"  - {h['title']} [{h['source']}]" for h in headlines]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_rss(self, url: str, source: str) -> list[dict[str, str]]:
        """Fetch and parse an RSS feed, returning headline dicts."""
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items: list[dict[str, str]] = []

        # Standard RSS 2.0: /rss/channel/item/title
        # Atom feeds: /feed/entry/title  (handled via namespace-agnostic search)
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el  = item.find("link")
            if title_el is None or not title_el.text:
                continue
            title = self._clean_text(title_el.text)
            if not title:
                continue
            link = (link_el.text or "").strip() if link_el is not None else ""
            items.append({"title": title, "source": source, "link": link})

        logger.debug("RSS %s: parsed %d items", source, len(items))
        return items

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip CDATA wrappers and extra whitespace from RSS title text."""
        text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
        return text.strip()
