"""Cancel ALL resting orders and report real status."""
import os, sys
sys.path.insert(0, '~/alpha_trader')
from kalshi.client import KalshiClient

client = KalshiClient(
    key_id='REDACTED_KALSHI_KEY_ID',
    private_key_path=os.path.expanduser('~/.kalshi/private_key.pem'),
    demo=False
)

# Balance
bal = client.get_balance()
cash = bal.get('balance', 0)
exposure = bal.get('portfolio_value', 0)
print(f'Cash:      ${cash/100:.2f}')
print(f'Exposure:  ${exposure/100:.2f}')
print(f'Total:     ${(cash+exposure)/100:.2f}')

# All orders
resp = client.get_orders(limit=200)
orders = resp.get('orders', [])
resting = [o for o in orders if o.get('status') == 'resting']
executed = [o for o in orders if o.get('status') == 'executed']
other = [o for o in orders if o.get('status') not in ('resting', 'executed')]

print(f'\nTotal orders: {len(orders)}')
print(f'  Resting:   {len(resting)}')
print(f'  Executed:  {len(executed)}')
print(f'  Other:     {len(other)}')

# Cancel all resting
cancelled = 0
failed = 0
for o in sorted(resting, key=lambda x: x.get('ticker', '')):
    oid = o.get('order_id', '')
    ticker = o.get('ticker', '?')
    try:
        client.cancel_order(oid)
        cancelled += 1
        print(f'  CANCELLED: {ticker} ({oid[:12]})')
    except Exception as e:
        failed += 1
        print(f'  FAILED:    {ticker}: {str(e)[:80]}')

print(f'\nCancelled {cancelled}/{len(resting)} resting orders ({failed} failed)')

# Final balance
bal2 = client.get_balance()
cash2 = bal2.get('balance', 0)
exp2 = bal2.get('portfolio_value', 0)
print(f'\nAfter cancel:')
print(f'  Cash:      ${cash2/100:.2f} (was ${cash/100:.2f})')
print(f'  Exposure:  ${exp2/100:.2f} (was ${exposure/100:.2f})')
print(f'  Total:     ${(cash2+exp2)/100:.2f} (was ${(cash+exposure)/100:.2f})')
print()

# Show executed positions
if executed:
    print('EXECUTED POSITIONS (still open, will settle):')
    for o in executed:
        ticker = o.get('ticker', '?')
        side = o.get('side', '?')
        yes_price = o.get('yes_price_dollars', '?')
        count = o.get('count', '?')
        print(f'  {ticker:50s} {side:>3s} x{count} @ {float(yes_price or 0)*100:.0f}c')
