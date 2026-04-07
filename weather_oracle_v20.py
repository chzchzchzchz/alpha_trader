#!/usr/bin/env python3
"""
WEATHER ORACLE v20 — The Real Edge
Fetches LIVE NOAA/NWS forecast data and compares to Kalshi market prices.
If weather.gov says high will be 62°F but market says 84% chance >65°F → NO trade.
This is information arbitrage.
"""
import os, sys, time, json, sqlite3, logging
from datetime import datetime, timezone
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

# City coordinates for weather.gov API
CITIES = {
    "NY": {"lat": 40.7128, "lon": -74.0060},
    "PHIL": {"lat": 39.9526, "lon": -75.1652},
    "LAX": {"lat": 34.0522, "lon": -118.2437},
    "CHI": {"lat": 41.8781, "lon": -87.6298},
    "DAL": {"lat": 32.7767, "lon": -96.7970},
    "MIA": {"lat": 25.7617, "lon": -80.1918},
    "HOUSTON": {"lat": 29.7604, "lon": -95.3698},
}


def fetch_noaa_forecast(lat, lon):
    """Fetch the official NWS point forecast."""
    # Step 1: Get the forecast URL for this lat/lon
    try:
        r = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}", timeout=15,
            headers={"User-Agent": "alphatrader/1.0"}
        )
        if r.status_code != 200: return None
        props = r.json().get("properties", {})
        forecast_url = props.get("forecast")
        
        # Step 2: Get the actual forecast
        r2 = requests.get(forecast_url, timeout=15, headers={"User-Agent": "alphatrader/1.0"})
        if r2.status_code != 200: return None
        
        periods = r2.json().get("properties", {}).get("periods", [])
        
        results = {}
        for p in periods[:6]:  # Next 6 periods (3 days)
            temp = p.get("temperature")  # High or low in F
            is_night = "night" in p.get("shortForecast", "").lower() or "night" in p.get("name", "").lower()
            
            if temp is not None:
                key = "low" if is_night else "high"
                date_str = p.get("startTime", "")
                if date_str[:10] not in results:
                    results[date_str[:10]] = {}
                results[date_str[:10]][key] = temp
        
        return results
    except Exception as e:
        log.warning(f"NWS fetch failed: {e}")
        return None


def parse_date_str(date_str):
    """Extract MMDD from 2026-04-07."""
    return date_str.replace("-", "")


def trade_if_disagreement(ticker, market_yes_bid, market_yes_ask, our_forecast, kalshi_threshold, side_to_bet):
    """
    Compare our weather forecast to Kalshi market.
    Kalshi: market says 84% chance temp >54.5°F
    We check: what does weather.gov actually say?
    
    If weather.gov says 60°F (above 54.5) and market says 16% → YES is underpriced
    If weather.gov says 48°F (below 54.5) and market says 84% → NO is underpriced
    """
    market_yes_price = (market_yes_bid + market_yes_ask) / 2
    
    return {
        "ticker": ticker,
        "our_forecast": our_forecast,
        "kalshi_threshold": kalshi_threshold,
        "market_yes_price": market_yes_price,
        "recommended_side": side_to_bet,
        "confidence": abs(our_forecast - kalshi_threshold),
    }


