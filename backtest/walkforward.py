"""Walk-Forward Backtesting Engine. Tests strategies that ACTUALLY fire."""
from __future__ import annotations
import numpy as np
from typing import Dict, Any

class WalkForwardEngine:
    def __init__(self, slippage_bps=5.0, commission_bps=10.0):
        self.cost = (slippage_bps + commission_bps) / 10000.0

    def _rsi(self, c, p=8):
        d = np.diff(c)
        g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
        ag = np.convolve(g, np.ones(p)/p, mode='valid')
        al = np.convolve(l, np.ones(p)/p, mode='valid')
        rs = np.where(al > 0, ag/al, 100.0)
        return 100 - 100/(1+rs)

    def _ma(self, c, p):
        return np.convolve(c, np.ones(p)/p, mode='valid')

    def _bollinger(self, c, p=10, ns=1.0):
        ma = self._ma(c, p); off = len(c) - len(ma)
        bands = np.array([np.std(c[i+off:i+off+p])*ns for i in range(len(ma))])
        return ma, bands, off

    def _calc_returns(self, close, sigs, offset):
        h = False; ent = 0.0; rets = []
        for i, s in enumerate(sigs):
            p = close[i+offset]
            if not h and s == 1: h = True; ent = p; rets.append(-self.cost)
            elif h and s == -1: rets.append((p-ent)/ent - self.cost); h = False
            else: rets.append(0)
        return np.array(rets)

    def _sharpe(self, r):
        if len(r) < 2 or np.std(r) == 0: return 0.0
        return (np.mean(r)/np.std(r)) * np.sqrt(252)

    def _strat_rsi(self, c, entry=35, exit_t=65):
        rsi = self._rsi(c, 8); off = len(c) - len(rsi)
        sigs = np.zeros(len(rsi), dtype=int); h = False
        for i in range(len(rsi)):
            if not h and rsi[i] < entry: sigs[i] = 1; h = True
            elif h and rsi[i] > exit_t: sigs[i] = -1; h = False
        return sigs, off

    def _strat_bb(self, c, period=10, num_std=1.0):
        ma, bands, off = self._bollinger(c, period, num_std)
        sigs = np.zeros(len(ma), dtype=int); h = False
        for i in range(len(ma)):
            px = c[i+off]
            if not h and px < ma[i] - bands[i]: sigs[i] = 1; h = True
            elif h and (px > ma[i] or px < ma[i] - bands[i]*2): sigs[i] = -1; h = False
        return sigs, off

    def _strat_mom(self, c, period=5):
        mom = np.diff(c, period); off = len(c) - len(mom)
        sigs = np.ones(len(mom), dtype=int)
        for i in range(len(mom)): sigs[i] = 1 if mom[i] > 0 else -1
        return sigs, off

    def run_walk_forward(self, close, strategy='rsi', **kwargs):
        if len(close) < 90:
            return {'status': 'FAIL', 'error': f'Need 90 days, have {len(close)}'}
        te, ve = 60, 75
        tc = close[:te]; vc = close[te:ve]; tsc = close[ve:]
        generators = {
            'rsi': self._strat_rsi,
            'bb': self._strat_bb,
            'mom': self._strat_mom,
        }
        if strategy not in generators:
            return {'status': 'FAIL', 'error': f'Unknown: {strategy}'}
        gen = generators[strategy]
        tsigs, toff = gen(tc, **kwargs)
        tre = self._calc_returns(tc, tsigs, toff)
        tsh = self._sharpe(tre)
        vsigs, voff = gen(vc, **kwargs)
        vre = self._calc_returns(vc, vsigs, voff)
        vsh = self._sharpe(vre)
        ssigs, soff = gen(tsc, **kwargs)
        sre = self._calc_returns(tsc, ssigs, soff)
        ssh = self._sharpe(sre)
        tr = np.sum(sre); wins = int(np.sum(sre > 0)); losses = int(np.sum(sre < 0))
        t = wins + losses; wr = wins / max(t, 1)
        st = 'PASS' if ssh >= 0.5 and t >= 2 else 'FAIL'
        return {'status': st, 'strategy': strategy,
                'train_sharpe': round(tsh, 3), 'val_sharpe': round(vsh, 3),
                'oos_sharpe': round(ssh, 3), 'oos_return_pct': round(tr*100, 2),
                'oos_win_rate_pct': round(wr*100, 1), 'oos_trades': t,
                'oos_wins': wins, 'oos_losses': losses}
