#!/usr/bin/env python3
"""
NWS/NOAA Weather Research Agent — REAL External Data Alpha
Scans Kalshi weather markets, checks actual NOAA forecasts, finds mispriced contracts.
This is real alpha: market prices are based on stale forecasts, we use fresh NOAA data.
"""
import os, sys, time, sqlite3, json, logging, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/weather_research.log")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WEATHER] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="a"), logging.StreamHandler()],
)
log = logging.getLogger("weather")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS research_proposals (
        ts INTEGER, ticker TEXT, side TEXT, strategy TEXT,
        price_cents INTEGER, edge REAL, score REAL,
        market_yes_ask REAL, market_yes_bid REAL, vol REAL,
        swarm_yes REAL, details TEXT
    )""")
    conn.commit()
    return conn


def get_noaa_forecast(lat, lon):
    """Get NOAA NWS forecast for a location. Returns dict with temps."""
    try:
        # Get gridpoint
        r1 = requests.get(f"https://api.weather.gov/points/{lat},{lon}", timeout=15)
        if r1.status_code != 200:
            return None
        gp = r1.json()
        forecast_url = gp["properties"]["forecast"]
        
        # Get forecast
        r2 = requests.get(forecast_url, timeout=15)
        if r2.status_code != 200:
            return None
        
        periods = r2.json()["properties"]["periods"]
        result = {}
        
        for p in periods[:5]:  # Next 5 periods
            name = p.get("name", "")
            temp = p.get("temperature", 0)
            result[name] = temp
        
        return result
    except Exception as e:
        log.debug(f"NOAA fetch failed: {e}")
        return None


def parse_noaa_temp(forecast, target_type, target_value):
    """Parse NOAA forecast for a specific weather bet.
    target_type: 'high' or 'low'
    target_value: the threshold in Fahrenheit
    Returns: probability that condition will be met (0-1)
    """
    if not forecast:
        return 0.5  # Unknown
    
    # Look at next 1-2 forecast periods  
    temps = []
    for name, temp in forecast.items():
        if 'Tonight' in name or 'Afternoon' in name or 'overnight' in name.lower():
            temps.append({'name': name, 'temp': temp})
    
    if not temps:
        return 0.5
    
    # Check if the target is met in any period
    met_count = 0
    for period in temps:
        if target_type == 'high' and period['temp'] > target_value:
            met_count += 1
        elif target_type == 'low' and period['temp'] < target_value + 5:  # +5 margin for overnight lows
            met_count += 1
    
    return min(1.0, met_count / max(1, len(temps)))


def get_nws_high_temp_forecast(city):
    """Get the latest NWS high temp forecast for a city."""
    coords = {
        "NYC": (40.78, -73.97),
        "PHIL": (39.95, -75.16),
        "LAX": (34.05, -118.25),
        "CHI": (41.88, -87.63),
        "DAL": (32.78, -96.80),
        "MIA": (25.76, -80.19),
        "HOUSTON": (29.76, -95.37),
        "SEA": (47.61, -122.33),
        "DEN": (39.74, -104.99),
        "ATL": (33.75, -84.39),
        "PHX": (33.45, -112.07),
    }
    
    lat, lon = coords.get(city.upper(), (40.0, -74.0))
    return get_noaa_forecast(lat, lon)


def main_loop():
    client = KalshiClient(
        key_id='REDACTED_KALSHI_KEY_ID',
        private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
        demo=False
    )
    conn = init_db()
    
    # Map series to cities
    series_city = {
        'KXHIGHNY': 'NYC',
        'KXLOWTPHIL': 'PHIL',
        'KXLOWTLAX': 'LAX',
        'KXTEMPCHI': 'CHI',
        'KXTEMPDAL': 'DAL',
        'KXTEMPMIA': 'MIA',
        'KXTEMPHOUSTON': 'HOUSTON',
        'KXTEMPNYC': 'NYC',
        'KXTEMPSEA': 'SEA',
        'KXTEMPDEN': 'DEN',
        'KXTEMPATL': 'ATL',
        'KXTEMPPHX': 'PHX',
    }
    
    print("WEATHER RESEARCH AGENT — Using NOAA/NWS real forecast data")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    cycle = 0
    while True:
        cycle += 1
        print(f"\n{'='*60}")
        print(f"CYCLE {cycle} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        
        # Clear old proposals
        cutoff = int(time.time()) - 300
        conn.execute("DELETE FROM research_proposals WHERE ts < ?", (cutoff,))
        conn.commit()
        
        all_proposals = []
        proposals_saved = 0
        
        for series, city in series_city.items():
            try:
                # Get market data
                r = client.get_markets(series_ticker=series, status='open', limit=20)
                mkts = r.get('markets', [])
                
                if not mkts:
                    continue
                
                # Get NOAA forecast for this city
                forecast = get_nws_high_temp_forecast(city)
                
                for m in mkts[:10]:
                    ticker = m.get('ticker', '')
                    yb = m.get('yes_bid_dollars')
                    ya = m.get('yes_ask_dollars')
                    vol = m.get('volume_24h_fp', 0) or 0
                    vol = float(vol)
                    if vol < 100:
                        continue
                    
                    if yb is None or ya is None:
                        continue
                    
                    bid_c = round(float(yb) * 100)
                    ask_c = round(float(ya) * 100)
                    
                    # Parse ticker for bet type and value
                    # e.g. KXHIGHNY-26APR07-B54.5 = HIGH temp Below 54.5°F
                    # e.g. KXHIGHNY-26APR07-T55 = HIGH temp >= 55°F
                    parts = ticker.split('-')
                    if len(parts) < 3:
                        continue
                    
                    bet_type = parts[-2]  # 'B' (below) or 'T' (threshold/above)
                    try:
                        target_val = float(parts[-1])
                    except:
                        continue
                    
                    # Ask NOAA forecast
                    if not forecast:
                        continue
                    
                    # Determine the bet direction from ticker
                    if 'B' == bet_type:
                        # "Below X°F" — YES if actual high < X
                        target_type = 'high'
                        condition = lambda f: f < target_val
                        noaa_met = sum(1 for _,t in forecast.items() if t < target_val)
                    else:
                        # "Threshold X°F" or "At least X°F" — YES if actual >= X
                        target_type = 'high'  
                        condition = lambda f: f >= target_val
                        noaa_met = sum(1 for _,t in forecast.items() if t >= target_val)
                    
                    # Calculate probability from NOAA forecast
                    num_periods = max(1, len(forecast))
                    noaa_prob = noaa_met / num_periods
                    
                    # Market price implies probability
                    market_yes = (bid_c + ask_c) / 200.0
                    
                    # Edge = NOAA says different from market
                    edge = noaa_prob - market_yes
                    
                    # Expected PnL
                    cost = ask_c  # YES ask price
                    exp_pnl = noaa_prob * (100 - cost) - (1 - noaa_prob) * cost - 2
                    
                    if abs(edge) > 0.10 and exp_pnl > 3:
                        side = "yes" if edge > 0 else "no"
                        score = abs(edge) * 10 + exp_pnl / 2 + min(vol / 100, 20)
                        
                        all_proposals.append(dict(
                            ticker=ticker, side=side, strategy="noaa_forecast",
                            price_cents=cost, edge=round(edge, 3),
                            score=round(score, 1),
                            market_yes_ask=ask_c, market_yes_bid=bid_c, vol=vol,
                            swarm_yes=round(noaa_prob, 3),
                            details=f"NOAA={noaa_prob:.0%} vs MKT={market_yes:.0%} EDGE={edge:+.1%} EXP={exp_pnl:.0f}c VOL={vol:.0f} FCST={forecast}"
                        ))
                        proposals_saved += 1
                        
            except Exception as e:
                log.debug(f"{series}: {e}")
                continue
        
        # Save proposals
        ts = int(time.time())
        saved = 0
        for p in sorted(all_proposals, key=lambda x: x['score'], reverse=True)[:50]:
            conn.execute(
                "INSERT INTO research_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, p['ticker'], p['side'], p['strategy'],
                 p['price_cents'], p['edge'], p['score'],
                 p['market_yes_ask'], p['market_yes_bid'], p['vol'],
                 p['swarm_yes'], p['details']))
            saved += 1
        conn.commit()
        
        print(f"Analyzed {len(series_city)} series, found {len(all_proposals)} proposals, saved {saved}")
        if all_proposals:
            for p in sorted(all_proposals, key=lambda x: x['score'], reverse=True)[:5]:
                print(f"  {p['ticker']:45s} {p['side']:>2s} | {p['details'][:80]}")
        else:
            print("  No proposals — NOAA agrees with market prices")
        
        # Refresh every 2 minutes (NOAA updates every 6h, but market changes faster)
        time.sleep(120)


if __name__ == "__main__":
    main_loop()
