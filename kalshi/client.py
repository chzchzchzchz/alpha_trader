"""
Kalshi REST API client v4 — Fixed auth per kalshi-python SDK source.

Authentication: RSA-PSS. Message = timestamp + method + path (NO body).
Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP
API:  demo-api.kalshi.co (demo) / api.elections.kalshi.com (production)
"""
from __future__ import annotations

import os
import json
import time
import base64
from pathlib import Path
from urllib.parse import urlencode
from typing import Any

try:
    import requests
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

from core.trading_mode import LIVE, LiveTradingNotArmed, resolve_mode

_DEMO = "https://demo-api.kalshi.co/trade-api/v2"
_PROD = "https://api.elections.kalshi.com/trade-api/v2"

class KalshiClient:
    """Kalshi REST API client with RSA-PSS authentication."""

    def __init__(self, key_id=None, private_key_path=None, demo=True):
        # `demo` selects the API host and is honoured as given so that reads,
        # balance checks and emergency cancels always hit the account the
        # caller named. Placing an order against the production host is gated
        # separately by core.trading_mode (see place_order).
        self.demo = bool(demo)
        self._live_armed = (
            resolve_mode(requested_live=True, context="KalshiClient") == LIVE
            if not self.demo else False
        )
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

    def _sign(self, method: str, path: str):
        """Sign request per Kalshi SDK: timestamp + method + /trade-api/v2 + path (no body)."""
        ts = str(int(time.time() * 1000))
        # SDK uses full path including /trade-api/v2 prefix
        full_path = "/trade-api/v2" + path
        msg = ts + method.upper() + full_path
        if self._pk is None:
            return {}
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

    def _get(self, path: str, params: dict | None = None) -> dict:
        query = ""
        if params:
            query = "?" + urlencode(params)
        full = path + query
        # Sign with path ONLY (no query params) per Kalshi docs
        headers = self._sign("GET", path)
        r = self._session.get(self.base_url + full, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        bs = json.dumps(body)
        headers = self._sign("POST", path)
        r = self._session.post(
            self.base_url + path, headers=headers, data=bs, timeout=15
        )
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> dict:
        headers = self._sign("DELETE", path)
        r = self._session.delete(self.base_url + path, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()

    # ---- Market Data ----

    def get_markets(self, ticker_prefix=None, series_ticker=None, limit=200, status=None, cursor=None):
        params: dict[str, str] = {"limit": str(limit)}
        if ticker_prefix:
            params["ticker_prefix"] = ticker_prefix
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params)

    def get_market(self, ticker: str):
        return self._get(f"/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker: str, depth=20):
        resp = self._get(f"/markets/{ticker}/orderbook", {"depth": str(depth)})
        return resp.get("orderbook_fp", resp.get("orderbook", {}))

    def get_midpoint(self, ticker: str):
        resp = self._get(f"/markets/{ticker}/midpoint")
        return resp.get("yes_price") or resp.get("midpoint")

    # ---- Trading ----

    def place_order(self, ticker, action="buy", side="yes", count=1,
                    yes_price=None, no_price=None, expiration_type="gtc",
                    type="limit", client_order_id=None, post_only=False,
                    reduce_only=False, cancel_on_pause=False):
        import uuid
        if not self.demo and not self._live_armed:
            raise LiveTradingNotArmed(
                "Refusing to place a REAL order: live trading is not armed. "
                "Set LIVE_TRADING_ARMED to the arm phrase (see core/trading_mode.py)."
            )
        body: dict[str, Any] = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "expiration_type": expiration_type,
        }
        if type == "limit":
            body["type"] = "limit"
            if yes_price is not None:
                body["yes_price"] = int(round(float(yes_price) * 100)) if float(yes_price) < 1 else int(yes_price)
            if no_price is not None:
                body["no_price"] = int(round(float(no_price) * 100)) if float(no_price) < 1 else int(no_price)
        elif type == "market":
            body["action_type"] = "market"
        
        # Count: int
        body["count"] = int(count)
        
        # Flags
        if post_only:
            body["post_only"] = True
        if reduce_only:
            body["reduce_only"] = True
        if cancel_on_pause:
            body["cancel_order_on_pause"] = True
        
        body["client_order_id"] = client_order_id or str(uuid.uuid4())
        return self._post("/portfolio/orders", body)

    def cancel_order(self, order_id: str):
        return self._delete(f"/portfolio/orders/{order_id}")

    def get_orders(self, status=None, ticker=None, limit=20):
        params: dict[str, str] = {"limit": str(limit)}
        if status:
            params["status"] = status
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/orders", params)

    # ---- Portfolio ----

    def get_positions(self, settlement_status="unsettled"):
        return self._get("/portfolio/positions", {"settlement_status": settlement_status})

    def get_portfolio(self):
        return self._get("/portfolio")

    def get_balance(self):
        return self._get("/portfolio/balance")

    # ---- History ----

    def get_fills(self, limit=100):
        return self._get("/portfolio/fills", {"limit": str(limit)})

    def get_settlements(self, limit=100):
        return self._get("/portfolio/settlements", {"limit": str(limit)})
    
    # ---- Trades (public) ----
    
    def get_trades(self, ticker=None, limit=100, cursor=None):
        params: dict[str, str] = {"limit": str(limit)}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets/trades", params)
