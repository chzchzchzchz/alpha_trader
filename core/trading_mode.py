#!/usr/bin/env python3
"""
Trading mode gate — the single authority on whether this process may place
real Kalshi orders.

Contract
--------
    TRADING_MODE=paper|live          default: paper
    LIVE_TRADING_ARMED=I_ACCEPT_REAL_MONEY_LOSS
    KALSHI_DEMO=true                 legacy emergency brake: forces paper

Rules, in priority order:

1. The environment can only ever *downgrade* to paper. It can never upgrade a
   caller that asked for demo/paper into live.
2. A caller that asks for live gets live only if LIVE_TRADING_ARMED is set to
   the exact phrase. Otherwise:
     - TRADING_MODE=live  → raise LiveTradingNotArmed (operator clearly meant
       to go live and must find out why they did not), or
     - TRADING_MODE unset → warn and run paper.
3. Placing an order is the only operation that is gated. Reading prod market
   data, positions, balances, and *cancelling* prod orders is always allowed —
   an emergency-cancel script must never be silently redirected to the demo
   API (see kalshi.client.KalshiClient.place_order).

Note: kalshi_auto.py talks to Kalshi through the official kalshi_python SDK,
not through kalshi.client. It calls is_live() itself before authenticating.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("trading_mode")

PAPER = "paper"
LIVE = "live"
ARM_PHRASE = "I_ACCEPT_REAL_MONEY_LOSS"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


class LiveTradingNotArmed(RuntimeError):
    """Live trading was requested but not explicitly armed."""


def live_is_armed() -> bool:
    return os.getenv("LIVE_TRADING_ARMED", "").strip() == ARM_PHRASE


def resolve_mode(requested_live: bool = False, *, context: str = "") -> str:
    """Return PAPER or LIVE for a caller that did (not) ask for live trading."""
    where = f" [{context}]" if context else ""

    kalshi_demo = os.getenv("KALSHI_DEMO", "").strip().lower()
    env_mode = os.getenv("TRADING_MODE", "").strip().lower()

    if kalshi_demo and kalshi_demo not in _TRUTHY | _FALSY:
        logger.warning("Unrecognised KALSHI_DEMO=%r%s; treating as true (paper).",
                       kalshi_demo, where)
        kalshi_demo = "true"
    if env_mode and env_mode not in (PAPER, LIVE):
        logger.warning("Unrecognised TRADING_MODE=%r%s; treating as paper.",
                       env_mode, where)
        env_mode = PAPER

    if not requested_live:
        return PAPER

    # Caller asked for live. Environment may still veto.
    if kalshi_demo in _TRUTHY:
        logger.warning("Caller requested LIVE%s but KALSHI_DEMO=true forces PAPER.",
                       where)
        return PAPER
    if env_mode == PAPER:
        logger.warning("Caller requested LIVE%s but TRADING_MODE=paper forces PAPER.",
                       where)
        return PAPER

    if not live_is_armed():
        if env_mode == LIVE:
            raise LiveTradingNotArmed(_not_armed_message(where))
        logger.warning(
            "Caller requested LIVE trading%s but LIVE_TRADING_ARMED is not set. "
            "Running in PAPER mode. No real orders will be placed.", where,
        )
        return PAPER

    logger.warning("LIVE mode ARMED — REAL MONEY IS AT RISK%s", where)
    return LIVE


def is_live(requested_live: bool = False, *, context: str = "") -> bool:
    return resolve_mode(requested_live, context=context) == LIVE


def _not_armed_message(where: str) -> str:
    return (
        f"TRADING_MODE=live was set{where}, but live trading is NOT armed. "
        f"Real orders are blocked. To trade real money you must also set:\n"
        f"    LIVE_TRADING_ARMED={ARM_PHRASE}\n"
        f"Only do this once a paper track record justifies it."
    )
