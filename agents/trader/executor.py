"""
Trader Executor node.

Executes the sector rotation order through core/broker.py and sends
a Telegram alert via core/notifier.py.

Only runs if portfolio_vault_node set trade_approved=True.
Calculates share quantity from notional / current price (integer shares,
rounded down) to stay within the broker's qty-based API.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Optional

from agents.state import MacroCycleState
from core.notifier import make_notifier

logger = logging.getLogger("trading")


@dataclass
class _AlpacaCfg:
    key: str
    secret: str
    base_url: str


def trader_executor_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: execute the approved sector rotation trade.

    Reads:  state["trade_approved"], state["recommended_ticker"],
            state["notional_value"], state["cycle_phase"],
            state["sector_rationale"]
    Writes: state["order_id"], state["run_summary"]
    """
    new_errors: list[str] = []
    notifier = make_notifier()

    if not state.get("trade_approved"):
        reason = state.get("vault_block_reason", "trade not approved")
        summary = _build_summary(state, executed=False, order_id="", reason=reason)
        logger.info("[TraderExecutor] No trade — vault blocked: %s", reason)
        notifier.signal(
            strategy="MacroCycleEngine",
            question=f"Sector rotation blocked: {reason}",
            edge=0.0,
            price=0.0,
            size=0.0,
        )
        return {"order_id": "", "run_summary": summary, "errors": new_errors}

    ticker = state.get("recommended_ticker", "")
    notional = state.get("notional_value", 0.0)
    cycle_phase = state.get("cycle_phase", "unknown")
    rationale = state.get("sector_rationale", "")

    logger.info(
        "[TraderExecutor] Executing rotation → %s  notional=$%.2f", ticker, notional
    )

    broker = _make_broker()
    if broker is None:
        msg = "Alpaca credentials not set — cannot execute trade."
        new_errors.append(msg)
        summary = _build_summary(state, executed=False, order_id="", reason=msg)
        return {"order_id": "", "run_summary": summary, "errors": new_errors}

    # Calculate integer share qty from notional / price
    price = broker.get_latest_price(ticker)
    if not price or price <= 0:
        msg = f"Could not fetch price for {ticker}."
        new_errors.append(msg)
        summary = _build_summary(state, executed=False, order_id="", reason=msg)
        return {"order_id": "", "run_summary": summary, "errors": new_errors}

    qty = max(1, math.floor(notional / price))

    order_id = broker.submit_order(symbol=ticker, qty=qty, side="buy")
    executed = bool(order_id)

    if executed:
        notifier.trade(
            strategy="MacroCycleEngine",
            ticker=ticker,
            side="BUY",
            price=price,
            size=float(qty * price),
        )
        logger.info(
            "[TraderExecutor] Order placed: id=%s  %s x%d @ $%.2f",
            order_id, ticker, qty, price,
        )
    else:
        new_errors.append(f"Order submission failed for {ticker}")

    summary = _build_summary(state, executed=executed, order_id=order_id or "")
    return {"order_id": order_id or "", "run_summary": summary, "errors": new_errors}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_broker() -> Optional[object]:
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
        logger.warning("[TraderExecutor] Broker init failed: %s", exc)
        return None


def _build_summary(
    state: MacroCycleState,
    executed: bool,
    order_id: str,
    reason: str = "",
) -> str:
    phase     = state.get("cycle_phase", "unknown")
    sentiment = state.get("market_sentiment", "unknown")
    ticker    = state.get("recommended_ticker", "N/A")
    notional  = state.get("notional_value", 0.0)
    alloc     = state.get("allocation_fraction", 0.0)
    confidence = state.get("cycle_confidence", 0.0)
    rationale  = state.get("sector_rationale", "")
    errs       = state.get("errors") or []

    lines = [
        "=== Macro Cycle Engine Run Summary ===",
        f"  Cycle Phase:   {phase} (confidence {confidence:.0%})",
        f"  Sentiment:     {sentiment}",
        f"  Target Sector: {ticker}",
        f"  Rationale:     {rationale}",
        f"  Allocation:    {alloc:.1%} (${notional:.2f})",
    ]

    if executed:
        lines.append(f"  Status:        ✅ ORDER PLACED (id={order_id})")
    else:
        lines.append(f"  Status:        ⛔ NOT EXECUTED — {reason or 'see errors'}")

    if errs:
        lines.append("  Errors:")
        for e in errs:
            lines.append(f"    - {e}")

    return "\n".join(lines)
