"""Render final scored preparation from source-matched local/public evidence."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import json,hashlib,time,sqlite3
O=Path(__file__).resolve().parent;R=O.parents[1]
read=lambda p:json.loads((O/p).read_text())
sha=lambda p:hashlib.sha256((O/p).read_bytes()).hexdigest()
r=read('regression_release_final/test_receipt.json');assert r['passed'] and r['totals']['tests']>=2927
pres=read('preservation_receipt.json');assert pres['passed'] and pres['source_hash']==r['source_hash']
a=read('final_preopening_proposal/proposal.json');assert a['status']=='BLOCKED_NOT_AUTHORIZATION' and not a['approval_granted']
d=read('final_preopening_proposal/fresh_discovery/discovery.json');assert d['source_hash']==d['source_hash_after']==r['source_hash']
state=read('final_pas_observer/current.json');obs_path=Path(state['output']);obs=json.loads((obs_path/'terminal_result.json').read_text())
assert obs['threads_stopped'] and obs['signatures_created']==obs['exchange_writes']==0
assert obs['source_hash']==r['source_hash']
original=read('original_order_audit/readback.json');assert original['resolution']=='UNKNOWN_PRESERVED'
assert not (O/'final_preopening_proposal/mandate.json').exists() and not (O/'final_preopening_proposal/acceptance.json').exists()
instant=lambda ms:datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat(timespec='milliseconds')
frames=[json.loads(x) for x in (obs_path/'events.jsonl').read_text().splitlines()]
complete={x['latest_scan_ms'] for x in frames if x.get('latest_scan_ms') and len(x.get('signals',[]))==10 and not x.get('scan_in_progress')}
signals={x['symbol']:x for x in obs.get('signals',[])}
counts={};history_receipts=[]
for directory in [obs_path,O/'final_preopening_proposal/strategy_observation']:
 path=directory/'info_receipts.jsonl'
 if not path.exists():continue
 for line in path.read_text().splitlines():
  x=json.loads(line)
  if x.get('request',{}).get('type')=='candleSnapshot' and isinstance(x.get('response'),list):
   symbol=x['request']['req']['coin'];n=len({bar['t'] for bar in x['response'] if int(bar['t'])+60000<=x['received_ms']})
   counts[symbol]=max(counts.get(symbol,0),n)
   history_receipts.append(dict(symbol=symbol,completed_bars=n,received_ms=x['received_ms']))
markets=[]
for row in d['markets']:
 b=row['book'];bid=D(b['bids'][0]['price']);ask=D(b['asks'][0]['price']);step=D(10)**(-row['spec']['size_decimals'])
 floor=lambda q:q//step*step
 bbo=floor(min(D(b['bids'][0]['quantity']),D(b['asks'][0]['quantity']))*D('.1'))
 five_buy=sum((D(x['quantity']) for x in b['asks'] if D(x['price'])<=ask*D('1.0005')),D(0))
 five_sell=sum((D(x['quantity']) for x in b['bids'] if D(x['price'])>=bid*D('.9995')),D(0))
 five=floor(min(five_buy,five_sell)*D('.1'));sig=signals.get(row['symbol'],{})
 markets.append(dict(symbol=row['symbol'],asset_id=row['spec']['asset_id'],bid=str(bid),ask=str(ask),
  observed_ms=row['observed_ms'],book_ms=b['timestamp_ms'],spread_bps=str((ask-bid)/((ask+bid)/2)*10000),
  ten_percent_bbo_quantity=str(bbo),ten_percent_five_bps_quantity=str(five),
  displayed_book_only_quantity=row['displayed_book_only_quantity'],displayed_book_only_notional=row['displayed_book_only_notional'],
  active_leverage=row['active_asset']['leverage'],account_capacity=row['capacity']['liquidity_only_notional'],
  account_capacity_reasons=row['capacity']['reasons'],funding=row['context'].get('funding'),
  maximum_observed_completed_snapshot_bars=counts.get(row['symbol']),frozen_signal=sig.get('decision','UNKNOWN'),
  signal_reasons=sig.get('reasons',[]),native_protection_qualified=False,authorized_executable_notional='0'))
plan=d['configuration_plan'];summary=dict(verdict='NO_GO_FOR_TRADING',software_release='OFFLINE_VERIFIED',source_hash=r['source_hash'],starting_source=pres['starting_source'],
 totals=r['totals'],xml_sha256=r['xml_sha256'],release_path=str(O/'regression_release_final/test_receipt.json'),
 exact_scored_window=dict(starts_utc='2026-10-19T12:00:00Z',expires_utc='2026-11-06T12:00:00Z',practice_exception_applied=False),
 source_changes=pres['source_changes'],original_preservation=pres['passed'],original_journals_unchanged=pres['all_original_journals_unchanged'],
 native_repairs_preserved=pres['native_repairs'],execution_mode='PAPER',allow_live_orders=False,actual_wallet_signatures=0,exchange_writes=0,
 approval_created=False,trading_launched=False,unified_account_mode=d['account_mode'],
 usdp_balance=d['account']['reported_account_equity']['collateral_balance'],organizer_credit_amount=None,
 organizer_credit_status='NOT_ESTABLISHED_FROM_ORIGINAL_ORGANIZER_RECORD',configuration_plan=plan,
 markets=markets,preopening_proposal_status=a['status'],blockers=a['blockers'],historical_unknown=pres['original_unknown'],
 unknown_disposition='PRESERVED_UNRESOLVED_NO_PAS_ISOLATION_AUTHORIZED',consumed_native_review_required=True,
 original_order_readbacks=original['readbacks'],native_protection_qualified=False,native_subminimum_residual_qualified=False,
 observer=dict(output=str(obs_path),source_hash=obs['source_hash'],status=obs['status'],threads_stopped=obs['threads_stopped'],
  terminal_flat=obs.get('terminal_flat'),terminal_readbacks=obs.get('terminal_readbacks'),complete_scan_count=len(complete),
  complete_scan_times=sorted(complete),actual_errors=obs.get('actual_errors'),rate_report=obs.get('rate_report'),
  session_performance=obs.get('session_performance'),account_age_ms=obs.get('account_age_ms'),fee_age_ms=obs.get('fee_age_ms')),
 history_observations=history_receipts,actual_pas_accounting=d['account'].get('realized'),actual_pas_fills=d['account'].get('fills'),
 historical_par_net='0.050512 TEST USDPR on October 15; not PAS or official competition P&L',
 external_request_sent=False,generated_ms=time.time_ns()//1000000)
for path in [obs_path/'public.sqlite',O/'final_preopening_proposal/fresh_discovery/public.sqlite',O/'original_order_audit/public.sqlite']:
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
files=['regression_release_final/test_receipt.json','regression_release_final/regression.xml','final_preopening_proposal/proposal.json',
 'final_preopening_proposal/fresh_discovery/discovery.json','final_preopening_proposal/fresh_discovery/account_configuration_plan.json',
 'preservation_receipt.json','source_changes.json','stale_receipts.json','official_reference_review.json','original_order_audit/readback.json',
 'additional_pas_simulation.json','pas_reproduced_conflicts.xml','pas_faults_final.xml','opening_controls.xml','OPERATOR_RUNBOOK.md','EXTERNAL_EVIDENCE_REQUEST.md']
summary['artifact_sha256']={p:sha(p) for p in files}
summary['additional_offline_simulation']=read('additional_pas_simulation.json')
(O/'market_capacity.json').write_text(json.dumps(markets,indent=2)+'\n')
rows='\n'.join('| '+ ' | '.join([x['symbol'],str(x['asset_id']),str(round(D(x['spread_bps']),4)),x['ten_percent_bbo_quantity'],x['ten_percent_five_bps_quantity'],x['displayed_book_only_notional'],str(x['active_leverage']['value'])+'x CROSS',str(x['maximum_observed_completed_snapshot_bars']),x['frozen_signal'],x['authorized_executable_notional']])+' |' for x in markets)
blocks='\n'.join('- `'+b+'`' for b in a['blockers'])
report=f'''# Anchorium scored-phase release preparation — October 18, 2026

**Final verdict: NO-GO FOR TRADING.** Software-controlled repairs and the final full release are verified offline. Preparation did not load an actual-wallet key, sign, submit/cancel an order, change leverage/account mode, transfer collateral, create an acceptance or launch trading. PAPER/false and all shared safety restrictions remain.

## 1. PAS readiness and release consistency

Started from the exact requested source `{pres['starting_source']}` and its matching 2,889-test receipt/XML. PAS 2,850-test receipts were stale after the preceding par repair. This task made demonstrated production changes, so a new release was necessary: **{r['totals']['tests']} passed, 0 failures/errors/skips**, source before/after **`{r['source_hash']}`**, XML SHA-256 **`{r['xml_sha256']}`**. See [final receipt](regression_release_final/test_receipt.json), [XML](regression_release_final/regression.xml), [stale-receipt audit](stale_receipts.json) and [source changes](source_changes.json).

Strategy-freeze and production-policy/phase-0 checks passed before and after full regression. Frozen signal/state formulas, 300-bar warmup, ATR 0.40%, 15-bps scanner spread, Top-3, capital and mandate limits were not changed. All 53 original database logical contents and integrity checks match the baseline. Original proof files and the preceding native-repair modules remain byte-identical. Existing dirty PAS work was retained. See [preservation receipt](preservation_receipt.json).

The initial partial regression was explicitly interrupted, marked uncertified, after genuine public observation exposed the rate-deadline mismatch. Only `regression_release_final` certifies the final source. Historical receipts were not overwritten.

## 2. Current balance and configuration

Fresh public discovery completed at **{instant(d['finished_ms'])}**, selecting canonical `pas`, DEX index `{d['dex_index']}`, collateral token `{d['collateral_token']}` / USDP and exactly ten registered, non-delisted markets. These identities come from runtime discovery, not a native/par fallback. `exchangeStatus`/`perpDexStatus` are separately reported and do not prove an official opening or team eligibility.

Account mode: **{d['account_mode']}**. Unified USDP balance: **{summary['usdp_balance']}**. Exact organizer credit/reset amount: **UNKNOWN / not yet established**. No issuer/whitelist/reset claim is inferred from a balance. USDPR is not USDP. Current PAS leverage remains 10x/20x, so **0 of 10 markets are verified 1x CROSS**. No configuration change was submitted.

The fresh unsigned [configuration plan](final_preopening_proposal/fresh_discovery/account_configuration_plan.json) identifies all ten exact runtime asset IDs, observed prior settings and requested 1x CROSS actions. Plan hash: `{plan['plan_hash']}`. It requires funding, prior-state review, fresh account/agent/identity/sole-host/nonce/clock/rate checks and separate exact configuration-only approval. It grants no permit or transfer authority. The old par approval cannot authorize PAS changes.

## 3. Market-by-market capacity and frozen signals

The table uses fresh public books at each recorded market timestamp. Ten-percent BBO is lot-rounded on both sides; five-bps depth is also capped at ten percent on both sides. Displayed notional is only a book upper bound. It excludes funding, 1x readiness, risk, native/residual protection and authorization. **Actual authorized capacity is zero everywhere.** No notional target is enlarged to meet a minimum.

| Market | Runtime asset | Spread bps | 10% BBO qty | 10% five-bps qty | Book-only USDP notional | Current leverage | Max observed completed snapshot bars | Frozen decision | Authorized notional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{rows}

Detailed prices, ages, fee/funding contexts, account limits, signal reasons and raw-history counts are in [market_capacity.json](market_capacity.json) and the original public receipts. Completed-bar counts are maximum deduplicated completed bars actually returned by observed candle snapshots, not invented candles or a warmup waiver. Strategy decisions remain NO_TRADE/UNKNOWN where canonical data is insufficient or stale. No par history was substituted for PAS.

The seven-minute continuous observer completed **{len(complete)} distinct full ten-market scans**, then stopped with threads stopped `{obs['threads_stopped']}` and terminal flat `{obs.get('terminal_flat')}`. Its actual terminal readbacks remain under `{str(obs_path.relative_to(O))}`. Two authoritative flat/zero-order readbacks are required; cached status alone is not flatness evidence. The observed stream/account/recovery evidence, public request counts, bounded wait durations and errors are preserved in [final_summary.json](final_summary.json). Supporting account scans occur every 300 seconds; cached ages are explicit and never waive fresh signing checks. The final unsigned proposal also collected its own bounded strategy observation.

Reported `userCrossRate` is `{d['user_fees']['userCrossRate']}`. The [official guide](https://perpetual-alpha26.github.io/docs/) describes PAS positive base rates doubled by the venue. Existing software conservatively retains the stricter six-times bound `{d['fee_rate_bound']}`; actual USDP fill fees would govern realized P&L. This task changed no fee/risk limit. Funding is read per market, not assumed zero. The read-only process records real errors; a rate-controlled fallback label is not HTTP429 evidence.

## 4. Remaining exchange and organizer evidence

Actual proposal blockers:

{blocks}

In addition to genuine USDP funding and original organizer eligibility/credit provenance, a fresh 1x configuration approval, complete canonical warmup, actual PAS native/residual qualification and a new exact session approval remain required. The published schedule already establishes the scored interval; no October 17–18 special practice exception is imposed on the open scored phase. The original-evidence request is [saved separately](EXTERNAL_EVIDENCE_REQUEST.md) and was not sent.

## 5. Historical UNKNOWN disposition

CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce `1792217834069`, mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea`, source `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f` remains **UNKNOWN**. Original row, nonce and earlier exact certificate remain unchanged. The consumed native attempt remains `do_not_restart`; it was not relaunched or reset.

The fresh [original-order audit](original_order_audit/readback.json) reports actual public responses tied to the original CLOID. Current empty accounts/orders or `unknownOid` do not prove original non-transmission. The earlier certificate concerns a different CLOID and is not reused. Reconstructed stale-readiness timing is not an original causal rejection. No admissible new terminal/causal record was found in the retained local records and this task's public readbacks; no new certificate was manufactured.

No safe independently authorized PAS isolation was established. The same team/API/nonce domain retains shared uncertainty even though the DEX and collateral differ. The existing shared-account barrier continues to reject PAS signing. Any isolation exception needs an independently justified, explicitly authorized policy covering account, signer, nonce, late-action and accounting invariants; this preparation grants none.

## 6. PAS native protection and execution repairs

Software readiness is **OFFLINE VERIFIED FOR TESTED CASES**, not genuine venue qualification. The existing noninteractive lifecycle and official offline SDK stack were exercised with synthetic PAS accounts/USDP fills and ephemeral keys, with sockets/HTTP disabled. Real metadata was never changed. Whole-unit synthetic lots enable lifecycle fault injection; they do not establish actual PAS subminimum behavior.

Demonstrated repairs:

- Exact calendar: shared scored boundaries now use October 19 12:00 UTC and November 6 12:00 UTC. The prior shared IST-midnight window and PAS final-day midnight cutoff were outdated. Start-minus-one, start, end-minus-one, end, invalid intervals and the finite session cap are tested.
- PAS startup: account verification previously requested `par:BTC`, causing `STARTUP_RECOVERY_FAILED:VenueMismatch` for PAS. It now uses the verified selected venue prefix. No strategy callback changed.
- Fixed native stop readback: dynamic position-TP/SL records can no longer be accepted as the approved independent fixed-size route. Order grouping stays `na`.
- Conflicting closing fill: a reported fill outside its fixed Stop Limit is now rejected as a protection evidence conflict. Unresolved closing/protection evidence prevents the lifecycle from declaring a completed flat round trip. Two failing PAS reproductions are retained in [pas_reproduced_conflicts.xml](pas_reproduced_conflicts.xml).
- Unsigned configuration proposal: fresh discovery now writes the ten-market source-bound 1x CROSS plan, explicitly separate from credit provenance, approval and execution.
- Public preflight/reporting: scored preparation observes completed-bar signals even without native proof and bounds the scan to 180 seconds. PAS ordinary-minimum admissibility is separately labeled from genuine native qualification.
- Bounded public reads: a 65-second budget wait was truncated by a 45-second read deadline. Public observer/discovery deadlines now permit 75 seconds while rate limits/reserves remain unchanged. A deterministic rolling-window test and fresh observation validate the wait without expanding the budget. Signing freshness limits were not relaxed.

The 19 PAS fault cases cover frozen-signal entry/protection/close/accounting; rejected/uncertain entries; partial entry/exit behavior; rejected/uncertain/wrong-size stops; partial/full native fills; triggered-unfilled gaps; subminimum partial rejection; disconnects; dynamic-stop and fill-price conflicts; expiry, loss, stale book and disconnected entry barriers. Broader focused checks passed 303 tests before the final additional bounded-wait case. Full final-source regression supersedes all supporting counts. Supplemental offline replay also verified an invalid fractional-lot partial entry remaining in recovery and two sequential frozen-signal cycles without per-trade prompts; its synthetic fills and P&L are retained in [additional_pas_simulation.json](additional_pas_simulation.json), with actual P&L null and venue qualification false.

Actual PAS native acceptance, natural trigger, real associated closing fills and native subminimum residual/full-position routes remain **UNQUALIFIED**. Historical par IOC records do not qualify them. No actual PAS fill, fee or funding was generated. Current PAS reported accounting remains separate from the historical October 15 par net `+0.050512 TEST USDPR`. With zero initial USDP equity, a return percentage is undefined; no official score or expected profit is claimed.

## 7–9. Terminal command, approval procedure and conditional launch

[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) contains the exact read-only terminal/discovery commands, required evidence and configuration review, fresh scored proposal command using this final receipt, interactive exact-hash approval procedure and conditional authorized launch command. Those commands use explicit PAS_NATIVE_ONLY and preserve PAPER/false.

Routine trades inside one valid mandate use SCAN → SIGNAL → VALIDATE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE without individual prompts. Only the genuine initial exact-mandate approval is interactive. Existing LONG-only scope, one global position, two entry attempts, twelve signed actions, per-cycle close/protection limits, cancellation cap, bankroll/allocation/risk/loss bounds and expiry remain unchanged. Restart cannot restore/renew authority; duplicate-worker, stale-data, disconnect, stop, loss and expiry guards remain. The public duplicate-owner attempt was rejected with `PAPER_OWNER_ALREADY_RUNNING`.

## 10. Final GO / NO-GO

**NO-GO for actual scored trading.** A passing source release is not trading authority. The next independently verifiable conditions are actual USDP funding/organizer provenance, separate exact PAS 1x configuration approval/readbacks, admissible UNKNOWN/invocation recovery or an independently authorized isolation policy, sufficient canonical history, actual PAS native/residual qualification and a fresh finite exact human-approved mandate at/after opening.

The [official schedule](https://perpetual-alpha26.github.io/schedule) is October 19 12:00 UTC through November 6 12:00 UTC (17:30 IST at both ends). Each session remains separately bounded; there is no automatic renewal, midnight counter reset, next-day promotion or SHORT activation.

The standalone observer can run without an open Codex app, but still depends on this Mac, Python process, power, internet and exchange connectivity. Killing its terminal can interrupt supervision. Native Stop Limit gaps can leave exposure; budgets are not guaranteed loss caps and no profit is guaranteed. All actual residual-state claims require current authoritative evidence.
'''
(O/'FINAL_RELEASE_REPORT.md').write_text(report)
summary['artifact_sha256']['FINAL_RELEASE_REPORT.md']=sha('FINAL_RELEASE_REPORT.md')
summary['artifact_sha256']['market_capacity.json']=sha('market_capacity.json')
for name in ['final_summary.json','release_summary.json']:(O/name).write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(verdict=summary['verdict'],source=r['source_hash'],tests=r['totals'],full_scans=len(complete),balance=summary['usdp_balance'])))
