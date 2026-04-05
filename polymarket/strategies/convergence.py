"""
7-Filter High-Probability Convergence Strategy.

Source: dylanpersonguy/Polymarket-Trading-Bot (92 stars, 53K+ lines)

Targets markets where price should converge to YES or NO.  All 7 filters
must pass before a position is opened.

Filters:
  1. Probability in 65–96% range (high conviction, not extreme)
  2. Resolution ≤ 14 days (near-term, time decay working for you)
  3. Liquidity ≥ $10,000 24h volume
  4. Spread ≤ 200 bps (2%) — tight enough to get reasonable fills
  5. Order flow imbalance ≥ $500 (buy pressure exceeds sell)
  6. No recent spike ≥ 8% (avoid chasing momentum)
  7. Cluster cap: max 25% of open positions in same category

Sizing: capital × 0.5% × setup_score (0–1 based on how cleanly filters pass)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("trading")


@dataclass
class ConvergenceConfig:
    min_probability: float = 0.65
    max_probability: float = 0.96
    max_days_to_resolution: float = 14.0
    min_volume_24h_usdc: float = 10_000.0
    max_spread_bps: float = 200.0          # 2%
    min_order_flow_imbalance_usdc: float = 500.0
    max_recent_spike_pct: float = 0.08     # 8%
    max_cluster_fraction: float = 0.25     # 25% of portfolio in one category
    base_position_pct: float = 0.005       # 0.5% of capital per trade
    min_setup_score: float = 0.60          # reject if composite score < 60%


@dataclass
class FilterResult:
    name: str
    passed: bool
    score: float   # 0–1 contribution to setup score
    detail: str = ""


@dataclass
class ConvergenceSignal:
    token_id: str
    market_id: str
    question: str
    side: str              # 'YES' or 'NO'
    current_price: float
    setup_score: float
    filters: list[FilterResult]
    days_to_resolution: float
    volume_24h: float


class ConvergenceStrategy:
    """
    Scans markets for high-probability convergence setups.
    """

    def __init__(self, client, capital: float = 500.0,
                 config: ConvergenceConfig | None = None):
        self.client  = client
        self.capital = capital
        self.cfg     = config or ConvergenceConfig()
        self._open_categories: dict[str, float] = {}  # category -> USDC open
        self._total_open_usdc: float = 0.0
        # token_id -> entry_price, for spike detection
        self._recent_prices: dict[str, list[tuple[float, float]]] = {}

    # ------------------------------------------------------------------
    # Main scan
    # ------------------------------------------------------------------

    def scan(self, markets: list[dict]) -> list[ConvergenceSignal]:
        signals: list[ConvergenceSignal] = []

        for market in markets:
            tokens = market.get("tokens", [])
            yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            no_token  = next((t for t in tokens if t.get("outcome") == "No"),  None)
            if not yes_token or not no_token:
                continue

            yes_price = float(yes_token.get("price", 0.5))
            no_price  = 1.0 - yes_price
            volume    = float(market.get("volume24hr") or market.get("volume", 0))
            category  = market.get("category", "unknown")

            # Check YES side (high probability = convergence to 1.0)
            if self.cfg.min_probability <= yes_price <= self.cfg.max_probability:
                sig = self._evaluate(market, yes_token, "YES", yes_price, volume, category)
                if sig:
                    signals.append(sig)

            # Check NO side (high probability = convergence to 1.0 for NO)
            if self.cfg.min_probability <= no_price <= self.cfg.max_probability:
                sig = self._evaluate(market, no_token, "NO", no_price, volume, category)
                if sig:
                    signals.append(sig)

        signals.sort(key=lambda s: s.setup_score, reverse=True)
        logger.info("Convergence scan: %d signals from %d markets", len(signals), len(markets))
        return signals

    # ------------------------------------------------------------------
    # Filter pipeline
    # ------------------------------------------------------------------

    def _evaluate(self, market: dict, token: dict, side: str,
                  price: float, volume: float, category: str) -> ConvergenceSignal | None:
        token_id  = token.get("token_id") or token.get("tokenId", "")
        market_id = market.get("conditionId") or market.get("id", "")
        question  = market.get("question") or market.get("title", "")

        filters = [
            self._f1_probability(price),
            self._f2_resolution(market),
            self._f3_liquidity(volume),
            self._f4_spread(token_id),
            self._f5_order_flow(token_id),
            self._f6_no_spike(token_id, price),
            self._f7_cluster(category),
        ]

        if not all(f.passed for f in filters):
            return None

        setup_score = sum(f.score for f in filters) / len(filters)
        if setup_score < self.cfg.min_setup_score:
            return None

        end_date = market.get("endDate") or market.get("end_date_iso", "")
        days = self._days_to_resolution(end_date)

        return ConvergenceSignal(
            token_id=token_id,
            market_id=market_id,
            question=question,
            side=side,
            current_price=price,
            setup_score=setup_score,
            filters=filters,
            days_to_resolution=days,
            volume_24h=volume,
        )

    # -- Individual filters --

    def _f1_probability(self, price: float) -> FilterResult:
        ok = self.cfg.min_probability <= price <= self.cfg.max_probability
        # Score peaks at 85% (ideal convergence setup)
        score = 1.0 - abs(price - 0.85) / 0.35
        return FilterResult("probability", ok, max(0.0, score),
                            f"price={price:.3f}")

    def _f2_resolution(self, market: dict) -> FilterResult:
        end = market.get("endDate") or market.get("end_date_iso", "")
        days = self._days_to_resolution(end)
        ok = 0 < days <= self.cfg.max_days_to_resolution
        score = 1.0 - (days / self.cfg.max_days_to_resolution) if ok else 0.0
        return FilterResult("resolution", ok, score, f"days={days:.1f}")

    def _f3_liquidity(self, volume: float) -> FilterResult:
        ok = volume >= self.cfg.min_volume_24h_usdc
        score = min(1.0, volume / (self.cfg.min_volume_24h_usdc * 3))
        return FilterResult("liquidity", ok, score, f"vol24h=${volume:.0f}")

    def _f4_spread(self, token_id: str) -> FilterResult:
        try:
            book = self.client.get_orderbook(token_id)
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            if bids and asks:
                best_bid = float(bids[0].get("price", bids[0].get("p", 0)))
                best_ask = float(asks[0].get("price", asks[0].get("p", 1)))
                mid  = (best_bid + best_ask) / 2
                spread_bps = ((best_ask - best_bid) / mid * 10000) if mid else 9999
                ok = spread_bps <= self.cfg.max_spread_bps
                score = max(0.0, 1.0 - spread_bps / self.cfg.max_spread_bps)
                return FilterResult("spread", ok, score, f"{spread_bps:.0f}bps")
        except Exception:
            pass
        return FilterResult("spread", False, 0.0, "orderbook unavailable")

    def _f5_order_flow(self, token_id: str) -> FilterResult:
        """
        Proxy order flow imbalance using orderbook depth difference.
        Real implementation would use trade tape to sum buy vs sell USDC.
        """
        try:
            book = self.client.get_orderbook(token_id)
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            # Sum top-5 depth on each side
            bid_depth = sum(float(b.get("size", b.get("s", 0))) for b in bids[:5])
            ask_depth = sum(float(a.get("size", a.get("s", 0))) for a in asks[:5])
            imbalance = (bid_depth - ask_depth) * 1.0  # USDC proxy
            ok = imbalance >= self.cfg.min_order_flow_imbalance_usdc
            score = min(1.0, max(0.0, imbalance / (self.cfg.min_order_flow_imbalance_usdc * 2)))
            return FilterResult("order_flow", ok, score, f"imbalance=${imbalance:.0f}")
        except Exception:
            pass
        return FilterResult("order_flow", False, 0.0, "book unavailable")

    def _f6_no_spike(self, token_id: str, current_price: float) -> FilterResult:
        """Reject if price moved ≥8% recently (avoid chasing)."""
        history = self._recent_prices.get(token_id, [])
        now = time.time()
        # Keep last 60 seconds of prices
        history = [(t, p) for t, p in history if now - t <= 60]
        history.append((now, current_price))
        self._recent_prices[token_id] = history

        if len(history) >= 2:
            oldest = history[0][1]
            change = abs(current_price - oldest) / max(oldest, 0.001)
            ok = change < self.cfg.max_recent_spike_pct
            score = max(0.0, 1.0 - change / self.cfg.max_recent_spike_pct)
            return FilterResult("no_spike", ok, score, f"Δ={change:.1%}")

        return FilterResult("no_spike", True, 1.0, "insufficient history")

    def _f7_cluster(self, category: str) -> FilterResult:
        """Reject if category already has ≥25% of total open exposure."""
        total = max(self._total_open_usdc, 1.0)
        cat_exposure = self._open_categories.get(category, 0.0)
        fraction = cat_exposure / total
        ok = fraction <= self.cfg.max_cluster_fraction
        score = max(0.0, 1.0 - fraction / self.cfg.max_cluster_fraction)
        return FilterResult("cluster", ok, score, f"{fraction:.1%} in {category}")

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def position_size_usdc(self, signal: ConvergenceSignal) -> float:
        return self.capital * self.cfg.base_position_pct * signal.setup_score

    def record_open(self, signal: ConvergenceSignal, usdc: float) -> None:
        self._open_categories[signal.market_id] = (
            self._open_categories.get(signal.market_id, 0.0) + usdc
        )
        self._total_open_usdc += usdc

    def record_close(self, market_id: str, usdc: float) -> None:
        self._open_categories[market_id] = max(
            0.0, self._open_categories.get(market_id, 0.0) - usdc
        )
        self._total_open_usdc = max(0.0, self._total_open_usdc - usdc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _days_to_resolution(end_date_str: str) -> float:
        if not end_date_str:
            return 999.0
        try:
            end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            delta = end - datetime.now(timezone.utc)
            return max(0.0, delta.total_seconds() / 86400)
        except Exception:
            return 999.0