class WeatherOracle:
    def __init__(self):
        self.client = KalshiClient(
            key_id=KEY_ID, 
            private_key_path=PEM, 
            demo=False
        )
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
        self.executed = {}  # ticker -> ts (cooldown)

    def forecast_date_range(self):
        """Get dates we can forecast (today through next 2 days)."""
        now = datetime.now(timezone.utc)
        return [
            (now + timedelta(days=i)).strftime("%Y-%m-%d") 
            for i in range(3)
        ]
    
    def scan_kalshi_weather_markets(self):
        """Get all open weather markets from Kalshi."""
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
        """Parse KXHIGHNY-26APR07-B54.5 into:
        city=NY, date=20260407, threshold=54.5, is_low=False (B=high)
           KXLOWTPHIL-26APR07-T42 → city=PHIL, date=20260407, threshold=42, is_low=True (T=temp, but LOW)
        Convention: B54.5 = below 54.5 (so threshold is the boundary)
                   T42 = temp above/below 42
        """
        parts = ticker.split("-")
        # KXHIGHNY-26APR07-B54.5 → [KXHIGHNY, 26APR07, B54.5]
        series = parts[0]
        date_part = parts[1]  # 26APR07
        boundary = parts[2]   # B54.5 or T42 or B60.5
        
        # Extract city from series
        city_map = {
            "KXHIGHNY": "NY",
            "KXLOWTPHIL": "PHIL",
            "KXLOWTLAX": "LAX",
            "KXTEMPCHI": "CHI",
            "KXTEMPDAL": "DAL",
            "KXTEMPMIA": "MIA",
            "KXTEMPNYC": "NY",
            "KXTEMPHOUSTON": "HOUSTON",
        }
        
        # Extract year-month-day from 26APR07
        year = "20" + date_part[:2]
        month_str = date_part[2:5]
        day = date_part[5:]
        month_map = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05",
                     "JUN":"06","JUL":"07","AUG":"08","SEP":"09","OCT":"10",
                     "NOV":"11","DEC":"12"}
        month = month_map.get(month_str, "01")
        
        kalshi_date = f"{year}-{month}-{day}"
        threshold = float(boundary[1:])  # Remove B/T prefix
        city = city_map.get(series, "NY")
        
        return city, kalshi_date, threshold, boundary[0]

    def run_forecast_cycle(self):
        """One complete cycle: fetch weather, compare to market, trade edges."""
        log.info(f"\n{'='*60}")
        log.info(f"WEATHER ORACLE CYCLE — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        log.info(f"{'='*60}")
        
        # Step 1: Fetch NOAA forecasts for all cities
        forecasts = {}
        for city_name, coords in CITIES.items():
            data = fetch_noaa_forecast(coords["lat"], coords["lon"])
            if data:
                forecasts[city_name] = data
                log.info(f"  {city_name}: Got forecast for {list(data.keys())}")
                for date_str, temps in data.items():
                    log.info(f"    {date_str}: {temps}")
        
        # Step 2: Scan Kalshi weather markets
        markets = self.scan_kalshi_weather_markets()
        log.info(f"  Found {len(markets)} open Kalshi weather markets")
        
        # Step 3: Compare forecasts → find edges
        trades = 0
        for m in markets:
            ticker = m.get("ticker", "")
            yb = m.get("yes_bid_dollars")
            ya = m.get("yes_ask_dollars")
            vol = m.get("volume_24h_fp", 0) or 0
            vol = float(vol)
            
            if yb is None or ya is None: continue
            
            bid_c = round(float(yb) * 100)
            ask_c = round(float(ya) * 100)
            price = (bid_c + ask_c) / 2.0
            
            try:
                city, kalshi_date, threshold, indicator = self.extract_market_info(ticker)
                series = ticker.rsplit('-', 1)[0]  # KXHIGHNY-26APR07-B54.5 -> KXHIGHNY-26APR07
            except:
                continue
            
            # Check if we have a NWS forecast for this city/date
            if city not in forecasts: continue
            city_data = forecasts[city]
            if kalshi_date not in city_data: continue
            
            nws_temps = city_data[kalshi_date]
            nws_high = nws_temps.get("high")
            nws_low = nws_temps.get("low")
            
            # What does NWS say will happen?
            # Market: "Will high be BELOW threshold?" (B54.5)
            # If NWS says high = 48°F and threshold is 54.5 → YES is very likely
            # If market YES price is 40c → MASSIVE edge → BUY YES
            
            # Determine if this is a high or low market
            if "HIGH" in ticker or indicator == "T":
            
            if nws_relevant is None: continue
            
            # Compare NWS to Kalshi threshold
            diff = nws_relevant - threshold
            
            # Signal logic:
            # B = "High BELOW threshold" YES = temp will be BELOW threshold
            # If NWS says 48 and threshold is 54.5 → diff = -6.5 → definitely BELOW → BUY YES
            # If NWS says 58 and threshold is 54.5 → diff = +3.5 → above → BUY NO
            should_buy_yes = False
            confidence_pct = 0
            
            if diff <= -5:
                # Temp will be at least 5° BELOW threshold → BUY YES (B54.5)
                should_buy_yes = True
                confidence_pct = 85 + min(abs(diff) * 2, 14)  # 85-99%
            elif diff <= -2:
                # Temp 2-5° below → likely below but not certain
                should_buy_yes = True
                confidence_pct = 65 + abs(diff) * 5  # 65-75%
            elif diff >= 5:
                # Temp 5°+ above threshold → BUY NO on B54.5
                should_buy_yes = False  
                confidence_pct = 85 + min(diff * 2, 14)
            elif diff >= 2:
                should_buy_yes = False
                confidence_pct = 65 + diff * 5
            else:
                # Within 2° → too close to call
                continue
            
            # Now check if market price disagrees with us
            market_yes_pct = price / 100.0
            
            if should_buy_yes and (1 - confidence_pct/100) > (1 - market_yes_pct) + 0.10:
                # We're more confident YES than market → edge
                edge = confidence_pct/100 - market_yes_pct
                log.info(f"  EDGE: {ticker} BUY YES | NWS={nws_relevant}° thresh={threshold}° diff={diff:+.1f}° confidence={confidence_pct:.0f}% mkt={market_yes_pct:.0%} edge={edge:+.0%}")
                
                # Execute
                cost = ask_c
                if cost <= 25 and ticker not in self.executed:
                    self.execute_trade(ticker, "yes", cost, nws_relevant, market_yes_pct, edge)
                    trades += 1
                    
            elif not should_buy_yes and (1 - confidence_pct/100) > (1 - (1-market_yes_pct)) + 0.10:
                # We're more confident NO than market → edge
                edge = confidence_pct/100 - (1 - market_yes_pct)
                log.info(f"  EDGE: {ticker} BUY NO | NWS={nws_relevant}° thresh={threshold}° diff={diff:+.1f}° confidence={confidence_pct:.0f}% mkt={1-market_yes_pct:.0%} edge={edge:+.0%}")
                
                no_cost = 100 - bid_c
                if no_cost <= 25 and ticker not in self.executed:
                    self.execute_trade(ticker, "no", no_cost, nws_relevant, 1-market_yes_pct, edge)
                    trades += 1
        
        if trades == 0:
            log.info("  No trades — NWS agrees with Kalshi or no edge found")
        else:
            log.info(f"  Executed {trades} weather-arb trades")

    def execute_trade(self, ticker, side, price_cents, nws_temp, mkt_price, edge):
        """Place order with full logging."""
        try:
            result = self.client.place_order(
                ticker=ticker,
                action="buy",
                side=side,
                count=1,
                yes_price=price_cents if side == "yes" else None,
                no_price=price_cents if side == "no" else None,
            )
            order = result.get("order", {})
            oid = order.get("order_id", "?")
            status = order.get("status", "?")
            
            self.conn.execute(
                "INSERT INTO oracle_trades VALUES (?,?,?,?,?,?,?,?,?)",
                (int(time.time()), ticker, side, price_cents,
                 nws_temp, mkt_price, edge, status, oid))
            self.conn.commit()
            
            self.executed[ticker] = int(time.time())
            
            if status == "executed":
                log.info(f"    ✅ FILLED: {ticker} {side} @ {price_cents}c NWS={nws_temp}° edge={edge:+.0%}")
            else:
                log.info(f"    ⏳ RESTING: {ticker} {side} @ {price_cents}c")
                
        except Exception as e:
            log.error(f"    TRADE FAILED: {e}")

    def run_forever(self):
        log.info("WEATHER ORACLE v20 — Information Arbitrage Engine")
        log.info(f"  Uses NOAA/NWS forecasts vs Kalshi prices")
        
        while True:
            try:
                self.run_forecast_cycle()
                time.sleep(180)  # Refresh every 3 minutes
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Cycle crashed: {e}", exc_info=True)
                time.sleep(30)

from datetime import timedelta

if __name__ == "__main__":
    WeatherOracle().run_forever()