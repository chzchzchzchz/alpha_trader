#!/usr/bin/env python3
"""
WEATHER ORACLE v21 — The Real Edge
Fetches LIVE NOAA/NWS forecast data and compares to Kalshi market prices.
If weather.gov says high will be 62°F but market says 84% chance >65°F → NO trade.
"""
import os, sys, time, json, sqlite3, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
LOG_PATH = os.path.expanduser("~/alpha_trader/logs/weather_oracle.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WEATHER] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("weather")

sys.path.insert(0, str(Path(__file__).parent))
from kalshi.client import KalshiClient

KEY_ID = "REDACTED_KALSHI_KEY_ID"
PEM = os.path.expanduser("~/.kalshi/private_key.pem")

CITIES = {
    "NY": {"lat": 40.7128, "lon": -74.0060},
    "PHIL": {"lat": 39.9526, "lon": -75.1652},
    "LAX": {"lat": 34.0522, "lon": -118.2437},
    "CHI": {"lat": 41.8781, "lon": -87.6298},
    "DAL": {"lat": 32.7767, "lon": -96.7970},
    "MIA": {"lat": 25.7617, "lon": -80.1918},
    "HOUSTON": {"lat": 29.7604, "lon": -95.3698},
}

HEADERS = {"User-Agent": "alphatrader/1.0"}


def fetch_noaa_forecast(lat, lon):
    try:
        r = requests.get(f"https://api.weather.gov/points/{lat},{lon}", timeout=15, headers=HEADERS)
        if r.status_code != 200: return None
        props = r.json().get("properties", {})
        forecast_url = props.get("forecast")
        if not forecast_url: return None
        
        r2 = requests.get(forecast_url, timeout=15, headers=HEADERS)
        if r2.status_code != 200: return None
        
        periods = r2.json().get("properties", {}).get("periods", [])
        results = {}
        for p in periods[:6]:
            temp = p.get("temperature")
            is_night = "night" in p.get("name", "").lower()
            if temp is not None:
                key = "low" if is_night else "high"
                date_str = p.get("startTime", "")
                if date_str[:10] not in results:
                    results[date_str[:10]] = {}
                results[date_str[:10]][key] = temp
        return results
    except Exception as e:
        log.debug(f"NWS fetch failed: {e}")
        return None


class WeatherOracle:
    def __init__(self):
        self.client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=False)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS weather_forecasts (
                ts INTEGER, city TEXT, date TEXT,
                nws_high REAL, nws_low REAL,
                kalshi_market TEXT, kalshi_yes_price REAL,
                kalshi_threshold REAL,
                disagreement TEXT, signal TEXT
            );
            CREATE TABLE IF NOT EXISTS oracle_trades (
                ts INTEGER, ticker TEXT, side TEXT, price INTEGER,
                our_forecast REAL, kalshi_price REAL, 
                edge REAL, status TEXT, order_id TEXT
            );
        """)
        self.conn.commit()
        self.executed = {}

    def scan_kalshi_weather_markets(self):
        series_list = ["KXHIGHNY", "KXLOWTPHIL", "KXLOWTLAX", 
                       "KXTEMPCHI", "KXTEMPDAL", "KXTEMPMIA", 
                       "KXTEMPNYC", "KXTEMPHOUSTON"]
        all_mkts = []
        for s in series_list:
            try:
                r = self.client.get_markets(series_ticker=s, status="open", limit=20)
                all_mkts.extend(r.get("markets", []))
            except: pass
        return all_mkts

    def extract_market_info(self, ticker):
        # KXHIGHNY-26APR07-B54.5
        parts = ticker.split("-")
        if len(parts) < 3:
            return None
        series = parts[0]
        date_part = parts[1]
        boundary = parts[2]

        city_map = {
            "KXHIGHNY": "NY", "KXLOWTPHIL": "PHIL", "KXLOWTLAX": "LAX",
            "KXTEMPCHI": "CHI", "KXTEMPDAL": "DAL", "KXTEMPMIA": "MIA",
            "KXTEMPNYC": "NY", "KXTEMPHOUSTON": "HOUSTON",
        }
        month_map = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05",
                     "JUN":"06","JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
        
        try:
            year = "20" + date_part[:2]
            month_str = date_part[2:5]
            day = date_part[5:]
            month = month_map.get(month_str, "01")
            kalshi_date = f"{year}-{month}-{day}"
            threshold = float(boundary[1:])
            indicator = boundary[0]
        except:
            return None
        
        city = city_map.get(series)
        if not city: return None
        
        return city, kalshi_date, threshold, indicator

    def run_forecast_cycle(self):
        log.info(f"\n{'='*60}")
        log.info(f"WEATHER ORACLE CYCLE — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        log.info(f"{'='*60}")
        
        # Step 1: Fetch NOAA forecasts
        forecasts = {}
        for city_name, coords in CITIES.items():
            data = fetch_noaa_forecast(coords["lat"], coords["lon"])
            if data:
                forecasts[city_name] = data
                for date_str, temps in data.items():
                    log.info(f"  {city_name} {date_str}: {temps}")

        # Step 2: Scan Kalshi weather markets
        markets = self.scan_kalshi_weather_markets()
        log.info(f"Found {len(markets)} open Kalshi weather markets")

        trades = 0
        
        # Step 3: Compare
        for m in markets:
            ticker = m.get("ticker", "")
            yb = m.get("yes_bid_dollars")
            ya = m.get("yes_ask_dollars")
            vol = float(m.get("volume_24h_fp", 0) or 0)
            
            if yb is None or ya is None:
                continue
                
            bid_c = round(float(yb) * 100)
            ask_c = round(float(ya) * 100)
            price = (bid_c + ask_c) / 2.0
            
            info = self.extract_market_info(ticker)
            if not info:
                continue
            city, kalshi_date, threshold, indicator = info
            
            # Check if we have a NWS forecast
            if city not in forecasts:
                continue
            city_data = forecasts[city]
            if kalshi_date not in city_data:
                continue
                
            nws_temps = city_data[kalshi_date]
            nws_high = nws_temps.get("high")
            nws_low = nws_temps.get("low")
            
            # Determine relevant temp
            nws_relevant = None
            if "HIGH" in ticker:
                nws_relevant = nws_high
            elif "LOW" in ticker:
                nws_relevant = nws_low
            else:
                # For generic temp markets, use high for day markets
                nws_relevant = nws_high

            if nws_relevant is None:
                continue

            # Market convention: 
            # B54.5 = "High Temp Below 54.5"
            # T42 = "Min Temp Above 42"
            
            if "HIGH" in ticker:
                # Market: High below [threshold]
                if nws_relevant < threshold:
                    # Forecast is BELOW threshold = YES is correct
                    our_confidence = min(0.95, 0.5 + (threshold - nws_relevant) * 0.05)
                else:
                    # Forecast is ABOVE threshold = NO is correct
                    our_confidence = min(0.95, 0.5 + (nws_relevant - threshold) * 0.05)
            else:
                # Market: Low below/above [threshold]
                if nws_relevant < threshold:
                    our_confidence = min(0.95, 0.5 + (threshold - nws_relevant) * 0.04)
                else:
                    our_confidence = min(0.95, 0.5 + (nws_relevant - threshold) * 0.04)

            market_yes_pct = price / 100.0
            market_no_pct = 1.0 - market_yes_pct
            
            # Calculate edge
            # BUY YES if our YES confidence > market_yes_pct + 0.15 (15% edge)
            # BUY NO if our NO confidence (1-our_confidence for YES) > market_no_pct + 0.15
            
            if our_confidence > market_yes_pct + 0.12 and vol > 50:
                cost = ask_c
                if cost <= 30 and ticker not in self.executed:
                    edge_pct = our_confidence - market_yes_pct
                    log.info(f"  🟢 BUY YES: {ticker} | NWS={nws_relevant}° vs Thresh={threshold}° | Conf={our_confidence:.0%} vs Mkt={market_yes_pct:.0%} | Edge=+{edge_pct:.0%} | Cost={cost}c | Vol={vol:.0f}")
                    self.execute_trade(ticker, "yes", cost, nws_relevant, market_yes_pct, edge_pct)
                    trades += 1
            elif (1 - our_confidence) > market_no_pct + 0.12 and vol > 50:
                cost = 100 - bid_c
                if cost <= 30 and ticker not in self.executed:
                    edge_pct = (1 - our_confidence) - market_no_pct
                    log.info(f"  🔴 BUY NO: {ticker} | NWS={nws_relevant}° vs Thresh={threshold}° | Conf={1-our_confidence:.0%} vs Mkt={market_no_pct:.0%} | Edge=+{edge_pct:.0%} | Cost={cost}c | Vol={vol:.0f}")
                    self.execute_trade(ticker, "no", cost, nws_relevant, market_yes_pct, edge_pct)
                    trades += 1
            else:
                log.debug(f"  Skip {ticker}: NWS={nws_relevant}° Thresh={threshold}° Conf={our_confidence:.0%} Mkt={market_yes_pct:.0%} | Edge too small")

        if trades == 0:
            log.info("  No trades — NWS agrees with Kalshi or no edge found")
        else:
            log.info(f"Executed {trades} weather-arb trades")

    def execute_trade(self, ticker, side, price_cents, nws_temp, mkt_price, edge):
        try:
            result = self.client.place_order(
                ticker=ticker, action="buy", side=side, count=1,
                yes_price=price_cents if side == "yes" else None,
                no_price=price_cents if side == "no" else None,
            )
            order = result.get("order", {})
            oid = order.get("order_id", "?")
            status = order.get("status", "?")
            
            self.conn.execute("INSERT INTO oracle_trades VALUES (?,?,?,?,?,?,?,?,?)",
                (int(time.time()), ticker, side, price_cents,
                 nws_temp, mkt_price, edge, status, oid))
            self.conn.commit()
            self.executed[ticker] = int(time.time())
            
            emoji = "✅" if status == "executed" else "⏳"
            log.info(f"    {emoji} {ticker} {side} @ {price_cents}c (NWS={nws_temp}°) [{status}]")
        except Exception as e:
            log.error(f"    TRADE FAILED: {e}")

    def run_forever(self):
        log.info("WEATHER ORACLE v21 — NOAA Information Arbitrage")
        while True:
            try:
                self.run_forecast_cycle()
                time.sleep(180)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Cycle crashed: {e}", exc_info=True)
                time.sleep(30)

if __name__ == "__main__":
    WeatherOracle().run_forever()