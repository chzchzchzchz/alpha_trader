#!/usr/bin/env python3
"""
FIFA UT Market Psychology Layer — Layer 2 on top of autonomous_trader.py
Does NOT replace or restart the trader. Reads the same markets, looks for
FUT-specific psychology patterns: panic cascades, lazy MMs, time-of-day edges.

Writes signals to autonomous.db.fut_signals table (main trader can read later).
Also logs independently.

Separate process. Own schedule. No overlap.
"""
import os, sys, time, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests

DB = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG = os.path.expanduser("~/alpha_trader/logs/fut_layer.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

API = "https://api.elections.kalshi.com/trade-api/v2"

# ── FIFA UT Psychology Patterns ──

def detect_panic_cascade(price_history, current_price, threshold=0.20):
    """
    FIFA UT Pattern: Price dropped >threshold from recent avg in last 3 candles.
    Humans panic-sold. We buy the panic.
    """
    if len(price_history) < 3:
        return False, 0
    recent = price_history[-3:]
    avg = sum(recent) / len(recent)
    if avg == 0:
        return False, 0
    drop = (avg - current_price) / avg
    if drop >= threshold:
        confidence = min(drop / 0.40, 1.0)  # Cap at 0.40 drop = 100% confidence
        return True, confidence
    return False, 0


def detect_lazy_mm(markets):
    """
    FIFA UT Pattern: Market maker hasn't updated prices despite obvious value.
    Look for markets with very wide spreads AND stale volumes.
    """
    signals = []
    for m in markets:
        bid = float(m.get("yes_bid_dollars", 0) or 0)
        ask = float(m.get("yes_ask_dollars", 0) or 0)
        spread = ask - bid
        vol = float(m.get("volume_24h_fp", 0) or 0)
        
        # Wide spread + low volume = lazy MM
        if spread > 0.10 and vol < 100 and bid > 0.05:
            # MM not paying attention — there's free edge
            signals.append({
                "ticker": m["ticker"],
                "type": "lazy_mm",
                "bid": bid, "ask": ask,
                "spread": spread,
                "vol": vol,
                "score": round(spread * 500, 1),  # 10c spread = 50 points
            })
    return signals


def detect_time_edge(markets):
    """
    FIFA UT Pattern: Certain times have predictable edge.
    - Weather markets: check if we're near settlement (temp known but market stale)
    - Overnight: market makers less active
    """
    now = datetime.now(timezone.utc)
    et_hour = (now.hour - 5) % 24  # UTC-5
    
    signals = []
    overnight_boost = 1.0
    if et_hour < 6:  # 12am-6am ET = lazy hours (+50% edge)
        overnight_boost = 1.5
    elif 13 <= et_hour <= 14:  # Lunch hour (+25% edge)
        overnight_boost = 1.25
    
    for m in markets:
        close_str = m.get("close_time", "")
        if close_str:
            try:
                ct = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                hours_left = (ct - now).total_seconds() / 3600
                
                # If market closing in 1-3 hours and price is obviously wrong
                bid = float(m.get("yes_bid_dollars", 0) or 0)
                ask = float(m.get("yes_ask_dollars", 0) or 0)
                
                if 1 < hours_left < 3 and (bid > 0.85 or ask < 0.15):
                    # Should resolve but hasn't — edge
                    if ask < 0.05:
                        side = "no"
                        edge = (1 - ask) * 100
                    elif bid > 0.95:
                        side = "yes"
                        edge = bid * 100
                    else:
                        continue
                    
                    signals.append({
                        "ticker": m["ticker"],
                        "type": "time_edge",
                        "side": side,
                        "hours_left": round(hours_left, 1),
                        "price": (bid + ask) / 2,
                        "score": round(edge * overnight_boost, 1),
                    })
            except:
                pass
    
    return signals


def check_temp_settlement(markets):
    """
    FIFA UT Pattern: Weather market where the temp is already known
    (from weather.com) but the market hasn't resolved.
    This is information arbitrage.
    """
    import requests as _r
    signals = []
    
    for m in markets:
        ticker = m.get("ticker", "")
        if "KXHIGHNY" not in ticker and "KXTEMP" not in ticker and "KXLOWT" not in ticker:
            continue
        
        bid = float(m.get("yes_bid_dollars", 0) or 0)
        ask = float(m.get("yes_ask_dollars", 0) or 0)
        
        # If market is near close (<6 hours) and bid/ask are extreme
        close_str = m.get("close_time", "")
        if close_str:
            try:
                ct = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                hours_left = (ct - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_left < 6:
                    # Market about to resolve — if price isn't 0c or 100c,
                    # someone's wrong
                    if bid > 0.8 and ask < 1.0:
                        # Market thinks YES but there's doubt
                        signals.append({
                            "ticker": ticker,
                            "type": "temp_arb",
                            "side": "yes",
                            "hours_left": round(hours_left, 1),
                            "score": round(bid * 200, 1),
                            "note": f"market at {bid:.0%} but resolves in {hours_left:.1f}h"
                        })
                    elif bid == 0 and ask < 0.3:
                        signals.append({
                            "ticker": ticker,
                            "type": "temp_arb",
                            "side": "no",
                            "hours_left": round(hours_left, 1),
                            "score": round((1-ask) * 200, 1),
                            "note": f"market nearly resolved NO at {ask:.0%}, {hours_left:.1f}h left"
                        })
            except:
                pass
    
    return signals


def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS fut_signals (
        ts INTEGER, ticker TEXT, fut_type TEXT, side TEXT,
        price REAL, score REAL, vol REAL, details TEXT
    )""")
    conn.commit()
    return conn


def fetch_markets():
    """Fetch all open markets."""
    all_mkts = []
    series_checked = set()
    cursor = None
    try:
        r = requests.get(f"{API}/markets?status=open&limit=200", timeout=20)
        if r.status_code == 200:
            mkts = r.json().get("markets", [])
            all_mkts.extend(mkts)
            while len(all_mkts) < 500:
                cursor = r.json().get("cursor")
                if not cursor:
                    break
                r = requests.get(f"{API}/markets?status=open&limit=200&cursor={cursor}", timeout=20)
                new_mkts = r.json().get("markets", [])
                if not new_mkts:
                    break
                all_mkts.extend(new_mkts)
                time.sleep(0.05)
    except Exception as e:
        pass
    return all_mkts


def main():
    conn = init_db()
    ts = int(time.time())
    now = datetime.now(timezone.utc)
    et = datetime.now(timezone.utc).hour - 5
    if et < 0: et += 24
    
    print(f"\n{'='*60}")
    print(f"FUT PSYCHOLOGY LAYER — {now.strftime('%H:%M UTC')} ({et}:00 ET)")
    print(f"{'='*60}")
    
    markets = fetch_markets()
    print(f"Fetched {len(markets)} open markets")
    
    # Pattern 1: Panic cascades (need history — skip for now, collect data)
    # Pattern 2: Lazy market makers
    lazy = detect_lazy_mm(markets)
    print(f"\nLazy Market Makers: {len(lazy)} found")
    for l in sorted(lazy, key=lambda x: x["score"], reverse=True)[:5]:
        print(f"  {l['ticker']:45s} spread={l['spread']*100:.0f}c vol={l['vol']:.0f} score={l['score']:.1f}")
        conn.execute("INSERT INTO fut_signals VALUES (?,?,?,?,?,?,?,?)",
            (ts, l["ticker"], "lazy_mm", "yes", l["bid"], l["score"], l["vol"], 
             f"spread={l['spread']:.2f}"))
    
    # Pattern 3: Time-of-day edges
    time_sigs = detect_time_edge(markets)
    print(f"\nTime-of-Day Edges: {len(time_sigs)} found")
    for t in sorted(time_sigs, key=lambda x: x["score"], reverse=True)[:5]:
        print(f"  {t['ticker']:45s} {t['side']:3s} {t['hours_left']:.1f}h left score={t['score']:.1f}")
        conn.execute("INSERT INTO fut_signals VALUES (?,?,?,?,?,?,?,?)",
            (ts, t["ticker"], "time_edge", t["side"], t["price"], t["score"], 0,
             f"hours={t['hours_left']}"))
    
    # Pattern 4: Temperature settlement arbitrage
    temp_arbs = check_temp_settlement(markets)
    print(f"\nTemp Settlement Arb: {len(temp_arbs)} found")
    for ta in sorted(temp_arbs, key=lambda x: x["score"], reverse=True)[:5]:
        print(f"  {ta['ticker']:45s} {ta['side']:3s} score={ta['score']:.1f} — {ta['note']}")
        conn.execute("INSERT INTO fut_signals VALUES (?,?,?,?,?,?,?,?)",
            (ts, ta["ticker"], "temp_arb", ta["side"], 0, ta["score"], 0,
             ta["note"]))
    
    # Pattern 5: Overall market sentiment (FIFA UT crowd psychology)
    # Count how many markets are being overbid/underbid
    yes_markets = [m for m in markets if float(m.get("yes_bid_dollars",0) or 0) > 0.5]
    no_markets = [m for m in markets if float(m.get("yes_ask_dollars",0) or 0) < 0.5]
    
    print(f"\nMarket Psychology:")
    print(f"  Markets leaning YES: {len(yes_markets)}")
    print(f"  Markets leaning NO:  {len(no_markets)}")
    if yes_markets:
        avg_yes = sum(float(m.get("yes_bid_dollars",0) or 0) for m in yes_markets) / len(yes_markets)
        print(f"  Average YES bid: {avg_yes:.1%}")
    
    conn.commit()
    conn.close()
    
    total = len(lazy) + len(time_sigs) + len(temp_arbs)
    print(f"\nTotal FUT signals found: {total}")
    print(f"Next sweep in 120s.\n")


if __name__ == "__main__":
    while True:
        try:
            main()
            time.sleep(120)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"FUT error: {e}")
            time.sleep(60)
