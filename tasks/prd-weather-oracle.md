# PRD v21: Weather Oracle — Information Arbitrage
## The Alpha: NOAA/NWS weather forecasts vs Kalshi market prices.
## If weather.gov says high = 48 but market says 84% YES temp >54.5 → we know NO is way undervalued.
## This is REAL edge — external data the market hasn't priced in.
## Implementation:
1. Fetch NWS forecast for NY, PHIL, LAX, CHI, DAL, MIA, HOUSTON
2. Compare to ALL open Kalshi weather tickers
3. If NWS disagrees with market >5° → EXECUTE
4. Log everything
