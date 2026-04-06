"""
Shared position registry — prevents multiple strategies from taking
positions in the same Kalshi ticker simultaneously.

Usage:
    registry = PositionRegistry()
    if registry.try_claim("INFLATE-24JAN-T1.5", "convergence"):
        # strategy can open this market
        ...
    registry.release("INFLATE-24JAN-T1.5", "convergence")
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
import time


@dataclass
class SlotInfo:
    ticker: str
    strategy: str
    t0: float


class PositionRegistry:
    def __init__(self, max_per_ticker: int = 1):
        self._slots: dict[str, list[SlotInfo]] = {}
        self._total_open: int = 0
        self._max_per_ticker = max_per_ticker
        self._lock = threading.Lock()

    def try_claim(self, ticker: str, strategy: str, total_max: int = 50) -> bool:
        """Try to claim a slot in a market. Returns True if allowed."""
        with self._lock:
            if self._total_open >= total_max:
                return False
            existing = self._slots.get(ticker, [])
            if len(existing) >= self._max_per_ticker:
                return False
            self._slots.setdefault(ticker, []).append(
                SlotInfo(ticker, strategy, time.time())
            )
            self._total_open += 1
            return True

    def release(self, ticker: str, strategy: str) -> bool:
        with self._lock:
            slots = self._slots.get(ticker, [])
            for i, s in enumerate(slots):
                if s.strategy == strategy:
                    slots.pop(i)
                    if not slots:
                        del self._slots[ticker]
                    self._total_open -= 1
                    return True
            return False

    def owned(self, ticker: str) -> list[str]:
        """Which strategies have a claim on this ticker."""
        with self._lock:
            return [s.strategy for s in self._slots.get(ticker, [])]

    def active_claims(self) -> dict[str, int]:
        """Count of open claims."""
        with self._lock:
            return {k: len(v) for k, v in self._slots.items()}

    @property
    def total_open(self) -> int:
        with self._lock:
            return self._total_open
