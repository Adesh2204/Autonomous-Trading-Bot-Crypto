"""Read-only exchange check for the carry basket: positions, open orders, equity, 24 h funding, leverage."""
import sys, json, time
from decimal import Decimal as D
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "algo-trading-bot"))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.venue_profiles import venue_profile
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.testnet_certification import TEAM
c = HyperliquidClient(venue=venue_profile('pas')); c.startup()
a = HyperliquidAccount(c, TEAM)
pos = {s: p for s, p in a.get_positions().items() if p.quantity}
orders = a.get_frontend_open_orders()
eq = a.get_equity()
print('team', TEAM)
print('positions', {s: (str(p.quantity), str(p.entry_price)) for s, p in pos.items()})
print('open_orders', len(orders), orders[:5])
print('equity', eq)
now = int(time.time()*1000)
for s in ('pas:BTC','pas:ETH','pas:HYPE','pas:SP500','pas:USDJPY'):
    rows = c.post_info('fundingHistory', coin=s, startTime=now-24*3600000)
    r = [D(x['fundingRate']) for x in rows]
    m24 = sum(r)/len(r) if r else None
    aad = c.post_info('activeAssetData', user=TEAM, coin=s)
    spec = c.market(s)
    print(s, 'n', len(r), 'mean24h %.7f' % m24, 'day%% %.3f' % (m24*24*100), 'lev', aad.get('leverage'), 'maxLev', getattr(spec,'max_leverage',None), 'szDec', getattr(spec,'size_decimals',None))
