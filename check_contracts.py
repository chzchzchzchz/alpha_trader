#!/usr/bin/env python3
"""
Check actual contract direction definitions by fetching market detail.
"""
import os, sys
sys.path.insert(0, '~/alpha_trader')
from kalshi.client import KalshiClient

client = KalshiClient(
    key_id='REDACTED_KALSHI_KEY_ID',
    private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
    demo=False
)

# Fetch the markets using series_ticker
r = client.get_markets(series_ticker="KXHIGHNY", status="open", limit=20)
mkt = r.get('markets', [])

for m in sorted(mkt, key=lambda x: x.get('ticker','')):
    ticker = m.get('ticker', '?')
    title = m.get('title', '?')
    yes_sub = m.get('yes_sub_title', '?')
    no_sub = m.get('no_sub_title', '?')
    yb = round(float(m.get('yes_bid_dollars',0) or 0)*100)
    ya = round(float(m.get('yes_ask_dollars',0) or 0)*100)
    
    print(f"\n{ticker}:")
    print(f"  YES({yb}-{ya}c): {yes_sub}")
    print(f"  NO:              {no_sub}")
    print(f"  Title:           {title}")
