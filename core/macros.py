"""MacroEngine - Real FRED data. No API key needed.
Fetches from: https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID
"""
from __future__ import annotations
import numpy as np
import httpx
from typing import Dict, Any


class MacroEngine:
    def __init__(self):
        self.series = {
            "T10Y2Y": {"name": "10Y-2Y Treasury Spread", "higher_good": True},
            "UNRATE": {"name": "Unemployment Rate", "higher_good": False},
            "CPIAUCSL": {"name": "CPI", "higher_good": False},
            "UMCSENT": {"name": "Consumer Sentiment", "higher_good": True},
            "FEDFUNDS": {"name": "Fed Funds Rate", "higher_good": False},
        }

    def _fetch(self, sid):
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            r = httpx.get(url, timeout=10.0, follow_redirects=True,
                headers={"User-Agent": "AlphaTrader/1.0"})
            if r.status_code != 200:
                return None
            lines = r.text.strip().split("\n")[1:]
            vals = []
            for ln in lines:
                parts = ln.strip().split(",")
                if len(parts) >= 2:
                    try: vals.append(float(parts[1]))
                    except: pass
            return vals if len(vals) >= 12 else None
        except:
            return None

    def _momentum(self, v, n=3):
        return (v[-1] - v[-n-1]) / max(abs(v[-n-1]), 1e-9)

    def generate_signals(self) -> Dict[str, Any]:
        signals = {}
        for sid, meta in self.series.items():
            vals = self._fetch(sid)
            if vals is None:
                signals[sid] = {"name": meta["name"], "error": "fetch_failed"}
                continue
            mom3 = self._momentum(vals, 3)
            mom6 = self._momentum(vals, 6)
            bullish = meta["higher_good"]
            if not bullish:
                mom3 = -mom3; mom6 = -mom6
            weight = max(-10, min(10, (mom3 + mom6) * 5))
            signals[sid] = {
                "name": meta["name"],
                "value": vals[-1],
                "momentum_3m": round(mom3, 4),
                "momentum_6m": round(mom6, 4),
                "weight": round(weight, 2)
            }
        good = {k:v for k,v in signals.items() if "error" not in v}
        if good:
            weights = [v["weight"] for v in good.values()]
            avg = np.mean(weights)
            signals["aggregate"] = {
                "bullish": avg > 0,
                "strength": round(abs(avg), 2),
                "bullish_pct": round((avg + 10) / 20 * 100, 1),
                "count": len(good)
            }
        return signals
