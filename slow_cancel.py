from kalshi.client import KalshiClient
import os, time

client = KalshiClient(
    key_id=os.environ.get('KALSHI_API_KEY_ID'),
    private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
    demo=False
)

cancelled = 0
for attempt in range(5):
    try:
        orders_resp = client.get_orders(limit=100)
        orders = orders_resp.get('orders', [])
        resting = [o for o in orders if o.get('status') == 'resting']
        
        if not resting:
            print(f'No more resting orders. Total cancelled: {cancelled}')
            break
        
        print(f'Attempt {attempt+1}: {len(resting)} resting orders')
        for o in resting[:10]:
            try:
                client.cancel_order(o['order_id'])
                cancelled += 1
            except Exception:
                pass
            time.sleep(1.5)  # Slow down for rate limit
    except Exception as e:
        print(f'Attempt {attempt+1} error: {e}')
        time.sleep(10)

bal = client.get_balance()
print(f'\nFinal: Available=${bal.get("balance",0)/100:.2f} Tied=${bal.get("portfolio_value",0)/100:.2f}')
