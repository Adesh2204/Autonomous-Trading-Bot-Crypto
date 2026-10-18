"""Additional offline partial-entry and sequential-cycle evidence; never venue proof."""
from pathlib import Path
from decimal import Decimal as D
from dataclasses import asdict
import json,sys,tempfile,pytest
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'algo-trading-bot'))
from test_pas_execution_faults import pas_bridge
from test_long_session import enter
from exchange.bounded_daily_session import TradeState
O=Path(__file__).resolve().parent
rows=[]
for scenario in ['partial_entry','two_noninteractive_cycles']:
 with tempfile.TemporaryDirectory(prefix='anchorium_pas_offline_') as tmp:
  m=pytest.MonkeyPatch();m.setenv('HL_DEX','pas');m.setenv('SIGNAL_DATA_MODE','PAS_NATIVE_ONLY')
  g=pas_bridge.__wrapped__(Path(tmp),m);b=next(g)
  try:
   if scenario=='partial_entry':
    b.venue.partial_entry_fraction=D('.5')
    enter(b);held=b.live.account.get_position('pas:BTC')
    assert held and held.quantity % D(1)!=0
    assert not b.live.fixture.orders and b.daily.state!=TradeState.FLAT_VERIFIED
    rows.append(dict(scenario='invalid_fractional_lot_partial_entry',status='OFFLINE_FAILED_SAFE_AS_REQUIRED',
      remaining_quantity=str(held.quantity),state=b.daily.state.value,native_qualification=False,
      actual_wallet_signatures=0,exchange_writes=0))
    continue
   for cycle in range(2 if scenario=='two_noninteractive_cycles' else 1):
    enter(b);held=b.live.account.get_position('pas:BTC');print(scenario,cycle,b.daily.state,held,flush=True);assert held and held.quantity>0
    stop=b.live.fixture.orders[0];assert D(stop['sz'])==held.quantity and stop['reduceOnly'] is True
    price=D(105) if scenario=='two_noninteractive_cycles' and cycle==0 else D(97)
    b.live.fixture.book.update(time=b.live.fixture.now,levels=[[dict(px=str(price),sz='100')],[dict(px=str(price+D('.02')),sz='100')]])
    b.live.fixture.contexts=[dict(markPx=str(price),oraclePx=str(price),funding='.0001',openInterest='10') for _ in b.live.fixture.contexts]
    b.session._close('pas:BTC','Target Hit' if price==105 else 'Stop Loss Hit');assert b.daily.state==TradeState.FLAT_VERIFIED
    b.live.fixture.now=(b.live.fixture.now//60000+1)*60000
   rows.append(dict(scenario=scenario,status='OFFLINE_PASSED',cycles=b.daily.data['cycles'],
    synthetic_signed_actions=len(b.live.transport.signed_payloads),synthetic_fills=[asdict(x) for x in b.recovery.state.fills.values()],
    synthetic_net=b.daily.data['realized_net'],actual_venue_qualified=False,actual_wallet_signatures=0,exchange_writes=0))
  finally:
   try:next(g)
   except StopIteration:pass
   m.undo()
(O/'additional_pas_simulation.json').write_text(json.dumps(dict(source='OFFLINE_EPHEMERAL_FIXTURE_ONLY',results=rows,actual_pnl=None,native_qualification=False),indent=2,default=str)+'\n')
print('ADDITIONAL_OFFLINE_PAS_SCENARIOS_PASSED',len(rows))
