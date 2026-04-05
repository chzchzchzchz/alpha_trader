"""
Portfolio Vault — the deterministic risk manager node.

Wraps core/broker.py (AlpacaBroker) with safety guards:
  1. Market must be open
  2. Allocation fraction must be valid (0 < f ≤ MAX_ALLOCATION)
  3. Notional value must be ≥ MIN_NOTIONAL
  4. Cycle confidence must be ≥ MIN_CONFIDENCE to trade

The LLM agents decide *what* to buy; the vault decides *whether* and
*how much* — no AI math is used for position sizing.

All Alpaca credentials are read from environment variables:
  ALPACA_API_KEY    — API key
  ALPACA_SECRET_KEY — secret key
  ALPACA_BASE_URL   — defaults to paper trading URL
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from agents.state import MacroCycleState

logger = logging.getLogger("trading")

# Safety constants
MIN_NOTIONAL: float = 100.0        # minimum trade size in USD
MAX_ALLOCATION: float = 0.25       # max 25% of buying power per rotation
MIN_CONFIDENCE: float = 0.40       # minimum cycle confidence to execute


@dataclass
class _AlpacaCfg:
    key: str
    secret: str
    base_url: str


def portfolio_vault_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: validate and size a sector rotation trade.

    Reads:  state["recommended_ticker"], state["cycle_confidence"]
    Writes: state["allocation_fraction"], state["notional_value"],
            state["trade_approved"], state["vault_block_reason"]
    """
    ticker = state.get("recommended_ticker", "")
    cycle_confidence = state.get("cycle_confidence", 0.0)
    new_errors: list[str] = []

    logger.info("[PortfolioVault] Evaluating trade for %s (confidence=%.2f)", ticker, cycle_confidence)

    # ── Gate 1: valid ticker ──────────────────────────────────────────
    if not ticker:
        return _block("No ticker recommended by sector specialist.", new_errors)

    # ── Gate 2: minimum confidence ────────────────────────────────────
    if cycle_confidence < MIN_CONFIDENCE:
        return _block(
            f"Cycle confidence {cycle_confidence:.0%} below minimum {MIN_CONFIDENCE:.0%}.",
            new_errors,
        )

    # ── Gate 3: broker connectivity + market hours ────────────────────
    broker = _make_broker()
    if broker is None:
        return _block("Alpaca credentials not set — cannot trade.", new_errors)

    if not broker.is_market_open():
        return _block("Market is closed — trade deferred.", new_errors)

    # ── Gate 4: fetch buying power ────────────────────────────────────
    buying_power = _get_buying_power(broker)
    if buying_power is None:
        return _block("Could not retrieve buying power.", new_errors)

    # ── Gate 5: sizing — scale allocation with confidence ─────────────
    # Confidence 0.40 → 5% allocation; 1.0 → MAX_ALLOCATION (25%)
    raw_fraction = (cycle_confidence - MIN_CONFIDENCE) / (1.0 - MIN_CONFIDENCE)
    allocation_fraction = round(raw_fraction * MAX_ALLOCATION, 4)
    allocation_fraction = max(0.01, min(MAX_ALLOCATION, allocation_fraction))

    notional_value = buying_power * allocation_fraction

    if notional_value < MIN_NOTIONAL:
        return _block(
            f"Notional ${notional_value:.2f} below minimum ${MIN_NOTIONAL:.0f}.",
            new_errors,
        )

    logger.info(
        "[PortfolioVault] Approved: %s allocation=%.1f%% notional=$%.2f",
        ticker, allocation_fraction * 100, notional_value,
    )
    return {
        "allocation_fraction": allocation_fraction,
        "notional_value":      notional_value,
        "trade_approved":      True,
        "vault_block_reason":  "",
        "errors":              new_errors,
    }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _block(
    reason: str,
    errors: list[str],
) -> MacroCycleState:
    logger.warning("[PortfolioVault] Trade blocked: %s", reason)
    return {
        "allocation_fraction": 0.0,
        "notional_value":      0.0,
        "trade_approved":      False,
        "vault_block_reason":  reason,
        "errors":              errors,
    }


def _make_broker() -> Optional[object]:
    """Build an AlpacaBroker from environment variables, or return None."""
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret  = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret:
        return None
    base_url = os.environ.get(
        "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
    )
    try:
        from core.broker import AlpacaBroker
        cfg = _AlpacaCfg(key=api_key, secret=secret, base_url=base_url)
        return AlpacaBroker(cfg)
    except Exception as exc:
        logger.warning("[PortfolioVault] Broker init failed: %s", exc)
        return None


def _get_buying_power(broker) -> Optional[float]:
    """Read buying_power from the Alpaca account object."""
    try:
        account = broker.api.get_account()
        return float(account.buying_power)
    except Exception as exc:
        logger.warning("[PortfolioVault] Could not get buying power: %s", exc)
        return None
