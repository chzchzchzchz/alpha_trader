#!/usr/bin/env python3
"""
Position Tracker — fetch and maintain open positions from Kalshi API and DB.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Dict, List

from kalshi.client import KalshiClient
from kalshi.wallet_analyzer import WalletAnalyzer

logger = logging.getLogger("positions")

class PositionTracker:
    def __init__(self, client: KalshiClient, analyzer: WalletAnalyzer):
        self.client = client
        self.analyzer = analyzer
        self._cache: Dict[str, dict] = {}

    def refresh(self) -> List[dict]:
        """Refresh open positions from API and return list."""
        try:
            resp = self.client.get_positions(settlement_status="unsettled")
            positions = resp.get("positions", [])
            self._cache = {p["ticker"]: p for p in positions}
            logger.debug("Refreshed %d open positions from API", len(positions))
            return positions
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            return []

    def get_open_exposure(self, by_category: bool = False) -> Dict[str, float]:
        """
        Return total exposure in cents. If by_category=True, returns dict category->cents.
        """
        positions = self.refresh()
        total = 0.0
        if by_category:
            cat_exposure: Dict[str, float] = {}
            for p in positions:
                ticker = p["ticker"]
                # Derive category from ticker or event_ticker
                # Use Kalshi response's event_ticker if present
                cat = p.get("event_ticker", ticker.split('-')[0])
                cost_cents = p.get("cost_basis_cents", 0) or p.get("avg_price", 0) * p.get("contracts", 0) * 100
                cat_exposure[cat] = cat_exposure.get(cat, 0) + cost_cents
                total += cost_cents
            logger.debug("Exposure by category: %s", cat_exposure)
            return cat_exposure
        else:
            for p in positions:
                total += p.get("cost_basis_cents", 0) or p.get("avg_price", 0) * p.get("contracts", 0) * 100
            return {"total": total}

    def get_position(self, ticker: str) -> dict | None:
        return self._cache.get(ticker)

    def is_open(self, ticker: str) -> bool:
        return ticker in self._cache
