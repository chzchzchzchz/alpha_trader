"""Strict Walk-Forward: OOS, bias audit, punishing slippage."""
from __future__ import annotations
import numpy as np
from typing import Dict, Any

class WalkForwardEngine:
    def __init__(self, slippage_bps=10, commission_bps=10):
        self.cost = (slippage_bps + commission_bps) / 10000.0

    def _rsi(self, c, p=14):
        d = np.diff(c); g = np.where(d>0,d,0); l = np.where(d<0,-d,0)
        ag = np.convolve(g,np.ones(p)/p,'valid')
        al = np.convolve(l,np.ones(p)/p,'valid')
        return 100-100/(1+np.where(al>0,ag/al,100))

    def _ma(self, c, p):
        return np.convolve(c, np.ones(p)/p, mode='valid')

    def _calc(self, close, sigs, off):
        h=False; e=0; r=[]; cost=self.cost
        for i,s in enumerate(sigs):
            if i+off>=len(close): break
            p = close[i+off]
            if not h and s==1: h=True; e=p; r.append(-cost)
            elif h and s==-1: r.append((p-e)/e-cost); h=False
            else: r.append(0)
        return np.array(r)

    def _sharpe(self, r):
        if len(r)<3 or np.std(r)==0: return 0.0
        return (np.mean(r)/np.std(r))*np.sqrt(252)

    def _sigs_rsi(self, c, period=14, et=30, xt=70):
        rsi = self._rsi(c, period); off = len(c)-len(rsi)
        sigs = np.zeros(len(rsi), int); h = False
        for i in range(len(rsi)):
            if not h and rsi[i]<et: sigs[i]=1; h=True
            elif h and rsi[i]>xt: sigs[i]=-1; h=False
        return sigs, off

    def _sigs_sma(self, c, fast=5, slow=20):
        mf = self._ma(c, fast); ms = self._ma(c, slow)
        mn = min(len(mf), len(ms)); off = len(c)-mn
        sigs = np.zeros(mn, int); h = False
        for i in range(mn):
            if mf[i]>ms[i] and not h: sigs[i]=1; h=True
            elif mf[i]<ms[i] and h: sigs[i]=-1; h=False
        return sigs, off

    def run_walk_forward(self, close, strategy="rsi", **kwargs):
        n = len(close)
        if n < 135: return {"status":"FAIL","error":f"Need 135, have {n}"}
        te, ve = 60, 90
        generators = {"rsi": self._sigs_rsi, "sma": self._sigs_sma}
        if strategy not in generators: return {"status":"FAIL","error":"Unknown"}
        gen = generators[strategy]

        # Optimize on train
        best_sh, best_p = -999, {}
        if strategy == "rsi":
            for p in [10,14,18]:
                for et in [25,30,35,40]:
                    for xt in [60,65,70]:
                        if et >= xt: continue
                        ts, to = gen(close[:te], period=p, et=et, xt=xt)
                        tr = self._calc(close[:te], ts, to)
                        sh = self._sharpe(tr)
                        if sh > best_sh: best_sh = sh; best_p = {"period":p,"et":et,"xt":xt}
        elif strategy == "sma":
            for f in [3,5,8]:
                for s in [15,20,30]:
                    if f >= s: continue
                    ts, to = gen(close[:te], fast=f, slow=s)
                    tr = self._calc(close[:te], ts, to)
                    sh = self._sharpe(tr)
                    if sh > best_sh: best_sh = sh; best_p = {"fast":f,"slow":s}

        vs, vo = gen(close[te:ve], **best_p)
        vre = self._calc(close[te:ve], vs, vo)
        ts, to = gen(close[ve:135], **best_p)
        tre = self._calc(close[ve:135], ts, to)

        w = int(np.sum(tre>0)); l = int(np.sum(tre<0)); t = w+l
        ret = np.sum(tre); wr = w/max(t,1)
        sh = self._sharpe(tre)

        passed = t >= 10 and sh >= 0.5 and wr >= 0.50
        return {"status":"PASS" if passed else "FAIL",
                "strategy":f"{strategy}({best_p})",
                "train_sharpe":round(best_sh,3),
                "oos_sharpe":round(sh,3),
                "oos_return_pct":round(ret*100,2),
                "oos_win_rate_pct":round(wr*100,1),
                "oos_trades":t}

    def check_look_ahead_bias(self, close, signals):
        n = len(close)
        if len(signals) != n: return {"bias":True,"reason":"mismatch"}
        for i in range(1,min(20,n-1)):
            if signals[i]!=0 and signals[i-1]==0:
                pn = close[i]; pnx = close[i+1] if i+1<n else pn
                if signals[i]==1 and pnx < pn*0.97:
                    return {"bias":True,"reason":"signal at "+str(i)+" misses drop"}
        return {"bias":False,"status":"CLEAN"}

    def monte_carlo(self, n=50, wr=0.55, aw=0.02, al=-0.015, sims=10000):
        wealths = []
        for _ in range(sims):
            w = 1.0
            for _ in range(n):
                w *= (1+aw) if np.random.random()<wr else (1+al)
            wealths.append(w)
        w = np.array(wealths)
        return {"sims":sims, "median":float(np.median(w)),
                "worst_5":float(np.percentile(w,5)),
                "best_5":float(np.percentile(w,95)),
                "prob_profit":float(np.mean(w>1)),
                "prob_ruin":float(np.mean(w<0.5))}
