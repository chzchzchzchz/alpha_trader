"""
Polymarket Wallet Scanner.

Scans the Polymarket leaderboard and any known wallet addresses to find
wallets with persistent, statistically significant edge.

What research shows about profitable wallets:
  - Only 7.6% of wallets are profitable (120k of 1.5M)
  - 55%+ win rate over 50+ trades minimum threshold
  - Smooth equity curve (not volatile swings)
  - Category specialists outperform generalists
  - Exit at 80-90% (not holding to resolution)
  - Early entry (2-3 days before news breaks)

Basket approach: group 5-10 wallets in the same category, follow the basket.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("trading")

# Minimum stats for a wallet to be considered for copy trading
MIN_TRADES       = 50
MIN_WIN_RATE     = 0.55
MIN_ROI          = 0.10   # 10% ROI over history
MAX_WALLETS      = 20     # cap to avoid over-diversification


@dataclass
class WalletProfile:
    address: str
    total_trades: int
    win_rate: float
    roi: float             # total realized PnL / total volume
    total_pnl: float
    total_volume: float
    avg_position_size: float
    category_win_rates: dict[str, float] = field(default_factory=dict)
    best_category: str = ""
    last_active: Optional[datetime] = None
    recent_trades: list[dict] = field(default_factory=list)

    @property
    def score(self) -> float:
        """
        Composite score for ranking wallets.
        Rewards win rate + ROI + recency, penalizes tiny sample.
        """
        sample_penalty = min(1.0, self.total_trades / 100)
        return (self.win_rate * 0.5 + self.roi * 0.3) * sample_penalty

    @property
    def is_viable(self) -> bool:
        return (self.total_trades >= MIN_TRADES
                and self.win_rate >= MIN_WIN_RATE
                and self.roi >= MIN_ROI)


class WalletScanner:
    def __init__(self, client):
        self.client = client
        self._wallet_cache: dict[str, WalletProfile] = {}
        self._last_scan: float = 0.0

    # ------------------------------------------------------------------
    # Leaderboard scan
    # ------------------------------------------------------------------

    def scan_leaderboard(self, top_n: int = 200) -> list[WalletProfile]:
        """
        Pull leaderboard, filter to wallets with meaningful edge.
        Returns sorted list of viable wallets.
        """
        logger.info("Scanning Polymarket leaderboard (top %d)...", top_n)
        try:
            traders = self.client.get_top_traders(limit=top_n)
        except Exception as e:
            logger.error("Leaderboard fetch failed: %s", e)
            return []

        profiles: list[WalletProfile] = []
        for t in traders:
            addr = t.get("proxyWallet") or t.get("address") or t.get("user", "")
            if not addr:
                continue
            profile = self._build_profile_from_leaderboard(addr, t)
            if profile and profile.is_viable:
                profiles.append(profile)

        profiles.sort(key=lambda p: p.score, reverse=True)
        logger.info("Found %d viable wallets from leaderboard", len(profiles))
        return profiles[:MAX_WALLETS]

    def enrich_with_category_data(self, profiles: list[WalletProfile]) -> None:
        """
        For each wallet, fetch recent trades and compute per-category win rate.
        This is the "category specialist" detection.
        Modifies profiles in-place.
        """
        for p in profiles:
            try:
                trades = self.client.get_wallet_activity(p.address, limit=200)
                p.recent_trades = trades
                p.category_win_rates = self._compute_category_win_rates(trades)
                if p.category_win_rates:
                    p.best_category = max(p.category_win_rates,
                                          key=p.category_win_rates.get)
                time.sleep(0.1)  # gentle rate limiting
            except Exception as e:
                logger.debug("Category enrichment failed for %s: %s", p.address[:8], e)

    def find_category_specialists(
        self, profiles: list[WalletProfile],
        category: str,
        min_category_wr: float = 0.60,
        min_trades_in_category: int = 10,
    ) -> list[WalletProfile]:
        """
        Filter to wallets that are specialists in a specific category.
        A generalist with 55% overall WR might be 80% in crypto, 30% in politics.
        """
        specialists = []
        for p in profiles:
            cat_wr = p.category_win_rates.get(category, 0)
            cat_trades = sum(
                1 for t in p.recent_trades
                if self._trade_category(t) == category
            )
            if cat_wr >= min_category_wr and cat_trades >= min_trades_in_category:
                specialists.append(p)
        specialists.sort(key=lambda p: p.category_win_rates.get(category, 0), reverse=True)
        return specialists

    # ------------------------------------------------------------------
    # Known whale list (seed manually or from prior scans)
    # ------------------------------------------------------------------

    def analyze_wallet(self, address: str) -> WalletProfile | None:
        """Analyze a specific wallet by address."""
        if address in self._wallet_cache:
            return self._wallet_cache[address]
        try:
            stats = self.client.get_wallet_pnl(address)
            trades = self.client.get_wallet_activity(address, limit=200)
            profile = self._build_profile_from_stats(address, stats, trades)
            if profile:
                self._wallet_cache[address] = profile
            return profile
        except Exception as e:
            logger.error("Wallet analysis failed %s: %s", address[:10], e)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_profile_from_leaderboard(self, addr: str, data: dict) -> WalletProfile | None:
        pnl    = float(data.get("pnl", data.get("profit", 0)) or 0)
        volume = float(data.get("volume", data.get("notionalVolume", 1)) or 1)
        wins   = int(data.get("wins", data.get("marketsWon", 0)) or 0)
        total  = int(data.get("tradesCount", data.get("trades", 0)) or 0)
        if total == 0:
            return None
        return WalletProfile(
            address=addr,
            total_trades=total,
            win_rate=wins / total if total else 0.0,
            roi=pnl / volume if volume else 0.0,
            total_pnl=pnl,
            total_volume=volume,
            avg_position_size=volume / max(total, 1),
        )

    def _build_profile_from_stats(self, addr: str, stats: dict,
                                   trades: list[dict]) -> WalletProfile | None:
        if not stats and not trades:
            return None
        pnl      = float(stats.get("pnl", 0) or 0)
        volume   = float(stats.get("volume", 0) or 1)
        win_rate = float(stats.get("winRate", 0) or 0)
        total    = int(stats.get("tradesCount", len(trades)) or len(trades))

        cat_wrs = self._compute_category_win_rates(trades)
        best_cat = max(cat_wrs, key=cat_wrs.get) if cat_wrs else ""

        return WalletProfile(
            address=addr,
            total_trades=total,
            win_rate=win_rate,
            roi=pnl / volume if volume else 0.0,
            total_pnl=pnl,
            total_volume=volume,
            avg_position_size=volume / max(total, 1),
            category_win_rates=cat_wrs,
            best_category=best_cat,
            recent_trades=trades,
        )

    @staticmethod
    def _compute_category_win_rates(trades: list[dict]) -> dict[str, float]:
        cat_wins   = defaultdict(int)
        cat_totals = defaultdict(int)

        for t in trades:
            outcome = t.get("outcome")  # "WINNING" | "LOSING" | None
            if outcome not in ("WINNING", "LOSING"):
                continue
            cat = WalletScanner._trade_category(t)
            cat_totals[cat] += 1
            if outcome == "WINNING":
                cat_wins[cat] += 1

        return {
            cat: cat_wins[cat] / cat_totals[cat]
            for cat in cat_totals
            if cat_totals[cat] >= 5  # need at least 5 trades per category
        }

    @staticmethod
    def _trade_category(trade: dict) -> str:
        # Polymarket activity records sometimes include market metadata
        return (trade.get("market", {}).get("category")
                or trade.get("category")
                or trade.get("groupItemTitle", "unknown")
                or "unknown")
