"""SkepticAgent: Statistical validation of trading edges."""
from __future__ import annotations
import numpy as np
from typing import Dict, Any

class SkepticAgent:
    def __init__(self, alpha=0.05, min_n=15):
        self.alpha = alpha; self.min_n = min_n; self.history = []

    def _ttest(self, vals):
        n=len(vals); m=np.mean(vals); s=np.std(vals,ddof=1)
        if s==0 or n<3: return 0,1
        t=m/(s/np.sqrt(n)); df=n-1
        p=min(1, 2/(1+0.4361836*abs(t)/np.sqrt(df)*np.exp(-t*t/2)))
        return t, p

    def validate(self, strat_rets, bm_rets=None):
        n = len(strat_rets)
        if n < self.min_n:
            return {"status":"FAIL","reason":f"n={n} < {self.min_n}"}
        m=np.mean(strat_rets); s=np.std(strat_rets,ddof=1)
        t_stat, t_pval = self._ttest(strat_rets)
        wins = int(np.sum(strat_rets>0)); wr = wins/n
        sr = (m/max(s,1e-9))*np.sqrt(252) if s>0 else 0
        alpha_pval = 1.0
        if bm_rets is not None and len(bm_rets)>=n:
            ex = strat_rets - bm_rets[:n]
            _, alpha_pval = self._ttest(ex)
        edge_valid = m>0 and t_pval<self.alpha and alpha_pval<self.alpha
        result = {"status":"PASS" if edge_valid else "REJECT",
                  "n":n, "t_stat":round(t_stat,4), "t_pval":round(t_pval,4),
                  "alpha_pval":round(alpha_pval,4),
                  "mean_bps":round(m*10000,2),
                  "sharpe":round(sr,3),
                  "wr_pct":round(wr*100,1),
                  "edge_valid":bool(edge_valid)}
        self.history.append(result)
        return result
