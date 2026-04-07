#!/usr/bin/env python3
"""
WEATHER ORACLE v22 — FIXED. Uses NOAA/NWS forecasts vs Kalshi prices.
Only trades THRESHOLD contracts (T=above/below), skips RANGE (B) contracts.
Reads actual YES/NO labels from Kalshi to determine direction.
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
        forecast_url = r.json().get("properties", {}).get("forecast")
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
    except:
        return None


class WeatherOracle:
    def __init__(self):
        self.client = KalshiClient(key_id=KEY_ID, private_key_path=PEM, demo=False)
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS oracle_trades (
                ts INTEGER, ticker TEXT, side TEXT, price INTEGER,
                our_forecast REAL, kalshi_price REAL, 
                edge REAL, status TEXT, order_id TEXT
            );
        """)
        self.conn.commit()
        self.executed = {}

    def scan_markets(self):
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

    def parse_contract(self, ticker, yes_sub):
        """Returns: (is_above, threshold) or None if unparseable.
        is_above = True means YES wins if temp > threshold
        is_above = False means YES wins if temp < threshold
        """
        import re
        # Extract numbers and direction words from yes_sub_title
        nums = re.findall(r'(\d+)', yes_sub)
        if not nums:
            return None
        threshold = int(nums[0])
        
        is_above = "above" in yes_sub.lower()
        is_below = "below" in yes_sub.lower()
        
        if is_above:
            return (True, threshold)
        elif is_below:
            return (False, threshold)
        else:
            # Range contract (e.g. "54° to 55°") — skip
            return None

    def run_cycle(self):
        log.info(f"\n{'='*60}")
        log.info(f"WEATHER ORACLE v22 — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        log.info(f"{'='*60}")

        # 1. Fetch NWS
        forecasts = {}
        for city, coords in CITIES.items():
            data = fetch_noaa_forecast(coords["lat"], coords["lon"])
            if data:
                forecasts[city] = data
                for d, t in data.items():
                    log.info(f"  {city} {d}: {t}")

        # 2. Scan markets
        markets = self.scan_markets()
        log.info(f"Found {len(markets)} markets")

        trades = 0
        for m in markets:
            ticker = m.get("ticker", "")
            yb = m.get("yes_bid_dollars")
            ya = m.get("yes_ask_dollars")
            yes_sub = m.get("yes_sub_title", "")
            vol = float(m.get("volume_24h_fp", 0) or 0)

            if yb is None or ya is None: continue
            bid_c = round(float(yb) * 100)
            ask_c = round(float(ya) * 100)
            if vol < 100: continue

            # Parse contract direction
            contract_info = self.parse_contract(ticker, yes_sub)
            if contract_info is None:
                continue  # Skip range contracts
            is_above, threshold = contract_info

            # Parse date and city from ticker
            parts = ticker.split("-")
            if len(parts) < 3: continue
            series = parts[0]
            date_part = parts[1]
            
            city_map = {
                "KXHIGHNY": "NY", "KXLOWTPHIL": "PHIL", "KXLOWTLAX": "LAX",
                "KXTEMPCHI": "CHI", "KXTEMPDAL": "DAL", "KXTEMPMIA": "MIA",
                "KXTEMPNYC": "NY", "KXTEMPHOUSTON": "HOUSTON",
            }
            month_map = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05",
                         "JUN":"06","JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
            try:
                year = "20" + date_part[:2]
                month = month_map.get(date_part[2:5], "01")
                day = date_part[5:]
                kalshi_date = f"{year}-{month}-{day}"
            except: continue
            
            city = city_map.get(series)
            if not city or city not in forecasts: continue
            if kalshi_date not in forecasts[city]: continue
            
            fc = forecasts[city][kalshi_date]
            # Use high or low based on series
            nws_temp = fc.get("high") if "HIGH" in series else fc.get("low")
            if nws_temp is None: continue

            # YES wins if: is_above AND temp > threshold, OR is_below AND temp < threshold
            if is_above:
                diff = nws_temp - threshold
                our_yes_conf = min(0.95, 0.5 + diff * 0.06) if diff > 0 else max(0.05, 0.5 + diff * 0.06)
            else:
                diff = threshold - nws_temp
                our_yes_conf = min(0.95, 0.5 + diff * 0.06) if diff > 0 else max(0.05, 0.5 + diff * 0.06)

            market_yes = ask_c / 100.0
            
            # Trade if edge > 12%
            if our_yes_conf > market_yes + 0.12 and ask_c <= 30:
                edge = our_yes_conf - market_yes
                if ticker not in self.executed:
                    log.info(f"  🟢 YES: {ticker} | NWS={nws_temp}° vs Thresh={threshold}° ({'above' if is_above else 'below'}) | YES_Conf={our_yes_conf:.0%} vs Mkt={market_yes:.0%} | Edge=+{edge:.0%} | Cost={ask_c}c | Vol={vol:.0f}")
                    self.execute_trade(ticker, "yes", ask_c, nws_temp, market_yes, edge)
                    trades += 1
            elif (1 - our_yes_conf) > (1 - market_yes) + 0.12 and (100 - bid_c) <= 30:
                no_cost = 100 - bid_c
                edge = (1 - our_yes_conf) - (1 - bid_c / 100.0)
                if ticker not in self.executed:
                    log.info(f"  🔴 NO: {ticker} | NWS={nws_temp}° vs Thresh={threshold}° ({'above' if is_above else 'below'}) | NO_Conf={1-our_yes_conf:.0%} vs Mkt_NO={1-market_yes:.0%} | Edge=+{edge:.0%} | Cost={no_cost}c | Vol={vol:.0f}")
                    self.execute_trade(ticker, "no", no_cost, nws_temp, market_yes, edge)
                    trades += 1
            else:
                diff_pct = abs(our_yes_conf - market_yes)
                log.debug(f"  Skip {ticker}: NWS={nws_temp}° Thresh={threshold}° {'above' if is_above else 'below'} Conf={our_yes_conf:.0%} Mkt={market_yes:.0%} | Edge={diff_pct:.0%} (need >12%)")

        if trades == 0:
            log.info("No trades — markets are efficient")
        else:
            log.info(f"Executed {trades} trades")

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
        log.info("WEATHER ORACLE v22 — NOAA Information Arbitrage")
        log.info("  ONLY trades threshold (T) contracts, skips range (B)")
        log.info("  Reads YES/NO labels from Kalshi API")
        while True:
            try:
                self.run_cycle()
                time.sleep(180)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Crash: {e}", exc_info=True)
                time.sleep(30)

if __name__ == "__main__":
    WeatherOracle().run_forever()
