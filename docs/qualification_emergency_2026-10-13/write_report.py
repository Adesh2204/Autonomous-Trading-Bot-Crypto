from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,hashlib,sys,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.emergency_qualification import EmergencyProposal,policy_hash,require_emergency_regression,RECOVERY_STEPS
from exchange.qualification_watcher import durable_readback
out=Path(__file__).resolve().parent;obs=out/'final_read_only'
r=json.loads((obs/'readiness.json').read_text());p=EmergencyProposal(**json.loads((obs/'proposal.json').read_text()))
receipt=json.loads((out/'regression_release/test_receipt.json').read_text());before=json.loads((out/'source_before.json').read_text());c=r['selected_candidate']
require_emergency_regression(ROOT,out/'regression_release/test_receipt.json')
assert r['proposal_id']==p.identity and r['source_hash']==r['source_hash_after']==active_source_hash(ROOT)==receipt['source_hash']
assert r['status']=='AWAITING_EXACT_HUMAN_RISK_APPROVAL' and r['actual_wallet_signatures']==r['exchange_submissions']==0
assert c['positions']==[] and c['orders']==[] and c['account_reconciliation']['ready']
assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==s for n,s in before['protected'].items())
cleanup=durable_readback(obs/'read_only.sqlite',r['durable_cleanup']['source_identity'],clean=True)
assert cleanup['snapshots_verified']==2 and not any(cleanup['actions'].values())
assert not (obs/'operator_approval.json').exists() and not list(obs.rglob('WHITELIST_TRADE_PROOF.json'))
verification=dict(verified_at_ms=time.time_ns()//1000000,proposal_id=p.identity,source_bound_full_regression=True,
 source_hash=active_source_hash(ROOT),protected_files_unchanged=True,clean_checkpoints=cleanup,
 account_flat_observed_ms=c['account_ms'],actual_order_authorized=False,signatures=0,exchange_submissions=0,
 actual_fill_verified=False,protection_verified=False,approval_deadline_ms=r['approval_deadline_ms'],
 latest_entry_transmission_ms=r['approval_deadline_ms']-90000)
atomic_json(out/'final_verification.json',verification)
markets=[]
for symbol in r['metadata']:
 x=r['markets'][symbol+':Ioc'];a=r['capacity_inventory'][symbol]
 markets.append(dict(symbol=symbol,asset_id=x['asset_id'],size_step=x['size_step'],
  minimum_ioc_quantity=x.get('minimum_quantity'),minimum_ioc_notional=x.get('minimum_entry_notional'),
  one_lot_notional=x.get('minimum_lot_notional'),cap_lot_quantity=x.get('maximum_lot_rounded_quantity'),
  spread_bps=x.get('spread_bps'),ioc_public_potential=x['potential'],gtc_public_potential=r['markets'][symbol+':Gtc']['potential'],
  blocker=x.get('blocker'),close_assessment=x.get('residuals'),protection_verified=False,capacity=a,
  fees=c['readiness']['fees'],observations_are_snapshots_not_future_permission=True))
atomic_json(out/'market_review.json',markets)
atomic_json(out/'final_summary.json',dict(status=r['status'],proposal_id=p.identity,proposal=r['proposal'],
 test_totals=receipt['totals'],new_tests=91,focused_tests=211,source_hash=receipt['source_hash'],
 preserved_brain_sha256=before['protected']['algo-trading-bot/signal_brain.py'],current_market='par:BTC',
 notional=r['actual_entry_exposure'],approval_deadline_ist=r['approval_deadline_ist'],
 actual_protection_ready=False,normal_controlled_execution_ready=False,isolated_experimental_proposal_ready=True,
 order_authorized=False,actual_fill_verified=False,whitelist_confirmed=False,autonomous_trading_enabled=False,
 next_action='Human exact-proposal risk approval if current; otherwise deliberate read-only re-preparation.',verification=verification))
