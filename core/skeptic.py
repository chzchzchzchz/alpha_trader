"""Skeptic Agent - Validates all data & signals before execution.
Rejects bad data, unrealistic edges, and echo chambers.
Thresholds calibrated for real market reality."""
from __future__ import annotations
from typing import List, Dict

class SkepticAgent:
    def __init__(self, strictness=0.7):
        self.strictness = strictness
        self.doubts = []

    def check_data(self, signals):
        """Check overall data integrity"""
        self.doubts = []
        if not signals:
            return "REJECT: No data - pipeline broken"
        sources = set()
        for s in signals:
            if hasattr(s, 'source'):
                src = s.source.value if hasattr(s.source, 'value') else str(s.source)
                sources.add(src)
            elif isinstance(s, dict):
                sources.add(s.get('source', 'unknown'))
        
        if len(sources) < 2:
            self.doubts.append(f"Only {len(sources)} source")
            return f"CAUTION: Only {len(sources)} source - not diversified"
        return "PASS"

    def check_signal(self, signal):
        """Check individual signal quality"""
        conf = signal.get("confidence", 0.5)
        if conf < 0.50:
            return "REJECT: Very weak confidence"
        if conf < 0.55:
            return "CAUTION: Low confidence - risky"
        return "PASS"

    def check_strategy_performance(self, name: str, result: Dict) -> str:
        """Check strategy backtest results for realism"""
        self.doubts = []
        ret = result.get("total_return_pct", 0)
        trades = result.get("total_trades", 0)
        if trades < 5:
            self.doubts.append("Too few trades")
            return "CAUTION: Statistically insignificant"
        if ret > 200 and trades < 30:
            self.doubts.append("Unrealistic return")
            return "REJECT: Likely overfit or buggy"
        if ret < -50:
            self.doubts.append("Massive losses")
            return "REJECT: Strategy destroyed capital"
        return "PASS"
