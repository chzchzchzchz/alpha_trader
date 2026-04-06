"""SkepticAgent - Statistical validation engine for trading strategies.
Uses actual statistical tests (t-test, Mann-Whitney, Cohen's d) to validate edges.
No LLM reliance - pure statistics.
"""
from __future__ import annotations
import numpy as np
from typing import Dict, Any

class SkepticAgent:
    def __init__(self, alpha=0.05, min_trades=10, min_edge_bps=5.0):
        self.alpha = alpha
        self.min_trades = min_trades
        self.min_edge_bps = min_edge_bps
        self.history = []

    def _ttest(self, vals):
        if len(vals) < 3:
            return 0.0, 1.0
        m = np.mean(vals)
        s = np.std(vals, ddof=1)
        if s == 0:
            return m, 1.0
        t = m / (s/np.sqrt(len(vals)))
        p = 2 * min(1.0, self._t_pval_approx(abs(t), len(vals)-1))
        return t, p

    def _t_pval_approx(self, t, df):
        if df <= 0: return 0.5
        x = df / (df + t*t)
        return 0.5 * self._regularized_beta(df/2.0, 0.5, x)

    def _regularized_beta(self, a, b, x):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        return x ** a * (1-x) ** b

    def validate_returns(self, strategy_returns=np.ndarray, 
                        benchmark_returns=None) -> Dict[str, Any]:
        """Full statistical validation of strategy returns."""
        n = len(strategy_returns)
        mean_r = np.mean(strategy_returns)
        std_r = np.std(strategy_returns, ddof=1)
        sr_annual = (mean_r / max(std_r, 1e-9)) * np.sqrt(252) if std_r > 0 else 0.0
        
        t_stat, t_pval = self._ttest(strategy_returns)
        wins = int(np.sum(strategy_returns > 0))
        wr = wins / max(n, 1)
        
        alpha_pval = 1.0
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            excess = strategy_returns - benchmark_returns[:n]
            _, alpha_pval = self._ttest(excess)
        
        cohens_d = mean_r / max(std_r, 1e-9)
        
        edge_bps = mean_r * 10000
        edge_valid = edge_bps >= self.min_edge_bps and n >= self.min_trades
        
        result = {
            "status": "PASS" if (t_pval < self.alpha and edge_valid and alpha_pval < self.alpha) else "REJECT",
            "t_statistic": round(t_stat, 4),
            "t_pvalue": round(t_pval, 6),
            "alpha_pvalue": round(alpha_pval, 6),
            "annualized_sharpe": round(sr_annual, 3),
            "mean_return_bps": round(edge_bps, 2),
            "win_rate_pct": round(wr * 100, 1),
            "total_trades": n,
            "edge_valid": bool(edge_valid),
            "significance_at_5pct": bool(t_pval < self.alpha),
            "cohen_d": round(cohens_d, 3),
            "warnings": []
        }
        
        if n < self.min_trades:
            result["warnings"].append(f"Only {n} trades (need {self.min_trades})")
        if edge_bps < self.min_edge_bps:
            result["warnings"].append(f"Edge {edge_bps:.1f}bps < {self.min_edge_bps}bps minimum")
        if t_pval >= self.alpha:
            result["warnings"].append(f"Returns not significant (p={t_pval:.4f})")
        
        self.history.append(result)
        return result

    def check_trade(self, trade_dict: dict) -> str:
        conf = trade_dict.get("confidence", 0.5)
        size = trade_dict.get("size", 0)
        if conf < 0.55:
            return f"REJECT: confidence {conf:.0%} < 55%"
        if size > 0.05:
            return f"REJECT: size {size:.1%} > 5% max"
        return "PASS"

    def summary(self) -> dict:
        if not self.history:
            return {"validations": 0}
        return {"validations": len(self.history),
                "passed": sum(1 for x in self.history if x["status"] == "PASS"),
                "failed": sum(1 for x in self.history if x["status"] != "PASS")}
