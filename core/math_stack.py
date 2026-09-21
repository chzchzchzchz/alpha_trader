"""
core/math_stack.py — Central math library for prediction market trading.

Based on:
  - LMSR (Logarithmic Market Scoring Rule) market structure
  - RohOnChain's VWAP threshold framework
  - Medallion Fund signal aggregation (Jim Simons approach)
  - Frank-Wolfe / Bregman Projection for bracket arb

All probability values are in [0, 1] space.
All price values are in cents [0, 100].
"""
from __future__ import annotations
import math
from typing import Sequence


# ── LMSR Foundation ───────────────────────────────────────────────────────────

def lmsr_cost(quantities: Sequence[float], b: float = 100.0) -> float:
    """
    LMSR cost function: C(q) = b * ln(Σ e^(qᵢ/b))

    Prices in an LMSR market ARE probability distributions.
    The key implication: price moves near 0 or 1 carry more
    information than the same move near 0.5.
    """
    max_q = max(quantities)
    return b * math.log(sum(math.exp((q - max_q) / b) for q in quantities)) + max_q


def lmsr_price(quantities: Sequence[float], outcome_idx: int, b: float = 100.0) -> float:
    """
    LMSR marginal price for outcome i:
    p_i = e^(qᵢ/b) / Σ e^(qⱼ/b)

    This IS the probability of outcome i under the market's belief.
    """
    exp_q = [math.exp(q / b) for q in quantities]
    return exp_q[outcome_idx] / sum(exp_q)


def cents_to_prob(price_cents: float) -> float:
    """Convert Kalshi price in cents to probability [0,1]."""
    return max(1e-6, min(1 - 1e-6, price_cents / 100.0))


def prob_to_cents(p: float) -> float:
    """Convert probability to Kalshi cents."""
    return round(max(1.0, min(99.0, p * 100)), 1)


# ── KL Divergence (Information Distance) ─────────────────────────────────────

def kl_divergence(p: float, q: float) -> float:
    """
    KL(P || Q) for binary distributions.

    This is the correct distance metric between two LMSR market states.
    A move from 0.05→0.15 has KL ≈ 0.049 (high information value).
    A move from 0.50→0.60 has KL ≈ 0.020 (lower information value).
    Same 10¢ move, but the low-probability edge is informationally richer.
    """
    p = max(1e-9, min(1 - 1e-9, p))
    q = max(1e-9, min(1 - 1e-9, q))
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def bregman_distance(our_p: float, market_p: float) -> float:
    """
    Bregman distance from market state to our probability estimate.
    Maximum extractable profit ∝ Bregman distance.
    Equivalent to KL divergence for the negative-entropy Bregman generator.
    """
    return kl_divergence(our_p, market_p)


# ── Probability Scoring (LMSR-Aware, Not Linear) ─────────────────────────────

def temp_edge_to_prob(noaa_temp: float, threshold: float, is_above: bool,
                      scale: float = 0.18) -> float:
    """
    Convert temperature gap to probability using sigmoid (log-odds), NOT linear.

    The previous v22 formula was: 0.5 + diff * 0.06  (LINEAR — wrong)
    This uses: sigmoid(diff * scale)  (CORRECT for log-probability space)

    scale=0.18 means a 5° gap → ~70% confidence, 10° gap → ~85% confidence.
    The sigmoid ensures we never escape [0,1] and the shape matches
    how LMSR prices respond to information.
    """
    if is_above:
        diff = noaa_temp - threshold
    else:
        diff = threshold - noaa_temp

    log_odds = diff * scale
    prob = 1.0 / (1.0 + math.exp(-log_odds))
    return max(0.05, min(0.95, prob))


