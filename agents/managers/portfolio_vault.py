"""
Portfolio Vault — the deterministic risk manager node.

Wraps core/broker.py (AlpacaBroker) with safety guards:
  1. Market must be open
  2. Allocation fraction must be valid (0 < f ≤ MAX_ALLOCATION)
  3. Notional value must be ≥ MIN_NOTIONAL
  4. Cycle confidence must be ≥ MIN_CONFIDENCE to trade
  5. Circuit breaker: blocks if Kelly-sized allocation > 20% of equity
     OR if the CBOE VIX is above VIX_CIRCUIT_BREAKER (35)

Position sizing uses quarter-Kelly (KellySizer with fraction=0.25) with
default odds b=2.0 (sector ETF rotation is assumed to have 2 : 1 upside).

  f* = (p · (b+1) − 1) / b   [full Kelly]
  final = f* × 0.25           [quarter-Kelly for variance reduction]

where p = cycle_confidence and b = KELLY_ODDS.

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
from core.kelly_sizer import KellySizer

logger = logging.getLogger("trading")

# Safety constants
MIN_NOTIONAL: float = 100.0         # minimum trade size in USD
MAX_ALLOCATION: float = 0.25        # hard cap: 25% of buying power per rotation
MIN_CONFIDENCE: float = 0.40        # minimum cycle confidence to execute

# Circuit breaker thresholds
CIRCUIT_BREAKER_ROTATION: float = 0.20   # block if Kelly allocation > 20% of equity
VIX_CIRCUIT_BREAKER: float = 35.0        # block if VIX ≥ this level

# Kelly parameters for sector ETF rotation
KELLY_ODDS: float = 2.0    # assumed 2:1 upside (avg_win=0.10 / avg_loss=0.05)
KELLY_FRACTION: float = 0.25  # quarter-Kelly multiplier


@dataclass
class _AlpacaCfg:
    key: str
    secret: str
    base_url: str


def portfolio_vault_node(state: MacroCycleState) -> MacroCycleState:
    """
    LangGraph node: validate and size a sector rotation trade.

    Reads:  state["recommended_ticker"], state["cycle_confidence"]
    Writes: state["vix"], state["allocation_fraction"], state["notional_value"],
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

    # ── Gate 5: VIX circuit breaker ───────────────────────────────────
    vix = _fetch_vix()
    if vix is not None and vix >= VIX_CIRCUIT_BREAKER:
        reason = (
            f"Circuit breaker: VIX={vix:.1f} ≥ threshold {VIX_CIRCUIT_BREAKER:.0f}. "
            "Position sizing halted to protect capital."
        )
        _fire_circuit_breaker(reason)
        return {**_block(reason, new_errors), "vix": vix}

    # ── Gate 6: Kelly-criterion position sizing ───────────────────────
    sizer = KellySizer(fraction=KELLY_FRACTION)
    # avg_win and avg_loss map to b = KELLY_ODDS via avg_win/avg_loss = b
    avg_win = KELLY_ODDS * 0.05   # 0.10 (10% gain on correct rotation)
    avg_loss = 0.05                # 0.05 (5% loss on incorrect rotation)
    kelly_frac = sizer.kelly_fraction(cycle_confidence, avg_win, avg_loss)
    allocation_fraction = round(min(kelly_frac, MAX_ALLOCATION), 4)

    logger.info(
        "[PortfolioVault] Kelly sizing: p=%.2f b=%.1f → f*=%.4f (capped at %.2f)",
        cycle_confidence, KELLY_ODDS, kelly_frac, MAX_ALLOCATION,
    )

    # ── Gate 7: rotation circuit breaker (> 20% of equity) ───────────
    if kelly_frac > CIRCUIT_BREAKER_ROTATION:
        reason = (
            f"Circuit breaker: Kelly allocation {kelly_frac:.1%} exceeds "
            f"daily rotation limit {CIRCUIT_BREAKER_ROTATION:.0%}. "
            "Trade blocked to prevent over-concentration."
        )
        _fire_circuit_breaker(reason)
        return {**_block(reason, new_errors), "vix": vix}

    # Ensure a minimum meaningful allocation after Kelly math
    if allocation_fraction <= 0:
        return {**_block(
            f"Kelly fraction {kelly_frac:.4f} implies no edge at confidence "
            f"{cycle_confidence:.0%} — trade skipped.",
            new_errors,
        ), "vix": vix}

    notional_value = buying_power * allocation_fraction

    if notional_value < MIN_NOTIONAL:
        return {**_block(
            f"Notional ${notional_value:.2f} below minimum ${MIN_NOTIONAL:.0f}.",
            new_errors,
        ), "vix": vix}

    logger.info(
        "[PortfolioVault] Approved: %s kelly=%.1f%% allocation=%.1f%% notional=$%.2f",
        ticker, kelly_frac * 100, allocation_fraction * 100, notional_value,
    )
    return {
        "vix":                 vix,
        "allocation_fraction": allocation_fraction,
        "notional_value":      notional_value,
        "trade_approved":      True,
        "vault_block_reason":  "",
        "errors":              new_errors,
    }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _block(reason: str, errors: list[str]) -> MacroCycleState:
    logger.warning("[PortfolioVault] Trade blocked: %s", reason)
    return {
        "allocation_fraction": 0.0,
        "notional_value":      0.0,
        "trade_approved":      False,
        "vault_block_reason":  reason,
        "errors":              errors,
    }


def _fire_circuit_breaker(reason: str) -> None:
    """Send a Telegram alert and log the circuit breaker trigger."""
    logger.warning("[PortfolioVault] CIRCUIT BREAKER: %s", reason)
    try:
        from core.notifier import make_notifier
        notifier = make_notifier()
        notifier.circuit_breaker(reason, daily_pnl=0.0)
    except Exception as exc:
        logger.warning("[PortfolioVault] Could not send circuit breaker alert: %s", exc)


def _fetch_vix() -> Optional[float]:
    """
    Attempt to read the latest CBOE VIX level from FRED (series VIXCLS).

    Returns None if FRED_API_KEY is not set or the request fails — the caller
    skips the VIX circuit breaker in that case rather than blocking all trades.
    """
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        logger.debug("[PortfolioVault] FRED_API_KEY not set — VIX check skipped")
        return None
    try:
        import requests as _req
        resp = _req.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id":  "VIXCLS",
                "api_key":    api_key,
                "file_type":  "json",
                "sort_order": "desc",
                "limit":      1,
            },
            timeout=8,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        if obs and obs[0].get("value", ".") != ".":
            vix = float(obs[0]["value"])
            logger.info("[PortfolioVault] VIX=%.2f (FRED VIXCLS, %s)", vix, obs[0]["date"])
            return vix
    except Exception as exc:
        logger.warning("[PortfolioVault] VIX fetch failed — check skipped: %s", exc)
    return None


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
