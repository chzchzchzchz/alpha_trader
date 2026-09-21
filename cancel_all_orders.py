from kalshi.client import KalshiClient
import os

client = KalshiClient(
    key_id=os.environ.get('KALSHI_API_KEY_ID'),
    private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
    demo=False
)

print('=== Current Balance ===')
bal = client.get_balance()
cents = bal.get('balance', 0)
port = bal.get('portfolio_value', 0)
print(f'Available: ${cents/100:.2f} | Tied up: ${port/100:.2f} | Total: ${(cents+port)/100:.2f}')

print('\n=== Cancelling ALL Resting Orders ===')
total_cancelled = 0

try:
    orders_resp = client.get_orders(limit=100)
    orders = orders_resp.get('orders', [])
    print(f'Found {len(orders)} total orders')

    for o in orders:
        status = o.get('status', '')
        oid = o.get('order_id', '')
        ticker = o.get('ticker', '?')
        
        if status == 'resting':
            try:
                client.cancel_order(oid)
                total_cancelled += 1
                print(f'  CANCELLED: {ticker}')
            except Exception as e:
                print(f'  FAILED {ticker}: {e}')
        elif status == 'executed':
            side = o.get('side', '?')
            yes_price = o.get('yes_price_dollars') or o.get('no_price_dollars')
            print(f'  EXECUTED (keeping): {ticker} {side} @ {yes_price}')
        else:
            print(f'  Status={status}: {ticker}')
except Exception as e:
    print(f'Error getting orders: {e}')

print(f'\nCancelled {total_cancelled} resting orders')

print('\n=== Balance After Cancel ===')
bal2 = client.get_balance()
cents2 = bal2.get('balance', 0)
port2 = bal2.get('portfolio_value', 0)
print(f'Available: ${cents2/100:.2f} | Tied up: ${port2/100:.2f} | Total: ${(cents2+port2)/100:.2f}')