def aggregate_signals(signals: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """
    Aggregate N weak probability signals into one high-conviction estimate.
    Uses log-odds averaging (correct for probability space).

    Each signal: 52-54% win rate alone (barely above noise).
    Combined (if independent): compounded edge via log-odds addition.
    Ref: Medallion Fund / Jim Simons — 50 weak signals → 1 trade.
    """
    if not signals:
        return 0.5
    if weights is None:
        weights = [1.0] * len(signals)

    total_weight = sum(weights)
    weighted_log_odds = sum(
        w * math.log(max(1e-9, s) / max(1e-9, 1 - s))
        for s, w in zip(signals, weights)
    )
    avg_log_odds = weighted_log_odds / total_weight
    return 1.0 / (1.0 + math.exp(-avg_log_odds))


# ── VWAP Deviation Signal ─────────────────────────────────────────────────────

def vwap_deviation(yes_ask_cents: float, no_ask_cents: float) -> float:
    """
    |YES_ask + NO_ask - 100| in cents.

    In a perfectly efficient market: YES_ask + NO_ask = 100¢ (no-arb condition).
    Above 2¢ deviation: structural gap exists, execution risk < expected profit.
    Below 2¢ deviation: fees eat the trade, skip.

    RohOnChain: calculated per Polygon block (~2s). Threshold: 2¢.
    """
    return abs(yes_ask_cents + no_ask_cents - 100.0)


def vwap_qualifies(yes_ask_cents: float, no_ask_cents: float,
                   threshold_cents: float = 2.0) -> bool:
    """Returns True if the VWAP deviation exceeds the threshold."""
    return vwap_deviation(yes_ask_cents, no_ask_cents) > threshold_cents


# ── Modified Kelly Criterion ──────────────────────────────────────────────────

def kelly_fraction(our_prob: float, cost_cents: float,
                   payout_cents: float = 100.0,
                   fractional: float = 0.25) -> float:
    """
    Modified Kelly: f = (b*p - q) / b × √p

    Where:
      b  = net odds (payout/cost - 1)
      p  = our probability estimate
      q  = 1 - p
      √p = RohOnChain's execution probability discount

    fractional=0.25 means quarter-Kelly (conservative, handles model error).

    Returns fraction of bankroll to wager [0, 0.5].
    """
    if cost_cents <= 0 or payout_cents <= cost_cents:
        return 0.0
    p = max(0.01, min(0.99, our_prob))
    q = 1.0 - p
    b = (payout_cents - cost_cents) / cost_cents   # net odds
    raw_kelly = (b * p - q) / b
    execution_discount = math.sqrt(p)
    return max(0.0, min(0.5, raw_kelly * execution_discount * fractional))


def kelly_contracts(bankroll_cents: float, our_prob: float,
                    cost_cents: float, max_contracts: int = 20) -> int:
    """
    Convert Kelly fraction to integer number of contracts.
    """
    f = kelly_fraction(our_prob, cost_cents)
    if f <= 0 or cost_cents <= 0:
        return 0
    raw = (bankroll_cents * f) / cost_cents
    return max(1, min(max_contracts, int(raw)))


# ── Profit Filter ─────────────────────────────────────────────────────────────

def min_profit_qualifies(our_prob: float, cost_cents: float,
                         min_profit_per_dollar: float = 0.05) -> bool:
    """
    RohOnChain's minimum $0.05 profit threshold per dollar deployed.
    Expected value: our_prob * 100¢ - cost_cents
    As a fraction of cost: EV / cost
    """
    ev_cents = our_prob * 100.0 - cost_cents
    if cost_cents <= 0:
        return False
    return (ev_cents / cost_cents) >= min_profit_per_dollar


def book_depth_cap(position_size: int, book_depth: int,
                   max_fraction: float = 0.50) -> int:
    """
    Cap position at max_fraction of the thinner order book side.
    Prevents moving the market against yourself.
    """
    max_allowed = int(book_depth * max_fraction)
    return min(position_size, max(1, max_allowed))


# ── Trade Qualification (Full Checklist) ──────────────────────────────────────

def qualifies(yes_ask_cents: float, no_ask_cents: float,
              our_prob: float, book_depth: int = 1000,
              vwap_min: float = 2.0,
              min_profit: float = 0.05) -> tuple[bool, str]:
    """
    Run the full precision entry checklist from the thesis:

    1. VWAP deviation > 2¢
    2. Min profit ≥ 5% per dollar
    3. Book depth sufficient
    4. Kelly fraction > 0

    Returns (qualifies: bool, reason: str)
    """
    dev = vwap_deviation(yes_ask_cents, no_ask_cents)
    if dev < vwap_min:
        return False, f"VWAP dev {dev:.2f}¢ < {vwap_min}¢ threshold"

    if not min_profit_qualifies(our_prob, yes_ask_cents, min_profit):
        ev = our_prob * 100 - yes_ask_cents
        return False, f"EV {ev:.1f}¢ below min profit threshold"

    f = kelly_fraction(our_prob, yes_ask_cents)
    if f <= 0:
        return False, f"Kelly fraction {f:.4f} ≤ 0 (negative edge)"

    if book_depth < 10:
        return False, f"Book depth {book_depth} too thin"

    return True, f"PASS: dev={dev:.2f}¢ kelly={f:.3f}"
