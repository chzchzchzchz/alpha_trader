"""Kalshi 15-min crypto direction strategy - autonomous trading."""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
import httpx

class KalshiAutonomous:
    """Finds mispriced 15-min crypto markets on Kalshi."""
    
    def __init__(self, client, min_edge=8, max_bet=20):
        self.client = client
        self.min_edge = min_edge
        self.max_bet = max_bet
        self.trades = []
    
    def get_crypto_momentum(self, symbol="SOL"):
        """Get 24h momentum from CoinGecko (free)."""
        cm = {"SOL":"solana","ETH":"ethereum","BTC":"bitcoin","XRP":"ripple","HYPE":"hyperliquid"}
        cid = cm.get(symbol, "solana")
        try:
            r = httpx.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd&include_24hr_change=true",
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code == 200:
                d = r.json()
                p = d.get(cid, {}).get('usd', 0)
                c = d.get(cid, {}).get('usd_24h_change', 0)
                return {"price": p, "mom": c/100}
        except: pass
        return {"price": 0, "mom": 0}
    
    def detect_edge(self, mkt):
        """Find if market is mispriced vs real momentum."""
        tkr = mkt.get('ticker', '')
        sym = 'SOL'
        if 'ETH' in tkr: sym = 'ETH'
        elif 'BTC' in tkr: sym = 'BTC'
        elif 'XRP' in tkr: sym = 'XRP'
        
        yb = mkt.get('yes_bid', 0)
        mom = self.get_crypto_momentum(sym)
        
        if yb <= 0 or mom['price'] == 0:
            return None
        
        implied = yb / 100.0
        momentum = mom['mom']
        
        # If 24h momentum > 2% AND implied < 45c -> BUY YES
        if momentum > 0.02 and implied < 0.45:
            edge = round((momentum - implied) * 100, 1)
            if edge >= self.min_edge:
                return {"ticker": tkr, "side": "yes", "edge": edge,
                        "conf": min(0.80, 0.5 + abs(edge)/200),
                        "mom": momentum, "implied": implied, "price": mom['price']}
        
        # If 24h momentum < -2% AND implied > 55c -> BUY NO
        elif momentum < -0.02 and implied > 0.55:
            edge = round(((1-implied) + momentum) * 100, 1)
            if abs(edge) >= self.min_edge:
                return {"ticker": tkr, "side": "no", "edge": edge,
                        "conf": min(0.80, 0.5 + abs(edge)/200),
                        "mom": momentum, "implied": implied, "price": mom['price']}
        
        return None
    
    def execute(self, edge, capital=500):
        """Place order on Kalshi."""
        if not edge: return {"status": "NONE"}
        
        size = min(self.max_bet, max(1, int(capital * edge['conf'] * 0.15 / 50)))
        
        try:
            r = self.client.place_order(ticker=edge['ticker'], action='buy', side=edge['side'], count=size)
            self.trades.append({"ts": datetime.now(timezone.utc).isoformat(),
                               "ticker": edge['ticker'], "side": edge['side'],
                               "size": size, "edge": edge['edge'], "result": r})
            return {"status": "EXECUTED", "ticker": edge['ticker'], "side": edge['side'], "size": size}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)[:200]}
    
    def run_cycle(self, capital=500):
        """One full cycle."""
        mkts = self.client.get_markets(limit=50)
        m15 = [m for m in mkts if '15M' in m.get('ticker', '')]
        
        print(f"    Found {len(mkts)} markets, {len(m15)} are 15-min crypto")
        
        edges = []
        for m in m15:
            e = self.detect_edge(m)
            if e:
                edges.append(e)
                print(f"      EDGE: {e['ticker']} -> {e['side']} "
                      f"(edge={e['edge']}%, mom={e['mom']:.1%}, implied={e['implied']:.0%}, price=${e['price']})")
        
        if not edges:
            return {"status": "NO_EDGES", "checked": len(m15)}
        
        edges.sort(key=lambda x: abs(x['edge']), reverse=True)
        best = edges[0]
        print(f"    Best: {best['ticker']} {best['side']} edge={best['edge']}%")
        
        return self.execute(best, capital)
    
    def get_trades(self):
        return self.trades
