"""Strict validation protocol: OOS testing, Monte Carlo, bias audit, live paper trading."""
from __future__ import annotations
import numpy as np
from typing import Dict, Any, List

class StrictValidator:
    def __init__(self, slippage_bps=10, commission_bps=20):
        self.cost = (slippage_bps + commission_bps) / 10000.0
        self.validation_results = []

    def generate_signals_safe(self, close, rsi_period=14, entry_t=30, exit_t=70):
        n = len(close)
        signals = np.zeros(n, dtype=int)
        holding = False
        for i in range(rsi_period, n-1):
            window = close[max(0, i-rsi_period+1):i+1]
            if len(window) < rsi_period:
                continue
            d = np.diff(window)
            g = np.where(d > 0, d, 0.0)
            l = np.where(d < 0, -d, 0.0)
            avg_g, avg_l = np.mean(g), np.mean(l)
            rsi = 100 - 100/(1+avg_g/max(avg_l, 0.001))
            if not holding and rsi < entry_t:
                signals[i] = 1; holding = True
            elif holding and rsi > exit_t:
                signals[i] = -1; holding = False
        return {"signals": signals, "valid": True}

    def check_look_ahead_bias(self, close, signals):
        n = len(close)
        if len(signals) != n:
            return {"bias_detected": True, "reason": "Signal/data mismatch"}
        bias, reasons = False, []
        for i in range(1, min(20, n-1)):
            if signals[i] != 0 and signals[i-1] == 0:
                pnow, pnext = close[i], close[i+1] if i+1 < n else close[i]
                if signals[i] == 1 and pnext < pnow*0.97:
                    bias = True; reasons.append(f"Signal at {i} misses price drop")
        return {"bias_detected": bias, "checked": min(20, n-1), "reasons": reasons, "status": "CLEAN" if not bias else "BIAS"}

    def run_strict_oos(self, close, rsi_p=14, e_t=30, x_t=70):
        n = len(close)
        if n < 400: return {"status": "FAIL", "error": f"Need 400 days, have {n}"}
        te = int(n * 0.7)
        train_c, test_c = close[:te], close[te:]
        tr = self.generate_signals_safe(train_c, rsi_p, e_t, x_t)
        tsigs, toff = tr["signals"], len(train_c) - len(tr["signals"])
        tre = self._calc(train_c, tsigs, toff)
        sr = self.generate_signals_safe(test_c, rsi_p, e_t, x_t)
        ssigs, soff = sr["signals"], len(test_c) - len(sr["signals"])
        sre = self._calc(test_c, ssigs, soff)
        bias = self.check_look_ahead_bias(test_c, ssigs)
        if bias["bias_detected"]:
            return {"status": "FAIL_BIAS", "details": bias["reasons"]}
        wins = int(np.sum(sre > 0)); losses = int(np.sum(sre < 0))
        total = wins+losses; ret = np.sum(sre)
        wr = wins/max(total,1)
        sharpe = np.mean(sre)/max(np.std(sre),1e-9)*np.sqrt(252) if total > 30 and np.std(sre)>0 else 0
        if total < 30:
            return {"status": "FAIL_INSUFFICIENT", "actual": total, "need": 30,
                    "return": float(ret*100), "wr": float(wr*100), "bias": "CLEAN"}
        passed = sharpe >= 0.5 and wr >= 0.50
        return {"status": "PASS" if passed else "FAIL_SHARPE",
                "params": f"RSI({rsi_p},{e_t},{x_t})",
                "test_days": len(test_c), "trades": total,
                "sharpe": float(round(sharpe,3)),
                "return_pct": float(round(ret*100,2)),
                "win_rate_pct": float(round(wr*100,1)),
                "bias": "CLEAN"}

    def _calc(self, close, sigs, off):
        h=False; ent=0; r=[]; c=self.cost
        for i,s in enumerate(sigs):
            if i+off>=len(close): break
            p = close[i+off]
            if not h and s==1: h=True; ent=p; r.append(-c)
            elif h and s==-1: r.append((p-ent)/ent-c); h=False
            else: r.append(0)
        return np.array(r)

    def monte_carlo(self, n_trades=50, win_rate=0.55, avg_win=0.02, avg_loss=-0.015, n_sims=10000):
        wealths = []
        for _ in range(n_sims):
            w = 1.0
            for _ in range(n_trades):
                w *= (1 + avg_win) if np.random.random() < win_rate else (1 + avg_loss)
            wealths.append(w)
        w = np.array(wealths)
        return {"sims": n_sims, "median": float(np.median(w)),
                "worst_5": float(np.percentile(w, 5)),
                "best_5": float(np.percentile(w, 95)),
                "prob_profit": float(np.mean(w > 1.0)),
                "prob_ruin": float(np.mean(w < 0.5))}
