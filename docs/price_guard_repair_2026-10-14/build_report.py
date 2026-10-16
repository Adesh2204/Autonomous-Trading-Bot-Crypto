"""Read-only engineering report; source-bound checks precede fresh proposal."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.emergency_qualification import (BOUNDED_POLICY,BOUNDED_PRICE,EmergencyProposal,
    require_emergency_regression,policy_hash)
from exchange.execution_journal import fingerprint
from exchange.qualification_watcher import durable_readback
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration

require_paper_migration();freeze=verify_strategy_freeze()
receipt=out/'regression_release/test_receipt.json';require_emergency_regression(ROOT,receipt)
tests=json.loads(receipt.read_text());assert tests['totals']==dict(tests=2115,failures=0,errors=0,skipped=0)
before=json.loads((out/'source_before.json').read_text());changes=json.loads((out/'source_changes.json').read_text())
assert tests['source_hash']==tests['source_hash_after']==active_source_hash(ROOT)
assert all(hashlib.sha256((ROOT/c['path']).read_bytes()).hexdigest()==c['after_sha256'] for c in changes)
protected=['algo-trading-bot/signal_brain.py','docs/strategy_freeze.json','configs/reliability_policy.json']
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==before['files'][p] for p in protected)
with sqlite3.connect((ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite').as_uri()+'?mode=ro',uri=True) as db:
    action_counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('intents','api_actions','signed_management')}
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
assert integrity=='ok' and not any(action_counts.values())
result=dict(status='ENGINEERING_COMPLETE_AWAITING_FRESH_BOUNDED_PROPOSAL',source_hash=active_source_hash(ROOT),
    previous_source_hash=before['source_hash'],regression=tests['totals'],baseline_tests=2046,new_tests=69,
    source_bound_full_regression=True,strategy_freeze=freeze,protected_files_unchanged=protected,
    changes=changes,new_policy=BOUNDED_POLICY,new_policy_hash=fingerprint(BOUNDED_POLICY),
    actual_wallet_signatures=0,exchange_submissions=0,qualification_journal_actions=action_counts,
    code_ready=True,protection_verified=False,controlled_protected_execution_ready=False,
    unrestricted_trading_enabled=False,actual_fill_verified=False,organizer_whitelist_confirmed=False,
    past_failed_quote_available=False)
proposal_text='No fresh order has been authorized. Preparation is the next permitted step.'
if len(sys.argv)>1:
    folder=Path(sys.argv[1]);folder=folder if folder.is_absolute() else ROOT/folder
    r=json.loads((folder/'readiness.json').read_text());p=EmergencyProposal(**json.loads((folder/'proposal.json').read_text())).require()
    assert r['status']=='AWAITING_EXACT_HUMAN_RISK_APPROVAL' and p.price_authorization_mode==BOUNDED_PRICE
    assert r['source_hash']==r['source_hash_after']==p.source_hash==active_source_hash(ROOT)
    assert r['proposal_id']==p.identity and r['qualification_policy_hash']==policy_hash(p)
    candidate=r['selected_candidate'];assert candidate['eligible'] and not candidate['positions'] and not candidate['orders']
    assert candidate['account_reconciliation']['ready']
    assert candidate['signer']['identity']['status']=='MATCH' and candidate['signer']['local_lease']['status']=='HEALTHY_LOCAL'
    assert all(x['active']['leverage']==dict(type='cross',value=1) for x in r['capacity_inventory'].values())
    approval=json.loads((folder/'approval_REQUIRED_UNFILLED.json').read_text())
    assert all(approval[k] is False for k in r['required_acknowledgements'])
    assert approval['approved_ms'] is None and approval['expires_ms'] is None and approval['operator_approval']==''
    assert not (folder/'operator_approval.json').exists()
    cleanup=durable_readback(folder/'read_only.sqlite',r['durable_cleanup']['source_identity'],clean=True)
    assert cleanup['snapshots_verified']==2 and not any(cleanup['actions'].values())
    result.update(status='AWAITING_EXACT_NEW_BOUNDED_PRICE_APPROVAL',proposal_id=p.identity,proposal=r['proposal'],
        approval_deadline_ms=r['approval_deadline_ms'],entry_deadline_ms=r['approval_deadline_ms']-90000,
        isolated_experimental_proposal_ready=True,approval_supplied=False,account_observed_ms=candidate['account_ms'],
        account_flat_observed=True,read_only_cleanup=cleanup)
    deadline=datetime.fromtimestamp((r['approval_deadline_ms']-90000)/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
    proposal_text=f'''Proposal `{p.identity}` is a read-only, source-bound Hyperliquid TESTNET `par:BTC` LONG envelope. Quantity is fixed at {p.quantity} BTC; maximum BUY price {p.max_buy_price}; selected opening notional ceiling {p.entry_notional_ceiling} TEST USDPR, inside the unchanged 1,000 outer cap. Exit floor {p.exit_bound}; one entry, up to two exact reduce-only IOC exits, one cancellation and four signed actions. Approval expires {r['approval_deadline_ist']}; entry needs at least 90 seconds remaining, making its latest transmission {deadline}. Final checks can still block it.\n\nThe account observation confirmed funded/unified mode, approved API signer, all ten 1x CROSS settings, zero positions/orders, healthy reconciliation/clock/local signer ownership, and two clean read-only checkpoints. Sole-host status includes the user's prior/current assertion; the local lease cannot independently inspect other machines. There is no signed action or fill from preparation.\n\nNo stop is verified or submitted. The new bounded-price acknowledgment is required in addition to the existing qualification risk acknowledgments. Codex must populate the approval file only from a genuine timely human response naming/accepting this exact envelope. Never backdate, reuse an expired approval, extend the cap or invent a fill.'''
    atomic_json(folder/'proposal_verification.json',result)
files='\n'.join('- ['+c['path']+'](<'+str(ROOT/c['path'])+'>)' for c in changes)
report=f'''# Team Anchorium — P0 price-guard repair

The repair is implemented and verified offline. **2,115 tests passed; zero failures, errors or skips. No actual order has been submitted by this repair.** The frozen strategy and PAPER/false locks remain intact. Protected execution is still unverified.

## Exact root cause and historical limit

The old approval fixed the IOC limit at the reviewed ask plus 20 bps. The later `check_entry` comparison rejected that fixed value when it exceeded `normalize_price(fresh_ask × 1.002, BUY)`, or could no longer reach the fresh ask. That comparison shared one error code with minimum and notional conditions. A small ask fall could therefore cause a preventable stale-price rejection. Old authorization prohibited changing the price, so repricing it would have violated approval.

For the previous 83,610 limit, a deterministic fresh ask of 83,442 gives a normalized 20-bps maximum of 83,608. The old price fails that comparison. A normalized fresh ask-plus-10-bps price is 83,525, which fits the unchanged 83,610 ceiling and current tolerance. This is a mathematical/offline reproduction, not a recovered historical market observation. The previous failed quote was not persisted, so its exact ask and branch remain unknowable from saved evidence.

## Persistent diagnostics

`P0_ENTRY_PRICE_GUARD` journal events now record bid, ask, mark, oracle, reviewed limit/cap, actual selected limit, current 20-bps ceiling, quantity, minimum/outer/selected notionals, proposal/book/mark/account/evaluation timestamps, exact Boolean price predicates and the returned guard result. They include public proposal/source hashes under supported public-hash fields. No private key, signer object, signature or signed payload is logged.

The existing launcher exports these records to `price_guard_diagnostics.json`, including a build failure before the runtime exists. A failed build also gets a plain execution report. Missing historical values are not reconstructed or invented.

## Corrected authorization

V1 (`FIXED_LIMIT_V1`) retains its original JSON compatibility, proposal identity/hash and exact-limit behavior. Optional new envelope fields must remain empty for fixed proposals. Expired/source-invalid legacy approvals remain blocked.

V2 (`BOUNDED_FRESH_IOC_V2`, policy `ANCHORIUM_P0_BOUNDED_IOC_V2`) applies only to the isolated BTC BUY IOC test. Its proposal commits to an exact quantity, equal quantity ceiling, a maximum BUY price and exact selected opening notional ceiling. The reviewed maximum remains the existing ask-plus-20-bps limit; it is not automatically widened. The policy hash and explicit bounded-price approval acknowledgment differ from V1.

After approval, the executor derives `min(fresh ask × 1.001, approved maximum BUY price, approved notional ceiling / fixed quantity)`, rounded down using runtime exchange precision. The 10-bps buffer leaves room inside the still-enforced 20-bps live tolerance; it does not guarantee a fill. The selected order must reach the current ask, fit every approved cap, satisfy the ordinary minimum, match actual asset/lot metadata and remain valid at signing. It never increases or rounds away the approved quantity.

The request is selected from the existing mandatory fresh validation context before the one durable entry is reserved. The journal stores the actual selected price. The central signing permit binds its callback to that actual request; all final signing/transport checks still validate the immutable signed wire against new public prices. It cannot be edited after reservation/signing. If the market moves outside its remaining live tolerance, the order is blocked. A durable duplicate returns the original stored price/outcome rather than selecting a second order.

## Limits retained

1x CROSS; ordinary $10 minimum; outer 1,000 TEST USDPR cap; exact smaller selected price/quantity/notional bounds; one global exposure; one entry; two bounded reduce-only IOC exit attempts; one original-entry cancellation; maximum four signed actions; five-minute proposal/approval expiry and 90-second entry recovery reserve. Runtime precision, source/regression identity, nonce/account leases, API budgets, account reconciliation, fresh book/mark/oracle checks, 50-bps qualification spread, 50% genuine L2 participation, 50/100/150-bps reference checks, exact one-lot BTC residual scope and approved exit floor remain mandatory.

Production VWAP/EMA/ATR/state logic, 300 completed bars, 0.40% volatility floor, 15-bps production spread and Top-3 are unchanged. No native minimum exemption, leverage/account administration, recurring task or unrestricted trading was added.

## Latency and recovery

Source/receipt checks, market observation, all-ten leverage inventory, signer derivation/lease review and expensive read-only preparation occur before approval. V2 removes one redundant early flat-position/open-order pair: the mandatory provider bundle immediately reads/reconciles those same fields, and both central and signing-boundary flat checks remain. It selects its price late from that fresh context. No account, history, nonce, market, rate or source safety check is disabled to improve speed.

Small native protective-stop acceptance and lifecycle remain UNVERIFIED. No stop is submitted. Partial fills are reconciled from actual team fills and current positions. Supported exact residual closes retain their price floor and two-attempt limit; they can still be rejected or lack liquidity. A rejected or uncertain exit preserves exposure and requires operator escalation. An uncertain entry is never blindly resubmitted. Restart does not resume an entry automatically.

## Tests and modifications

{files}

Full baseline 2,046 plus 69 new tests = **2,115 passed**. Coverage includes asks moving up/down, maximum-price clamping, out-of-envelope rejection, spread/depth changes, independent mark/order notional limits, quantity caps, precision/mapping, minimum-order failure without enlargement, approval/time/source policy expiry, stale quotes, actual central SDK wire validation, zero/partial/full fills, rejection/uncertainty, partial residual closure, rejected exits, duplicate prevention, restart, complete secret-free diagnostics, explicit V2 approval and no-fill artifact handling. Offline SDK tests use ephemeral fixture keys and forbid exchange HTTP; they do not certify a real fill or stop.

Development failures are preserved separately. They exposed the need to pass the actual selected request through the central permit's own callback, plus fixture formatting/zero-spread expectations. Final focused validation passed 323 tests, and the final new set passed 69. Full regression is the authoritative final receipt, with matching before/after source hashes and successful Phase-0 and strategy-freeze checks before and after.

Full active source: `{active_source_hash(ROOT)}`. Previous source: `{before['source_hash']}`. Brain remains `{before['files']['algo-trading-bot/signal_brain.py']}`. The pre-existing failed-build qualification journal was backed up without reset, and its original actions remain zero. Earlier evidence, nonce records and expired approvals were preserved.

## Proposal and remaining decision

{proposal_text}

`ACTUAL_PROTECTION_READY=FALSE`, normal protected `CONTROLLED_EXECUTION_READY=FALSE`, `ACTUAL_FILL_VERIFIED=FALSE`, organizer whitelist confirmation unverified. Readiness of this explicitly accepted no-stop experiment is separate from production/protected readiness. After genuine exact authorization, Codex may run only the bounded workflow, verify actual team-wallet fills/fees/positions and write `WHITELIST_TRADE_PROOF.json` only for a genuinely verified fill. Zero/rejected fills produce `NO_FILL_VERIFICATION.json`. No automatic repeat is authorized.
'''
(out/'report.md').write_text(report);atomic_json(out/'final_summary.json',result)
atomic_json(out/'artifact_sha256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in out.rglob('*') if p.is_file() and 'source_before' not in p.parts and p.name!='artifact_sha256.json'
    and not p.name.endswith(('-wal','-shm'))})
print(json.dumps(dict(status=result['status'],tests=tests['totals'],source_hash=active_source_hash(ROOT),proposal_id=result.get('proposal_id'))))
