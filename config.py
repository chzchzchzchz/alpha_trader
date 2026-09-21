#!/usr/bin/env python3
"""
Config — loads risk parameters from environment and second-brain (CRM).
Used by executor, position_manager, and other agents to enforce limits.
"""

import os
import json
import subprocess
from pathlib import Path

def load_second_brain_query(query_args: list[str]) -> dict:
    """Call ~/.hermes/second_brain/query.py and parse JSON output."""
    script = str(Path.home() / ".hermes" / "second_brain" / "query.py")
    cmd = ["python3", script] + query_args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}

def get_risk_profile():
    """Return a dict with risk limits."""
    # Defaults (safe starting values)
    profile = {
        "max_daily_loss_cents": 300,  # $3.00
        "max_concurrent_trades": 5,
        "stop_loss_pct": 0.15,  # 15%
        "take_profit_pct": 0.25,  # 25%
        "max_exposure_cents": 500,  # $5.00 total risk
        "tax_lot_method": "FIFO",
    }
    # Override from environment
    if os.getenv("MAX_DAILY_LOSS_CENTS"):
        profile["max_daily_loss_cents"] = int(os.getenv("MAX_DAILY_LOSS_CENTS"))
    if os.getenv("MAX_CONCURRENT_TRADES"):
        profile["max_concurrent_trades"] = int(os.getenv("MAX_CONCURRENT_TRADES"))
    if os.getenv("STOP_LOSS_PCT"):
        profile["stop_loss_pct"] = float(os.getenv("STOP_LOSS_PCT"))
    if os.getenv("TAKE_PROFIT_PCT"):
        profile["take_profit_pct"] = float(os.getenv("TAKE_PROFIT_PCT"))
    if os.getenv("MAX_EXPOSURE_CENTS"):
        profile["max_exposure_cents"] = int(os.getenv("MAX_EXPOSURE_CENTS"))
    if os.getenv("TAX_LOT_METHOD"):
        profile["tax_lot_method"] = os.getenv("TAX_LOT_METHOD")
    # Override from second-brain CRM (persona risk settings)
    try:
        brain = load_second_brain_query(["--persona"])
        if brain:
            # Look for keys like risk.max_daily_loss, etc.
            risk = brain.get("risk", {})
            if "max_daily_loss" in risk:
                profile["max_daily_loss_cents"] = int(risk["max_daily_loss"] * 100)
            if "max_concurrent_trades" in risk:
                profile["max_concurrent_trades"] = int(risk["max_concurrent_trades"])
            if "stop_loss" in risk:
                profile["stop_loss_pct"] = float(risk["stop_loss"])
            if "take_profit" in risk:
                profile["take_profit_pct"] = float(risk["take_profit"])
            if "tax_lot_method" in risk:
                profile["tax_lot_method"] = risk["tax_lot_method"]
    except Exception:
        pass
    return profile

RISK_PROFILE = get_risk_profile()
