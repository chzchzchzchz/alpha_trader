"""
Kalshi REST API client v3 — Updated for new auth standard (PSS padding).

Authentication: RSA-PSS-signed requests per Kalshi docs.
Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP
Signing: Strip query params from path before signing. Use PSS padding.
API:  demo-api.kalshi.co (demo) / api.elections.kalshi.com (production)
"""
from __future__ import annotations

import os
import json
import time
import base64
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urlunparse, urlencode
from typing import Any

try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

_DEMO = "https://demo-api.kalshi.co/trade-api/v2"
_PROD = "https://api.elections.kalshi.com/trade-api/v2"

class KalshiClient:
    """Kalshi REST API client with RSA-PSS authentication."""

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
        # Strip query params from path before signing (per Kalshi docs)
        path_without_query = path.split("?")[0]
        ts = str(int(time.time() * 1000))
        msg = ts + method.upper() + path_without_query + body
        if self._pk is None:
            return {}
        # Use PSS padding (not PKCS1v15) per Kalshi docs
        sig = self._pk.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    def _get(self, path, params=None):
        query = ""
        if params:
            query = "?" + urlencode(params)
        full_path = path + query
        headers = self._sign("GET", full_path)
        r = self._session.get(
            self.base_url + full_path, headers=headers, timeout=15
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path, body):
        bs = json.dumps(body)
        headers = self._sign("POST", path, bs)
        r = self._session.post(
            self.base_url + path, headers=headers, data=bs, timeout=15
        )
        r.raise_for_status()
        return r.json()

    def _delete(self, path):
        headers = self._sign("DELETE", path)
        r = self._session.delete(self.base_url + path, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()

    # ---- Market Data ----

    def get_markets(self, ticker_prefix=None, limit=200, cursor=None):
        params = {"limit": str(limit)}
        if ticker_prefix:
            params["ticker_prefix"] = ticker_prefix
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params)

    def get_market(self, ticker):
        return self._get(f"/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker, depth=20):
        # Per Kalshi docs: GET /markets/{ticker}/orderbook
        # Optional depth param
        resp = self._get(f"/markets/{ticker}/orderbook", {"depth": str(depth)})
        return resp.get("orderbook_fp", resp.get("orderbook", {}))

    def get_midpoint(self, ticker):
        resp = self._get(f"/markets/{ticker}/midpoint")
        return resp.get("yes_price") or resp.get("midpoint")

    # ---- Trading ----

    def place_order(self, ticker, action="buy", side="yes", count=1,
                    yes_price=None, no_price=None, expiration_type="GTC",
                    type="limit", client_order_id=None):
        """
        Place an order on Kalshi.

        Per official Kalshi API docs:
        - Use "type" field (not "order_type")
        - Include client_order_id for deduplication
        - Returns 201 on success with {"order": {...}}
        """
        import uuid
        body = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": type,
            "expiration_type": expiration_type,
        }
        if type == "limit":
            if yes_price is not None:
                body["yes_price"] = int(round(float(yes_price) * 100)) if isinstance(yes_price, float) and yes_price < 1 else yes_price
            if no_price is not None:
                body["no_price"] = int(round(float(no_price) * 100)) if isinstance(no_price, float) and no_price < 1 else no_price
        elif type == "market":
            body["action_type"] = "market"

        # Deduplication ID
        if client_order_id:
            body["client_order_id"] = client_order_id
        else:
            body["client_order_id"] = str(uuid.uuid4())

        return self._post("/portfolio/orders", body)

    def cancel_order(self, order_id):
        return self._delete(f"/orders/{order_id}")

    def get_orders(self, ticker=None, limit=20):
        params = {"limit": str(limit)}
        if ticker:
            params["ticker"] = ticker
        return self._get("/orders", params)

    # ---- Portfolio ----

    def get_positions(self, settlement_status="open"):
        return self._get("/positions", {"settlement_status": settlement_status})

    def get_portfolio(self):
        return self._get("/portfolio")

    def get_balance(self):
        return self._get("/portfolio/balance")

    # ---- History ----

    def get_fills(self, limit=100):
        return self._get("/fills", {"limit": str(limit)})

    def get_settlements(self, limit=100):
        return self._get("/settlements", {"limit": str(limit)})
