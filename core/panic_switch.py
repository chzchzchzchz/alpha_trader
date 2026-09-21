#!/usr/bin/env python3
"""
Panic Switch — Immediate cancellation of all orders across all venues.
Kill Switch — Automated circuit breaker on repeated failures.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Set, List

logger = logging.getLogger("panic")

@dataclass
class PanicState:
    triggered_at: float
    reason: str
    manual: bool = False

class PanicSwitch:
    def __init__(self, client, db_conn):
        self.client = client
        self.db_conn = db_conn
        self.panic_file = Path('logs/panic.trigger')
        self.state: PanicState | None = None
        self.canceled_orders: Set[str] = set()

    def check_trigger(self) -> bool:
        if self.panic_file.exists():
            reason = self.panic_file.read_text().strip()
            self.trigger(reason)
            return True
        return False

    def trigger(self, reason: str, manual: bool = True):
        if self.state is not None:
            logger.warning("Panic already triggered at %s", self.state.triggered_at)
            return
        logger.critical("PANIC SWITCH TRIGGERED: %s (manual=%s)", reason, manual)
        self.state = PanicState(triggered_at=time.time(), reason=reason, manual=manual)
        self._cancel_all_orders()
        self._mark_all_positions_for_exit()

    def _cancel_all_orders(self):
        try:
            resp = self.client.cancel_all_orders()
            canceled = resp.get('order_ids', [])
            self.canceled_orders.update(canceled)
            logger.info("Canceled %d orders", len(canceled))
        except Exception as e:
            logger.error("Failed to cancel orders: %s", e)

    def _mark_all_positions_for_exit(self):
        try:
            cur = self.db_conn.cursor()
            cur.execute("UPDATE positions SET status = 'panic_exit' WHERE status != 'closed'")
            self.db_conn.commit()
            logger.info("Marked all positions for panic exit")
        except Exception as e:
            logger.error("Failed to mark positions: %s", e)

    def is_triggered(self) -> bool:
        return self.state is not None

class KillSwitch:
    def __init__(self, failure_threshold: int = 5, window_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.failures: List[float] = []
        self.triggered_at: float | None = None

    def record_success(self):
        # Prune old failures
        now = time.time()
        cutoff = now - self.window_seconds
        self.failures = [t for t in self.failures if t >= cutoff]

    def record_failure(self):
        now = time.time()
        self.failures.append(now)
        # Prune old
        cutoff = now - self.window_seconds
        self.failures = [t for t in self.failures if t >= cutoff]
        if len(self.failures) >= self.failure_threshold and self.triggered_at is None:
            self.triggered_at = now
            logger.critical("KILL SWITCH TRIGGERED: %d failures in %ds window", len(self.failures), self.window_seconds)
            # Create panic trigger file
            Path('logs/kill.trigger').write_text(f"Killed after {len(self.failures)} failures in {self.window_seconds}s")

    def is_triggered(self) -> bool:
        return self.triggered_at is not None

    def should_halt(self) -> bool:
        return self.is_triggered()
