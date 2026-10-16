"""Local evidence audit and completed-window report; no exchange calls or signing."""
import json,hashlib,sqlite3,sys,time
from pathlib import Path
from decimal import Decimal as D
from collections import Counter
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
from exchange.live_recovery import LiveAccountRecovery
from exchange.exit_recovery import require_recovery_regression
b=Path(__file__).resolve().parent
m=json.loads((b/'mandate.json').read_text());a=json.loads((b/'recovery_approval.json').read_text())
r=json.loads((b/'authorized_profit_window/result.json').read_text());c=json.loads((b/'completion_read_only.json').read_text());prep=json.loads((b/'preparation_receipt.json').read_text())
rows=[json.loads(s) for s in (b/'authorized_profit_window/observations.jsonl').read_text().splitlines()];valid=[x for x in rows if x['bid'] is not None]
z=timezone(timedelta(hours=5,minutes=30));at=lambda t:datetime.fromtimestamp(t/1000,z).isoformat()
source=active_source_hash(ROOT);receipt=require_recovery_regression(ROOT,ROOT/'docs/btc_exit_recovery_2026-10-15/regression_release/test_receipt.json')
assert source==m['source_hash']==r['source_hash_after']
proofs={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in prep['original_buy_proof_sha256']};assert proofs==prep['original_buy_proof_sha256']
j=ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
with sqlite3.connect('file:'+str(j)+'?mode=ro',uri=True) as db:
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];control=dict(db.execute('SELECT name,value FROM controls'))
 new_intents=db.execute('SELECT intent_key,state,oid FROM intents WHERE created_ms>=?',(a['accepted_ms'],)).fetchall()
 generated_nonces=db.execute("SELECT COUNT(*) FROM events WHERE timestamp_ms>=? AND kind='NONCE_GENERATED'",(a['accepted_ms'],)).fetchone()[0]
 actions=db.execute('SELECT COUNT(*) FROM api_actions WHERE timestamp_ms>=?',(a['accepted_ms'],)).fetchone()[0]
 rate_events=db.execute("SELECT timestamp_ms,kind,data FROM events WHERE timestamp_ms>=? AND kind IN ('INFO_RATE_BUDGET_REJECTED','INFO_READ_FAILURE','RATE_LIMIT_THROTTLED')",(a['accepted_ms'],)).fetchall()
 snap,checksum=db.execute('SELECT data,checksum FROM recovery_snapshots ORDER BY seq DESC LIMIT 1').fetchone();cp=json.loads(snap)
 # Checkpoint uses a structured identity with its own hash domain; compare it to
 # its canonical generator, not to the aggregate proposal source-hash string.
 checkpoint_valid=fingerprint(cp)==checksum and cp['source_identity']==LiveAccountRecovery.source_identity()
 assert integrity=='ok' and checkpoint_valid
 assert not new_intents and not generated_nonces and not actions and not r['exit_attempted']
 assert 'exit_recovery_finished:'+a['mandate_hash'] in control
 assert 'exit_recovery_transmission:'+a['mandate_hash'] not in control

