"""
Polymarket API client.

Three APIs:
  - Gamma API  (market metadata, search)      https://gamma-api.polymarket.com
  - CLOB API   (orderbook, trading)            https://clob.polymarket.com
  - Data API   (wallet activity, positions)    https://data-api.polymarket.com

Authentication: CLOB requires a derived API key (key/secret/passphrase) tied
to your Polygon EOA wallet.  Gamma and Data endpoints are public (no auth).

Polygon chain ID: 137
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger("trading")

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE  = "https://clob.polymarket.com"
_DATA_BASE  = "https://data-api.polymarket.com"


class PolymarketClient:
    """
    Wraps all three Polymarket APIs.

    For read-only wallet scanning and arbitrage detection, only the public
    Gamma and Data APIs are needed — no credentials required.

    For order execution, set POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE
    environment variables (derived from your Polygon wallet via py-clob-client).
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._api_key       = os.getenv("POLY_API_KEY", "")
        self._api_secret    = os.getenv("POLY_API_SECRET", "")
        self._api_passphrase = os.getenv("POLY_API_PASSPHRASE", "")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, base: str, path: str, params: dict | None = None,
             auth: bool = False, retries: int = 3) -> Any:
        headers = {}
        if auth:
            headers = {
                "POLY-API-KEY":        self._api_key,
                "POLY-API-SECRET":     self._api_secret,
                "POLY-API-PASSPHRASE": self._api_passphrase,
            }
        url = base + path
        for attempt in range(retries):
            try:
                r = self._session.get(url, params=params, headers=headers, timeout=10)
                r.raise_for_status()
                return r.json()
            except requests.HTTPError as e:
                if r.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limited — waiting %ds", wait)
                    time.sleep(wait)
                else:
                    raise
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                time.sleep(1.5 ** attempt)
        return None

    def _post(self, base: str, path: str, body: dict) -> Any:
        import json
        headers = {
            "Content-Type":        "application/json",
            "POLY-API-KEY":        self._api_key,
            "POLY-API-SECRET":     self._api_secret,
            "POLY-API-PASSPHRASE": self._api_passphrase,
        }
        r = self._session.post(
            base + path, data=json.dumps(body), headers=headers, timeout=10
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Gamma API — public, no auth
    # ------------------------------------------------------------------

    def get_markets(self, limit: int = 100, offset: int = 0,
                    active: bool = True, closed: bool = False) -> list[dict]:
        params = {"limit": limit, "offset": offset,
                  "active": str(active).lower(), "closed": str(closed).lower()}
        return self._get(_GAMMA_BASE, "/markets", params=params) or []

    def search_markets(self, query: str, limit: int = 20) -> list[dict]:
        return self._get(_GAMMA_BASE, "/markets",
                         params={"search": query, "active": "true", "limit": limit}) or []

    def get_market_by_slug(self, slug: str) -> dict | None:
        results = self._get(_GAMMA_BASE, "/markets",
                            params={"slug": slug, "limit": 1})
        return results[0] if results else None

    def get_events(self, limit: int = 100, active: bool = True) -> list[dict]:
        return self._get(_GAMMA_BASE, "/events",
                         params={"limit": limit, "active": str(active).lower()}) or []

    # ------------------------------------------------------------------
    # Data API — public, no auth required for read
    # ------------------------------------------------------------------

    def get_wallet_activity(self, wallet_address: str,
                            limit: int = 100, offset: int = 0,
                            trade_type: str = "TRADE") -> list[dict]:
        """
        Fetch trade history for any Polymarket wallet address.
        Returns most recent trades first.
        """
        params = {
            "user":   wallet_address,
            "type":   trade_type,
            "limit":  limit,
            "offset": offset,
            "sortBy": "TIMESTAMP",
        }
        result = self._get(_DATA_BASE, "/activity", params=params)
        if isinstance(result, list):
            return result
        return result.get("data", []) if result else []

    def get_wallet_positions(self, wallet_address: str) -> list[dict]:
        result = self._get(_DATA_BASE, "/positions",
                           params={"user": wallet_address})
        if isinstance(result, list):
            return result
        return result.get("data", []) if result else []

    def get_wallet_pnl(self, wallet_address: str) -> dict:
        """Returns realized PnL, win rate, and volume for a wallet."""
        result = self._get(_DATA_BASE, "/stats",
                           params={"user": wallet_address})
        return result or {}

    def get_top_traders(self, limit: int = 100, window: str = "all") -> list[dict]:
        """Fetch leaderboard — sorted by PnL."""
        return self._get(_DATA_BASE, "/leaderboard",
                         params={"limit": limit, "window": window}) or []

    # ------------------------------------------------------------------
    # CLOB API — market data (public) + order placement (auth required)
    # ------------------------------------------------------------------

    def get_clob_market(self, condition_id: str) -> dict:
        return self._get(_CLOB_BASE, f"/markets/{condition_id}") or {}

    def get_orderbook(self, token_id: str) -> dict:
        return self._get(_CLOB_BASE, "/book", params={"token_id": token_id}) or {}

    def get_last_trade_price(self, token_id: str) -> float | None:
        result = self._get(_CLOB_BASE, "/last-trade-price",
                           params={"token_id": token_id})
        if result:
            return float(result.get("price", 0))
        return None

    def get_midpoint(self, token_id: str) -> float | None:
        result = self._get(_CLOB_BASE, "/midpoint",
                           params={"token_id": token_id})
        if result:
            return float(result.get("mid", 0))
        return None

    def place_market_order(self, token_id: str, side: str,
                           amount_usdc: float) -> dict:
        """
        Place a market order.
        side: 'BUY' | 'SELL'
        amount_usdc: dollar amount (not shares)

        NOTE: Real order placement requires py-clob-client with wallet signing.
        This sends a signed order to the CLOB API.
        See https://github.com/Polymarket/py-clob-client for full implementation.
        """
        body = {
            "token_id": token_id,
            "side":     side,
            "type":     "MARKET",
            "amount":   str(amount_usdc),
        }
        return self._post(_CLOB_BASE, "/order", body)

    def place_limit_order(self, token_id: str, side: str,
                          price: float, size: float) -> dict:
        body = {
            "token_id": token_id,
            "side":     side,
            "type":     "LIMIT",
            "price":    str(price),
            "size":     str(size),
        }
        return self._post(_CLOB_BASE, "/order", body)