spread=(float(p.reference_ask)-float(p.reference_bid))/((float(p.reference_ask)+float(p.reference_bid))/2)*10000
cutoff=datetime.fromtimestamp((r['approval_deadline_ms']-90000)/1000,timezone(timedelta(hours=5,minutes=30))).isoformat()
changes=json.loads((out/'source_changes.json').read_text())
text='''# P0 isolated qualification report

## 1. Actual root causes and corrected files

The supplied 300-second V8.9 session recorded 1,414 directional book observations and no Stage A opportunity. The late account refresh was the optional end audit. No eligible trade was demonstrated as missed. The old10%-of-BOTH-best-levels limit prevented the ordinary minimum valid BTC quantity. A larger opening alone does not solve residual closure. The final readiness display incorrectly retained CHECKING_RESIDUAL_EXITS; the terminal display is corrected. The new policy is a separate type/version; old approvals cannot authorize it.

'''+''.join('- '+n+'\n' for n in changes)+'''
## 2. Supported IOC/GTC method

IOC takes at most50% of genuine L2 quantity within a fixed normalized ask+20bps entry limit, with independent exit-depth review within bid-20bps. GTC and optional ALO place one bid-priced limit, monitor actual statuses/team fills for30 seconds from durable transmission, cancel the original remainder once and confirm terminal state before closing. No replacement, enlargement or repeat entry. Local cancellation is not exchange auto expiry. The old10% BBO policy is not falsely labeled as passed.

[Official order and cancellation semantics](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), [orderStatus and L2](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [ordinary minimum errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses). SDK0.24.0 inspected locally.

## 3. Current eligibility

Fresh read-only preparation finished in13.66 seconds, with one durable actual-account reconciliation. The team reported1,000,000 USDPR, unifiedAccount, the matching approved API agent, healthy local nonce ownership/clock/rates, zero positions and zero orders. All ten capacity observations showed1x CROSS. Remote sole-host ownership remains the user's prior human confirmation, not something local software can independently verify. BTC passed final source/account/margin/fee/price/liquidity/residual checks. Other current markets fail residual closure. Each inventory and final account observation has its own timestamp and is not future signing permission.

| Market | One-lot entry notional | Minimum IOC quantity | Spread bps | Result |
|---|---:|---:|---:|---|
'''
for x in markets:
 text+='| '+x['symbol']+' | '+str(x['one_lot_notional'])+' | '+str(x['minimum_ioc_quantity'])+' | '+str(round(float(x['spread_bps']),4))+' | '+('Final BTC risk-review proposal ready' if x['symbol']=='par:BTC' else 'Blocked: unverified residual close')+' |\n'
