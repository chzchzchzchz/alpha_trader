"""
Kalshi REST API client v2 - Kalshi-native (no prediction market).

Authentication: RSA-signed requests (Kalshi CFTC-regulated platform).
API: demo-api.kalshi.co (demo) / trading-api.kalshi.com (production)
"""
from __future__ import annotations

import os
import json
import time
import base64
import hashlib
from pathlib import Path
from typing import Any

try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

_DEMO = "https://demo-api.kalshi.co/trade-api/v2"
_PROD = "https://trading-api.kalshi.com/trade-api/v2"

# Kalshi-native: no prediction market dependency

class KalshiClient:
    """Kalshi REST API client with CFTC-regulated trading."""

    def __init__(self, key_id=None, private_key_path=None, demo=True):
        self.key_id = key_id or os.environ.get("KALSHI_API_KEY_ID", "")
        pem = private_key_path or os.environ.get("KALSHI_API_KEY_FILE")
        self.base_url = _DEMO if demo else _PROD
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._pk = None
        if pem and HAS_CRYPTO and Path(pem).exists():
            self._pk = serialization.load_pem_private_key(
                Path(pem).read_bytes(), password=None
            )

    def _sign(self, method, path, body=""):
        ts = str(int(time.time() * 1000))
        msg = ts + method.upper() + path + body
        if self._pk is None:
            return {}
        sig = self._pk.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA256())
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    def _get(self, path, params=None):
        headers = self._sign("GET", path)
        r = self._session.get(
            self.base_url + path, headers=headers, params=params, timeout=10
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path, body):
        bs = json.dumps(body)
        headers = self._sign("POST", path, bs)
        r = self._session.post(
            self.base_url + path, headers=headers, data=bs, timeout=10
        )
        r.raise_for_status()
        return r.json()

    # ---- Market Data ----

    def get_markets(self, ticker_prefix=None, limit=200, status=None, cursor=None):
        params = {"limit": str(limit)}
        if ticker_prefix:
            params["ticker_prefix"] = ticker_prefix
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params)

    def get_market(self, ticker):
        return self._get(f"/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker, depth=20):
        return self._get(f"/orderbook/{ticker}").get("orderbook", {})

    def get_midpoint(self, ticker):
        resp = self._get(f"/markets/{ticker}/midpoint")
        return resp.get("yes_price") or resp.get("midpoint")

    # ---- Trading ----

    def place_order(self, ticker, action="buy", side="yes", count=1,
                    yes_price=None, no_price=None, expiration_type="GTC",
                    order_type="limit"):
        """
        Place a Kalshi order.

        Args:
            ticker: Kalshi market ticker
            action: "buy" or "sell"
            side: "yes" or "no"
            count: number of contracts
            yes_price: price in cents for YES side (limit orders)
            no_price: price in cents for NO side (limit orders)
            expiration_type: "GTC", "GTD", "IOC", "FOK"
            order_type: "limit" or "market" (default "limit")
        """
        body = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "expiration_type": expiration_type,
        }

        # For limit orders, attach price
        if order_type == "limit":
            if yes_price is not None:
                body["yes_price"] = yes_price
            if no_price is not None:
                body["no_price"] = no_price
        # Market orders use action_price
        elif order_type == "market":
            body["action_type"] = "market"

        return self._post("/orders", body)

    def cancel_order(self, order_id):
        return self._delete(f"/orders/{order_id}")

    def get_orders(self, ticker=None, limit=20):
        params = {"limit": str(limit)}
        if ticker:
            params["ticker"] = ticker
        return self._get("/orders", params)

    # ---- Portfolio ----

    def get_positions(self, settlement_status="open"):
        return self._get(
            "/positions",
            {"settlement_status": settlement_status},
        )

    def get_portfolio(self):
        return self._get("/portfolio")

    def get_balance(self):
        return self._get("/balance")

    # ---- History ----

    def get_fills(self, limit=100):
        return self._get("/fills", {"limit": str(limit)})

    def get_settlements(self, limit=100):
        return self._get("/settlements", {"limit": str(limit)})

    def _delete(self, path):
        headers = self._sign("DELETE", path)
        r = self._session.delete(self.base_url + path, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
