"""
Kalshi REST API client.

Wraps the Kalshi trading API v2.  Authentication uses the KALSHI_API_KEY_ID
and KALSHI_API_KEY_FILE (path to RSA private key PEM) environment variables.

Docs: https://trading-api.kalshi.com/trade-api/v2/openapi.json
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("trading")

_DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"
_PROD_BASE = "https://trading-api.kalshi.com/trade-api/v2"


class KalshiClient:
    """Thin wrapper around the Kalshi REST API."""

    def __init__(self, key_id: str | None = None, private_key_path: str | None = None,
                 demo: bool = True):
        self.key_id = key_id or os.environ["KALSHI_API_KEY_ID"]
        pem_path = private_key_path or os.environ.get("KALSHI_API_KEY_FILE", "kalshi_key.pem")
        self.base_url = _DEMO_BASE if demo else _PROD_BASE
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        pem = Path(pem_path)
        if pem.exists():
            self._private_key = serialization.load_pem_private_key(
                pem.read_bytes(), password=None
            )
        else:
            logger.warning("Kalshi private key not found at %s — unauthenticated mode", pem_path)
            self._private_key = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        msg = ts + method.upper() + path + body
        if self._private_key is None:
            return {}
        sig = self._private_key.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA256())
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        headers = self._sign("GET", path)
        r = self._session.get(self.base_url + path, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> Any:
        import json
        body_str = json.dumps(body)
        headers = self._sign("POST", path, body_str)
        r = self._session.post(self.base_url + path, headers=headers, data=body_str, timeout=10)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> Any:
        headers = self._sign("DELETE", path)
        r = self._session.delete(self.base_url + path, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    def get_markets(self, limit: int = 200, cursor: str | None = None,
                    status: str = "open", series_ticker: str | None = None) -> dict:
        params = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._get("/markets", params=params)

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")

    def get_market_orderbook(self, ticker: str, depth: int = 10) -> dict:
        return self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_trades(self, ticker: str, limit: int = 100,
                   min_ts: int | None = None, max_ts: int | None = None) -> dict:
        params: dict = {"ticker": ticker, "limit": limit}
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts
        return self._get("/markets/trades", params=params)

    def get_series(self, series_ticker: str) -> dict:
        return self._get(f"/series/{series_ticker}")

    def get_event(self, event_ticker: str) -> dict:
        return self._get(f"/events/{event_ticker}")

    # ------------------------------------------------------------------
    # Portfolio / Account
    # ------------------------------------------------------------------

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

    def get_positions(self, limit: int = 200) -> dict:
        return self._get("/portfolio/positions", params={"limit": limit})

    def get_fills(self, ticker: str | None = None, limit: int = 200) -> dict:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/fills", params=params)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(self, ticker: str, action: str, side: str,
                    count: int, order_type: str = "limit",
                    yes_price: int | None = None, no_price: int | None = None) -> dict:
        """
        action: 'buy' | 'sell'
        side:   'yes' | 'no'
        yes_price / no_price: price in cents (1–99)
        """
        body: dict = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": order_type,
        }
        if yes_price is not None:
            body["yes_price"] = yes_price
        if no_price is not None:
            body["no_price"] = no_price
        return self._post("/portfolio/orders", body)

    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f"/portfolio/orders/{order_id}")

    def get_orders(self, status: str = "resting", limit: int = 100) -> dict:
        return self._get("/portfolio/orders", params={"status": status, "limit": limit})