text+='''
Final BTC reviewed L2 contained1.0264 BTC inside the entry limit and0.6932 BTC inside the immediate-exit limit. These are observed books, not fills. Final spread: '''+str(round(spread,4))+'''bps. Detailed prices, lot mappings, collateral, fees and residual quantities are in market_review.json/readiness.json.

## 4. Exposure and protection risk

Policy opening ceiling1,000 TEST USDPR, not a target or guaranteed maximum total loss. This fixed proposal is16.7160 USDPR. No actual order is authorized. No protective stop is verified or submitted. The exact one-lot BTC closing path uses independently read historical shape evidence, not a universal exception or future acceptance guarantee. Every possible selected whole-lot residual is checked. Disconnect, failed cancel, rejected/uncertain exit, vanished depth or price gap can leave an unprotected position needing separate manual recovery. Fees/funding and shared cross collateral prevent a guaranteed total loss cap. Normal protection/controlled certification remain FALSE; autonomous practice stays locked.

## 5. Tests and frozen strategy

1,984 passed;0 failures/errors/skips. Previous baseline1,893 plus91 new tests. Focused run211 passed. Intermediate failed reports are preserved. Phase-0 and strategy-freeze checks passed before and after full regression, with matching source hashes. signal_brain.py, freeze manifest and reliability/protection configuration are byte-identical. Production .40% ATR,15bps spread,300 bars,Top-3, UTC and strategy state behavior remain intact.

## 6. Exact preparation command

From the cloned project root, choose a new evidence directory:

```sh
.venv/bin/python scripts/run_emergency_qualification.py \\
  --output-directory "docs/qualification_emergency_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \\
  --test-receipt docs/qualification_emergency_2026-10-13/regression_release/test_receipt.json \\
  --duration-seconds 60 --route auto
```

Explicit --route ioc/gtc/alo chooses that preparation route; --transport rest is read-only fallback. The selected proposal authorizes only its exact route, never automatic fallback.

## 7. Exact current proposal and approval

Proposal ID: `'''+p.identity+'''`.

- Team: `'''+p.team_wallet+'''`. API signer: `'''+p.api_wallet+'''`.
- Hyperliquid TESTNET `par`, asset2670000; BUY0.0002 `par:BTC`, IOC limit83580. Maximum selected opening notional16.7160 USDPR.
- Reviewed immediate exit limit83124. Actual SELL reduce-only IOC exits use exact current reconciled quantity and fresh bid minus20bps, never below82045. At most two exits.
- Taker fee rate0.00090. Entry/floor round-trip fee estimate0.029812500 USDPR. Conditional full close at the floor loss estimate0.336812500 USDPR including those fees; not a total-loss guarantee. Actual reported fills/fees/funding/P&L must reconcile.
- Approval expiry: '''+r['approval_deadline_ist']+'''. Entry needs90 seconds remaining, latest transmission cutoff '''+cutoff+'''. Fresh preflight can still reject.
- No verified protective stop. Policy hash `'''+policy_hash()+'''`.

Explicit human approval must name the exact current ID and accept verified-wallet/sole-host assertions, one entry, the separate50bps/50%-L2/20bps policy, NO STOP, possible manual residual recovery, no guaranteed loss cap and one cancel/two exits/lifetime limits. approval_REQUIRED_UNFILLED.json remains blank/false. No operator_approval.json was created. Only a separately approved response may populate it with exact hashes, human text, integer current approval/expiry times and every acknowledgment true. The expiry cannot extend past five minutes from proposal observation. Changed source/policy/prices require revalidation or a new proposal; never silent resizing.

Legacy stop_trigger/stop_limit fields in this inherited schema describe reviewed exit geometry only; no stop is placed.

## 8. Separately approved execution command

Only after valid exact human consent and populated operator_approval.json:

```sh
'''+r['execute_command']+'''
```

## 9. Fill and position recovery verification

'''+''.join('- '+x+'\n' for x in RECOVERY_STEPS)+'''
An authorized attempt writes execution_report.json and WHITELIST_TRADE_PROOF.json from genuine team-account records. Preparation created no fill proof. Verified fill, verified flat account and organizer whitelist confirmation are separate claims. Both SQLite checkpoint checksums/source identities, integrity and clean shutdown were verified, with zero intents/API-action/signed-management rows. No actual-wallet signature or secret was saved.
'''
for old,new in {
 '1.0264':c['checks']['local']['entry_depth']['available_quantity'],
 '0.6932':c['checks']['local']['exit_depth']['available_quantity'],
 '16.7160':r['actual_entry_exposure'], '83580':p.entry_limit, '82045':p.exit_bound,
 '83124':c['checks']['local']['exit_depth']['limit'],
 '0.029812500':r['estimate_round_trip_taker_fee_at_limits'],
 '0.336812500':r['loss_if_fully_closed_at_floor_with_taker_fees']}.items():text=text.replace(old,str(new))
text=text.replace('Fresh read-only preparation finished in13.66 seconds',
 'Fresh read-only preparation finished in'+str(r['elapsed_seconds'])+' seconds')
text=text.replace('The selected proposal authorizes only its exact route',
 'An exact approval would authorize only the selected route')
(out/'report.md').write_text(text)
atomic_json(out/'artifact_sha256.json',{str(x.relative_to(out)):hashlib.sha256(x.read_bytes()).hexdigest() for x in out.rglob('*') if x.is_file() and 'source_before' not in x.parts and x.name!='artifact_sha256.json' and not x.name.endswith(('-wal','-shm'))})
print(json.dumps(dict(proposal_id=p.identity,deadline_ist=r['approval_deadline_ist'],latest_entry_cutoff=cutoff,
 remaining_seconds=round((r['approval_deadline_ms']-time.time_ns()//1000000)/1000,1),verified=True)))
