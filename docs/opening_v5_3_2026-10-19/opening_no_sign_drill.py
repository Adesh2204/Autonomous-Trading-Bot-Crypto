"""Pure opening-time readiness drill. Every account/approval value is synthetic."""
from pathlib import Path
import json,socket,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from test_activation_v5_2 import ready_report,fake_authority,NOW
from exchange.conditional_activation import readiness_to_dispatch
from exchange.base_exchange import ExchangeError
from exchange.paper_operations import active_source_hash,atomic_json
import builtins,requests

def forbidden(*a,**k):raise AssertionError('NO_PROMPT_NETWORK_OR_SIGNER_IN_PURE_DRILL')
builtins.input=forbidden;socket.socket.connect=forbidden;requests.Session.post=forbidden
outcomes=[]
for fault in ('none','funding','identity','history','unknown','native','source','leverage','account',
 'positions','orders','market_stream','account_stream','signal','capacity','acceptance','expiry'):
 report=ready_report();authority=fake_authority();at=NOW
 if fault=='funding':report['funding']['status']='USDP_ZERO'
 elif fault=='history':report['market_history']={}
 elif fault=='unknown':report['local_execution_state']['status']='BLOCKED_UNRESOLVED_INTENT'
 elif fault=='native':report['native_proof_verification']={}
 elif fault=='source':report['release_verification']['source_hash']='b'*64
 elif fault=='leverage':report['liquidity']['pas:BTC']['active_asset']['leverage']['value']=20
 elif fault=='account':report['account_observed_ms']=NOW-360001
 elif fault=='positions':report['account']['positions']=[{}]
 elif fault=='orders':report['account']['open_orders']=[{}]
 elif fault=='market_stream':report['stream_reconciled']=False
 elif fault=='account_stream':report['account_stream_healthy']=False
 elif fault=='signal':report['signals']=[]
 elif fault=='capacity':report['liquidity']['pas:BTC']['evidence_evaluation']['economically_viable_notional']='0'
 elif fault=='expiry':at=authority.m.daily.expires_ms
 if fault in {'identity','acceptance','expiry'}:
  def refused():raise ExchangeError('SYNTHETIC_EXACT_AUTHORITY_CHECK_FAILED')
  authority.require=refused
 try:ready=readiness_to_dispatch(report,authority,at);error=None
 except ExchangeError as exc:ready=False;error=str(exc)
 assert ready==(fault=='none'),fault
 outcomes.append(dict(scenario=fault,eligible_for_final_runtime_preflight=ready,reason=error,
  signatures_created=0,exchange_writes=0,prompts=0))
result=dict(source_hash=active_source_hash(ROOT),fixture_only=True,kind='PURE_NO_SIGN_NO_TRANSPORT_READINESS_DRILL',
 time_basis='Readiness fixture is inside the exact scored UTC interval; exact boundary tests are in test_scored_opening_release.py',
 outcomes=outcomes,signatures_created=0,exchange_writes=0,actual_acceptance_created=False,
 actual_account_or_venue_qualified=False,actual_realized_pnl=None,
 lifecycle_evidence='Separate full-suite PAS offline ephemeral-SDK lifecycle tests exercise entry, fills, protection, exits, accounting and expiry; they are synthetic and are not no-sign or venue qualification evidence.')
atomic_json(OUT/'opening_no_sign_drill.json',result)
print(json.dumps(dict(scenarios=len(outcomes),all_expected=True,signatures_created=0,exchange_writes=0)))
