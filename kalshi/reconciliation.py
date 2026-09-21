#!/usr/bin/env python3
"""
Reconciliation — Kalshi positions vs local DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

logger = logging.getLogger("reconciliation")

from kalshi.client import KalshiClient

class Reconciliation:
    def __init__(self, client: KalshiClient, db_conn):
        self.client = client
        self.db_conn = db_conn

    def reconcile_all(self) -> dict:
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "matched_positions": 0,
            "missing_local": [],
            "missing_remote": [],
            "amount_discrepancies": [],
            "balance_cents": 0,
            "positions_count": 0,
        }
        try:
            remote = self._fetch_remote_positions()
            result["positions_count"] = remote["raw_count"]
            result["balance_cents"] = remote["balance_cents"]
            local = self._load_local_positions()
            matched, discrepancies = self._compare_positions(local, remote["positions"])
            result["matched_positions"] = matched
            result["amount_discrepancies"] = discrepancies
            local_tickers = set(local.keys())
            remote_tickers = set(remote["positions"].keys())
            result["missing_local"] = list(remote_tickers - local_tickers)
            result["missing_remote"] = list(local_tickers - remote_tickers)
            if any([result["missing_local"], result["missing_remote"], discrepancies]):
                logger.warning("Reconciliation discrepancies: missing_local=%d missing_remote=%d discrepancies=%d",
                             len(result["missing_local"]), len(result["missing_remote"]), len(discrepancies))
            else:
                logger.info("Reconciliation OK: %d positions matched", matched)
        except Exception as e:
            logger.error("Reconciliation failed: %s", e)
            result["error"] = str(e)
        return result

    def _fetch_remote_positions(self) -> dict:
        try:
            pos_resp = self.client.get_positions(settlement_status="unsettled")
            positions = pos_resp.get("positions", [])
            bal_resp = self.client.get_balance()
            bal_cents = int(bal_resp.get("balance", 0) * 100) + int(bal_resp.get("portfolio_value", 0) * 100)
            pos_map = {}
            for p in positions:
                ticker = p.get("ticker", "")
                if ticker:
                    pos_map[ticker] = {
                        "ticker": ticker,
                        "quantity": p.get("quantity", 0),
                        "cost_basis_cents": p.get("cost_basis_cents", 0),
                    }
            return {"positions": pos_map, "balance_cents": bal_cents, "raw_count": len(positions)}
        except Exception as e:
            logger.error(f"Error fetching remote: {e}")
            return {"positions": {}, "balance_cents": 0, "raw_count": 0}

    def _load_local_positions(self) -> Dict[str, dict]:
        positions = {}
        try:
            cur = self.db_conn.cursor()
            cur.execute("""
                SELECT ticker, side, entry_price_cents, contracts
                FROM positions
                WHERE status != 'closed'
            """)
            for ticker, side, entry_price_cents, contracts in cur.fetchall():
                net = contracts if side == 'yes' else -contracts
                positions[ticker] = {"ticker": ticker, "net_position": net, "contracts": contracts}
        except Exception as e:
            logger.error(f"Error loading local positions: {e}")
        return positions

    def _compare_positions(self, local: Dict, remote: Dict) -> Tuple[int, List[Tuple[str, int, int]]]:
        matched = 0
        discrepancies = []
        local_tickers = set(local.keys())
        remote_tickers = set(remote.keys())
        common = local_tickers & remote_tickers
        for ticker in common:
            local_net = local[ticker]["net_position"]
            remote_qty = remote[ticker]["quantity"]
            if local_net == remote_qty:
                matched += 1
            else:
                discrepancies.append((ticker, local_net, remote_qty))
        return matched, discrepancies
