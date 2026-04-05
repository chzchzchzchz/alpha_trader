"""
Cross-platform market matcher.

Matches Kalshi markets to equivalent Polymarket markets using fuzzy string
matching (Jaccard + Levenshtein).  This is needed because the same real-world
event has different names on each platform.

E.g.:
  Kalshi:     "Will Bitcoin close above $100,000 on Dec 31?"
  Polymarket: "Bitcoin above 100k by end of 2024?"

Research reference: realfishsam/prediction-market-arbitrage-bot uses
Jaccard + Levenshtein.  ImMike/polymarket-arbitrage watches 10,000+ markets.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger("trading")

_STOPWORDS = frozenset([
    "will", "the", "a", "an", "be", "is", "are", "was", "were",
    "on", "in", "at", "by", "for", "of", "to", "and", "or", "it",
    "this", "that", "yes", "no", "above", "below", "by", "end",
])


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in _STOPWORDS and len(t) > 1]
    return " ".join(tokens)


def _tokenset(text: str) -> set[str]:
    return set(_normalize(text).split())


def jaccard(a: str, b: str) -> float:
    sa, sb = _tokenset(a), _tokenset(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union)


def levenshtein(a: str, b: str) -> int:
    a, b = _normalize(a), _normalize(b)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = curr
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """Combined similarity score (0-1). Higher = more similar."""
    j = jaccard(a, b)
    max_len = max(len(_normalize(a)), len(_normalize(b)), 1)
    lev_norm = 1.0 - levenshtein(a, b) / max_len
    return 0.6 * j + 0.4 * max(0.0, lev_norm)


@dataclass
class MatchedPair:
    kalshi_ticker: str
    kalshi_title: str
    poly_condition_id: str
    poly_question: str
    poly_token_id_yes: str
    poly_token_id_no: str
    match_score: float
    kalshi_yes_price: float   # fraction 0-1
    poly_yes_price: float     # fraction 0-1


class MarketMatcher:
    """
    Given lists of Kalshi markets and Polymarket markets,
    finds pairs that represent the same real-world event.
    """

    def __init__(self, min_similarity: float = 0.50):
        self.min_similarity = min_similarity

    def match(
        self,
        kalshi_markets: list,       # list of MarketStats from kalshi/wallet_analyzer
        poly_markets: list[dict],   # list of market dicts from Polymarket Gamma API
    ) -> list[MatchedPair]:
        pairs: list[MatchedPair] = []

        for km in kalshi_markets:
            best_score = 0.0
            best_pm: dict | None = None

            for pm in poly_markets:
                question = pm.get("question") or pm.get("title") or ""
                score = similarity(km.title, question)
                if score > best_score:
                    best_score = score
                    best_pm = pm

            if best_score >= self.min_similarity and best_pm:
                # Extract YES token price from Polymarket market
                tokens = best_pm.get("tokens", [])
                yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
                no_token  = next((t for t in tokens if t.get("outcome") == "No"),  None)

                if yes_token and no_token:
                    pairs.append(MatchedPair(
                        kalshi_ticker=km.ticker,
                        kalshi_title=km.title,
                        poly_condition_id=best_pm.get("conditionId", ""),
                        poly_question=best_pm.get("question") or best_pm.get("title", ""),
                        poly_token_id_yes=yes_token.get("token_id") or yes_token.get("tokenId", ""),
                        poly_token_id_no=no_token.get("token_id")  or no_token.get("tokenId", ""),
                        match_score=best_score,
                        kalshi_yes_price=km.yes_price,
                        poly_yes_price=float(yes_token.get("price", 0.5)),
                    ))

        pairs.sort(key=lambda p: p.match_score, reverse=True)
        logger.info("Matched %d market pairs (min_similarity=%.2f)",
                    len(pairs), self.min_similarity)
        return pairs