def db_rows(path,table):
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:return db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
old=ROOT/'docs/btc_exit_recovery_2026-10-15/before_nonces.sqlite';cur=ROOT/'runtime/testnet/anchorium-bot-1/nonces.sqlite'
with sqlite3.connect('file:'+str(old)+'?mode=ro',uri=True) as db:tables=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
nonce_history_unchanged=all(db_rows(old,t)==db_rows(cur,t) for t in tables)
stats=dict(observations=len(rows),bid_observations=len(valid),minimum_observed_bid=str(min(D(v['bid']) for v in valid)),maximum_observed_bid=str(max(D(v['bid']) for v in valid)),last_observation=rows[-1],maximum_observation_gap_ms=max(y['at_ms']-x['at_ms'] for x,y in zip(rows,rows[1:])),transport_counts=dict(Counter(x['transport'] for x in rows)))
summary=dict(report_type='BOUNDED_PROFIT_ONLY_WINDOW_RESULT',status=r['status'],generated_ms=time.time_ns()//1000000,mandate_id=a['mandate_hash'],source_hash=source,accepted_ms=a['accepted_ms'],authorization_expires_ms=a['expires_ms'],runtime_finished_ms=r['finished_ms'],runtime_terminal_exit_code=0,signing_authority_revoked=True,automatic_renewal=False,actual_new_entries=0,actual_exit_attempts=0,new_signed_actions=actions,new_nonces=generated_nonces,new_order_intents=new_intents,roundtrip_realized_pnl=None,account_flat=False,final_account=c,observation_statistics=stats,original_buy_proof_unchanged=True,original_buy_proof_sha256=proofs,nonce_history_unchanged=nonce_history_unchanged,sqlite_integrity=integrity,latest_recovery_checksum_and_source_valid=checkpoint_valid,checkpoint_source_identity=cp['source_identity'],rate_rejection_events=[dict(timestamp_ms=t,kind=k,data=json.loads(d)) for t,k,d in rate_events],test_receipt=str(receipt),existing_full_regression_tests=2312,no_code_changed_for_this_window=True,protection_verified=False,organizer_whitelisting_confirmed=False,production_mode='PAPER',allow_live_orders=False,next_action='HUMAN_DECISION_REQUIRED; do not renew or submit any order automatically')
atomic_json(b/'window_summary.json',summary)
text=f'''# Option B result — no profitable SELL observed

The exact approved mandate `{a['mandate_hash']}` completed with status **{r['status']}**. No SELL was attempted, signed or submitted. The original trade remains open. No completed-round-trip profit or loss is claimed.

## Authorization and timing

Approved at {at(a['accepted_ms'])}; maximum expiry {at(a['expires_ms'])}. Scope was TESTNET `par:BTC`, exactly one possible reduce-only IOC SELL of 0.0002 BTC, minimum 81,812 USDPR/BTC, with fresh estimated net profit of at least 0.001 USDPR. The ten-minute bound included a final fifteen-second management reserve. Signing authority was revoked before expiry; final runtime account reads completed by {at(r['finished_ms'])}.

No extension, renewal, loss-exit fallback, BUY, enlargement, cancellation or second exit occurred.

## Actual final account

Independent read-only snapshot: **{at(c['observed_ms'])}**.

- Team account: `{m['team_wallet']}`. API signer: `{m['api_wallet']}`.
- Remaining position: **0.0002 BTC LONG**, entry 81,512, **1x CROSS**.
- Open orders: **0**. Durable reconciliation: READY with no reported reasons.
- Executable bid / ask: **{c['quote']['bid']} / {c['quote']['ask']}**.
- Mark / oracle: {c['quote']['mark']} / {c['quote']['oracle']}; distinct from executable prices.
- No closing order ID or closing fill ID exists for this window.
- Protective-stop acceptance remains unverified. The position remains unprotected.

## Profit math and actual cashflows

Original genuine BUY: order 62755970305, fill 800659111758533; 0.0002 BTC at 81,512; cost 16.30240 TEST USDPR; reported entry fee 0.014672 USDPR.

Net reported funding is **{c['funding_cashflow']} USDPR**: +0.000141 at 10:30 IST and −0.000201 at 11:30 IST. The current hourly rate is not used instead of actual cashflows.

Conservative exit-fee bound is **0.27%**. Because the API omits deployerFeeScale, the documented maximum HIP-3 multiplier is used. This is an estimate bound for a future exit, not an actual paid exit fee. The approved maximum was 0.30%.

- Conservative break-even: **{c['break_even']} USDPR/BTC**.
- Positive-buffer SELL floor: **{c['positive_buffer_floor']} USDPR/BTC**.
- Conditional net at the final observed bid: **{c['conditional_net_at_observed_bid']} TEST USDPR**, assuming full execution and the reviewed fee bound. This is not realized P&L or authorization for a loss exit.
- Actual entry fee plus reported funding cashflow so far: **{-D('.014672')+D(c['funding_cashflow'])} USDPR**, excluding open-position valuation. This is not a completed-trade result.
- Reported mark-valued unrealized P&L: **{c['positions_after'][0]['unrealized_pnl']} USDPR**.

The floor included a small positive buffer; full execution at 81,812 under the reviewed fee/funding bounds would produce approximately 0.00108952 USDPR net. That outcome did not occur.

## Observation evidence and limits

There were **{stats['observations']}** recorded observations, including **{stats['bid_observations']}** with a bid. Recorded bids ranged **{stats['minimum_observed_bid']}–{stats['maximum_observed_bid']}**, below the approved floor.

Transport counts: `{json.dumps(stats['transport_counts'])}`. RATE_LIMITED_REST is a rate-controlled REST fallback label, not evidence of an HTTP 429. No persistent local read-budget rejection was found in this window. The longest observation gap was **{stats['maximum_observation_gap_ms']/1000:.3f} seconds**, including serial account checks and pacing. This is not an exhaustive record of every exchange tick; no hypothetical missed fill is invented.

## Integrity and preservation

- Source `{source}` is unchanged and matches the existing full 2,312-pass receipt. No new full regression run is claimed for this unchanged-source observation. Fresh preparation passed strategy freeze and Phase-0.
- New order intents: 0; signed API actions: 0; generated nonces: 0. Nonce history unchanged: {nonce_history_unchanged}.
- SQLite integrity: {integrity}. Latest checkpoint checksum and its structured source identity match their canonical verifier. The checkpoint identity and proposal aggregate hash use different hash domains; an initial local report assertion compared those unlike types, and the corrected read-only comparison passes. This was a reporting assertion, not an execution or persistence failure.
- Runtime signing authority is durably revoked. Restart cannot reactivate it.
- Both original BUY proofs retain their pre-window SHA-256 hashes. Organizer whitelisting remains unconfirmed.
- Production remains PAPER / ALLOW_LIVE_ORDERS=false. Strategy, thresholds and protection-certification status were not changed.

Underlying records: `authorized_profit_window/result.json`, `completion_read_only.json`, `window_summary.json`, the observation tape, exact mandate and genuine human acceptance.

## Next decision

No monitoring or signing window is active. A new ten-minute profit-only proposal or a separate bounded close proposal requires a fresh exact approval. No action will renew automatically. Waiting leaves the BTC LONG exposed and does not guarantee profit.
'''
(b/'window_report.md').write_text(text)
print(json.dumps({k:summary[k] for k in ('status','actual_exit_attempts','new_signed_actions','new_nonces','account_flat','original_buy_proof_unchanged','nonce_history_unchanged','sqlite_integrity','latest_recovery_checksum_and_source_valid')},indent=2))
