
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalshi.client import KalshiClient

client = KalshiClient(
    key_id=os.environ.get('KALSHI_API_KEY_ID'),
    private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
    demo=False
)

r = client.get_markets(series_ticker='KXINX', limit=10)
mkts = r.get('markets', [])
print(f'Got {len(mkts)} markets')
for m in mkts[:5]:
    bc = m.get('yes_bid_dollars')
    ac = m.get('yes_ask_dollars')
    ticker_val = m.get('ticker', '?')
    if bc is not None and ac is not None:
        bc_c = float(bc)*100
        ac_c = float(ac)*100
        vol = m.get('volume_24h_fp', 0) or 0
        print(f'  {ticker_val}: bid={bc_c:.0f}c ask={ac_c:.0f}c vol={vol:.0f}')
        print(f'    yes_bid={bc}, yes_ask={ac}')
    else:
        print(f'  {ticker_val}: bid=None ask=None')
        print(f'    keys with bid: {[k for k in m.keys() if "bid" in k.lower() or "ask" in k.lower()]}')
        print(f'    prices: {[k+"="+str(m.get(k)) for k in ["last_price", "yes_bid", "yes_ask"] if m.get(k)]}')
