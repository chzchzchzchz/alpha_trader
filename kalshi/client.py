"""Kalshi REST API client (CFTC-regulated)."""
from __future__ import annotations
import os, json, time, base64, hashlib
from pathlib import Path
from typing import Any
try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except: HAS_CRYPTO = False

_DEMO = "https://demo-api.kalshi.co/trade-api/v2"
_PROD = "https://trading-api.kalshi.com/trade-api/v2"

class KalshiClient:
    def __init__(self, key_id=None, private_key_path=None, demo=True):
        self.key_id = key_id or os.environ.get("KALSHI_API_KEY_ID","")
        pem = private_key_path or os.environ.get("KALSHI_API_KEY_FILE")
        self.base_url = _DEMO if demo else _PROD
        self._session = requests.Session()
        self._session.headers.update({"Content-Type":"application/json"})
        self._pk = None
        if pem and HAS_CRYPTO and Path(pem).exists():
            self._pk = serialization.load_pem_private_key(Path(pem).read_bytes(), password=None)

    def _sign(self, method, path, body=""):
        ts = str(int(time.time()*1000))
        msg = ts + method.upper() + path + body
        if self._pk is None: return {}
        sig = self._pk.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA256())
        return {"KALSHI-ACCESS-KEY":self.key_id,
                "KALSHI-ACCESS-TIMESTAMP":ts,
                "KALSHI-ACCESS-SIGNATURE":base64.b64encode(sig).decode()}

    def _get(self, path, params=None):
        headers = self._sign("GET", path)
        r = self._session.get(self.base_url+path, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path, body):
        bs = json.dumps(body)
        headers = self._sign("POST", path, bs)
        r = self._session.post(self.base_url+path, headers=headers, data=bs, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_markets(self, ticker_prefix=None, limit=10, status=None):
        params = {"limit": str(limit)}
        if ticker_prefix: params["ticker_prefix"] = ticker_prefix
        return self._get("/markets", params).get("markets", [])

    def get_market(self, ticker):
        return self._get("/markets/" + ticker).get("market", {})

    def place_order(self, ticker, action="buy", side="yes", count=1,
                    yes_price=None, no_price=None, expiration_type="GTC"):
        body = {"ticker":ticker, "action":action, "side":side, "count":count,
                "expiration_type":expiration_type}
        if yes_price is not None: body["yes_price"] = yes_price
        if no_price is not None: body["no_price"] = no_price
        return self._post("/orders", body)

    def get_positions(self, settlement_status="open"):
        return self._get("/positions", {"settlement_status":settlement_status})

    def get_portfolio(self):
        return self._get("/portfolio")

    def get_balance(self):
        return self._get("/balance")
