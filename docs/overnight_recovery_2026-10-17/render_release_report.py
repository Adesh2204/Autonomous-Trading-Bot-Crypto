"""Render final engineering report only after the final source-bound suite passes."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
import hashlib,json,sqlite3,sys,time,xml.etree.ElementTree as ET

P=Path(__file__).resolve().parent;ROOT=P.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.terminal_evidence import local_execution_state
from exchange.long_session import require_release
read=lambda p:json.loads(p.read_text())
stamp=lambda ms:datetime.fromtimestamp(ms/1000,ZoneInfo('Asia/Kolkata')).isoformat()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
receipt=P/'regression_release/test_receipt.json';release=read(receipt)
source=active_source_hash(ROOT)
assert release['passed'] and source==release['source_hash']==release['source_hash_after']
require_release(ROOT,receipt,source,sha(receipt))
pres=read(P/'preservation_receipt.json');assert pres['passed']
boundary_xml=P/'requested_boundary_final.xml'
boundary_suites=ET.parse(boundary_xml).getroot().findall('testsuite')
boundary_totals={k:sum(int(s.get(k,0)) for s in boundary_suites) for k in ('tests','failures','errors','skipped')}
assert boundary_totals==dict(tests=9,failures=0,errors=0,skipped=0)
boundary_receipt=dict(source_hash=source,totals=boundary_totals,xml_sha256=sha(boundary_xml),passed=True)
(P/'requested_boundary_receipt.json').write_text(json.dumps(boundary_receipt,indent=2)+'\n')
baseline=read(P/'baseline.json');changes=[]
paths=list((ROOT/'scripts').glob('*.py'))+[p for p in (ROOT/'algo-trading-bot').rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)]
for p in sorted(paths):
    name=str(p.relative_to(ROOT));digest=sha(p)
    if baseline['files'].get(name)!=digest:changes.append(dict(path=name,before=baseline['files'].get(name),after=digest))
reasons={
 'competition_windows.py':'Reject actual runtime construction outside the published finite windows; no implicit Oct17–18 permission.',
 'execution_journal.py':'Atomically persist append-only intent audit events alongside durable reservations/state changes.',
 'hyperliquid_execution.py':'Preserve sanitized causal exceptions and link genuinely ready recovery to new terminal audit records.',
 'intent_audit.py':'Checksum-chain append-only evidence; never backfill or resolve historical UNKNOWN.',
 'long_session.py':'Apply the published-window check before release/key/actual runtime construction.',
 'sdk_transport.py':'Record signed/dispatch/HTTP-response boundaries without secrets; retain the separate fixed-leverage transport.',
 'terminal_app.py':'Visible local UNKNOWN and session accounting, refreshed dashboard command, read-only restart provenance, stronger proposal blockers.',
 'terminal_evidence.py':'Unsigned exact-lot two-sided capacity, stressed conditional costs and observed-session accounting with defined bases.',
 'terminal_observer.py':'Refresh capacity clocks after candle recovery; publish independent capacity, counts and actual-account diagnostics.',
 'test_overnight_terminal_evidence.py':'Adversarial/property-style capacity, accounting, immutable-audit, stale-dashboard and window tests.',
 'phase0_check.py':'Allow the explicitly requested codex recovery branch only with migration-branch ancestry.'}
for c in changes:c['reason']=reasons[Path(c['path']).name]
(P/'change_manifest.json').write_text(json.dumps(dict(source_before=baseline['source_hash'],source_after=source,
    branch='codex/overnight-recovery-2026-10-17',commit=baseline['commit'],files=changes),indent=2)+'\n')

runs=[]
for output in sorted((ROOT/'runtime/overnight-recovery-demo/sessions').iterdir()):
    f=output/'terminal_result.json'
    if not f.exists():continue
    v=read(f);status=read(output/'status.json')
    events=[json.loads(x) for x in (output/'events.jsonl').read_text().splitlines()]
    runs.append(dict(output=str(output),session_id=output.name,source_hash=v['source_hash'],status=v['status'],
        terminal_flat=v['terminal_flat'],threads_stopped=v['threads_stopped'],requests=v['public_receipt_count'],
        signatures=v['signatures_created'],writes=v['exchange_writes'],intents=v['execution_intents'],
        readbacks=v['terminal_readbacks'],scan_windows=len({x['latest_scan_ms'] for x in events if x.get('latest_scan_ms')}),
        result_sha256=sha(f),restart_context=status.get('restart_context'),last=v))
assert runs and all(r['status']=='STOPPED' and r['terminal_flat'] and r['threads_stopped'] and r['signatures']==r['writes']==r['intents']==0 for r in runs)
final_runs=[r for r in runs if r['source_hash']==source];assert final_runs
latest=max(final_runs,key=lambda r:r['readbacks'][-1]['observed_ms']);v=latest['last']
local=local_execution_state(ROOT);assert local['status']=='BLOCKED_UNRESOLVED_INTENT'
account=v['account'];assert not account['positions'] and not account['open_orders']
assert not [f for f in account['fills'] if f['timestamp_ms']>=1792217727523]
assert not [f for f in account['funding_events'] if f['timestamp_ms']>=1792217727523]
rows=v.get('capacity_ranking',[])
assert len(rows)==len(v['signals'])==10
assert v['session_performance']['as_of_ms']==v['account_observed_ms']
now=time.time_ns()//1000000
(P/'market_capacity_snapshot.json').write_text(json.dumps(dict(source_hash=source,session_id=latest['session_id'],
    last_complete_scan_ms=v['latest_scan_ms'],snapshot_only=True,signing_authority='NONE',
    capacity_ranking=rows,liquidity=v['liquidity'],signals=v['signals'],opportunity_counts=v['opportunity_counts']),indent=2)+'\n')
engineering='\n'.join(f"| `{c['path']}` | {c['reason']} |" for c in changes)
table='\n'.join(f"| {r['symbol']} | {r['liquidity_only_quantity']} | {r['liquidity_only_notional']} | {r['economically_viable_notional']} | {r['authorized_executable_notional']} | {', '.join(r['reasons'][:2])} |" for r in rows)
run_table='\n'.join(f"| {r['session_id']} | {r['source_hash'][:12]} | {r['scan_windows']} | {r['requests']} | {r['status']} | {r['terminal_flat']} |" for r in runs)
report=f'''# Overnight autonomous engine — final engineering release

Updated {stamp(now)}. **Verdict: BLOCKED_EXTERNAL_EVIDENCE.** The standalone observation engine is demonstrated and the final changed source passes its full release suite. Genuine autonomous trading is not qualified or authorized. No new actual-wallet signing or exchange write occurred.

## A. Engineering changes

Recoverable branch: `codex/overnight-recovery-2026-10-17`, starting commit `{baseline['commit']}`. The prior dirty/untracked working source is preserved in `source_before.tar.gz`; database snapshots and exact dump hashes are in `baseline.json`. This is not a claim that inherited changes were newly committed. Original NSE source is untouched.

| Source | Defect or purpose |
| --- | --- |
{engineering}

The frozen brain/methods/parameters, production scanner ranking/Top-3, order quantity precision, risk geometry, 10% both-best-level participation and 5 bps depth policy remain unchanged. Diagnostic ranking never feeds production signals. Existing native stop identity/trigger/child management, exact residual guards, durable nonce lease, bounded signer, global account lease and deterministic LONG orchestration were reused rather than rebuilt.

The new ledger records PERSISTED, signing, signed, dispatch attempt, HTTP response, legacy acceptance/terminal outcome, UNKNOWN and verified recovery stages. DISPATCHED is an attempt, not proof of delivery; HTTP acknowledgement is not acceptance or a fill. Fill/fee accounting still requires account records. The ledger grants no authorization or UNKNOWN resolution and is not backfilled into old trading history. Update/delete triggers and checksums protect the application audit chain. Original exceptions now retain sanitized causal details. No venue idempotency guarantee is invented; local durable identity and pre-HTTP claims prevent blind resubmission.

## B. Blocker resolution

| Original issue | Root cause / implementation / verification | Status and remaining dependency |
| --- | --- | --- |
| Historical UNKNOWN | Original native worker retained only generic ExchangeError; reconstructed pre-HTTP timing cannot replace admissible original evidence. Raw intent/nonce preserved; new future audit records are not retroactive proof. | **BLOCKED:** positive original causal/terminal evidence or an admissible sanctioned recovery mechanism. |
| Five-second freshness | Existing repaired same-wire reacquisition retained; exact age and SDK-delay tests rerun in focused/final suites. Five seconds is a local evidence policy, not Hyperliquid's documented nonce window. | **RESOLVED offline;** genuine authorized exchange validation remains separate. |
| Native stop lifecycle | Existing parent/child/trigger/partial/cancellation manager and tests retained. No actual native stop event or closing chain recovered. | **BLOCKED:** genuine registered-par acceptance, natural trigger/child SELL fills and cleanup proof. |
| Subminimum residual | Every minimum lot remains below ordinary minimum at sampled marks; historical one-lot BTC full-position IOC proves only that scope. | **BLOCKED:** applicable small-native semantics and genuine residual evidence. No guard/precision bypass. |
| Stale capacity/account display | Capacity now has independent freshness checks after candle recovery; local unresolved journal remains visible despite exchange flatness. | **RESOLVED in software;** fresh data may still be unavailable. |
| Return/fee ambiguity | Session actual cashflows and explicit return/balance bases separated from historical totals and target scenarios. | **RESOLVED display;** empirical expected edge and official score remain unknown. |
| Overnight authorization/window | No current mandate/acceptance; published practice ends Oct16 and scored trading begins Oct19. Actual constructor now rejects a gap interval. | **BLOCKED:** organizer gap permission/exact cutoff and a separately tested applicable authorization route, then exact human approval. |

No certificate was appended for CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce **1792217834069**. Its mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea` remains consumed/expired. See the [formal review packet](../practice_recovery_2026-10-17/VENUE_OPERATOR_REVIEW_PACKET.md) and `UNKNOWN_REVIEW_UPDATE.md`. No organizer/venue message was sent on behalf of the operator.

## C. Liquidity, friction and opportunity observations

These are genuine timestamped public snapshots, not a promise of current fill capacity. The evaluator takes the minimum of both BBO participation caps, both finite 5 bps depth caps, runtime lot rounding, current 1x account limits and a proposed upper cap. Actual authorized allocation, risk budget, venue/residual/protection support and approval remain independent zero/unknown gates. Nothing is enlarged to reach 1,000–10,000 notional.

| Market | Lot-rounded liquidity quantity | Liquidity-only notional | Conditional economic notional | Authorized executable notional | Leading reason |
| --- | ---: | ---: | ---: | ---: | --- |
{table}

Latest complete scan: {stamp(v['latest_scan_ms']) if v.get('latest_scan_ms') else 'not completed'}. Latest gate counts: `{json.dumps(v.get('opportunity_counts'))}`. Capacity counts refer to all observed markets, not a nested count of passing candidate signals. No qualified positive-edge LONG was established. Stale or incomplete completed candles are rejected rather than synthesized; the raw receipts retain their actual last timestamps. A current book does not make stale candle signals current.

The economic engine retains the frozen target geometry and baseline fee-adjusted RR controls. New reporting distinguishes that conditional target scenario from a statistically estimated expected return; the latter stays null without supporting evidence. Stress doubles friction and reserves adverse funding. Passive comparison is fee-only; queue position, missed fills and adverse selection remain unknown. No routing change or post-only activation was made.

The [participant guide](https://perpetual-alpha26.github.io/docs/) describes current positive base fees doubled on par; actual earlier fills support 0.09% taker. The existing runtime deliberately keeps its more conservative 6x base-rate bound (currently 0.27% taker) unchanged. No lower fee floor or higher risk allowance was silently substituted to manufacture an opportunity. Actual fill fees always govern realized P&L.

## D. Tests and source identity

**{release['totals']['tests']} passed, {release['totals']['failures']} failures, {release['totals']['errors']} errors, {release['totals']['skipped']} skips**, complete final regression. Source before/after: `{source}`. XML SHA-256 `{release['xml_sha256']}`; receipt SHA-256 `{sha(receipt)}`. Fresh Phase-0 and strategy-freeze checks passed before and after, on the dependency-pinned SDK 0.24.0 runtime.

A separate final-source rerun of the explicitly requested signing-boundary suite passed **9/9**, including 4,900/5,000/5,100 ms and delayed-SDK cases. Its receipt is `requested_boundary_receipt.json`; these nine are separate from the full-suite count. `preservation_receipt.json` confirms SQLite integrity/checkpoints and unchanged original trading proofs, UNKNOWN and nonce.

The 2,753-test release was the baseline; 30 new tests cover immutable/atomic audit recording, independent stale evidence, lot/depth bounds, negative stressed economics, defined P&L bases, local UNKNOWN visibility, dead-dashboard claims and finite competition windows. Existing integration suites exercise ambiguous entry/exit, partials, native accepted-but-untriggered/triggered-unfilled cases, fee/depth deterioration, nonce/duplicate/reconnect/crash/expiry/loss/stop behavior and source-bound approvals. All signed test fixtures use ephemeral wallets and have no actual exchange authority.

The first full run exposed a compatibility defect in the new signed audit hook with the separate fixed-leverage configuration sink. It failed before transmission in the ephemeral fixture. That failed release is preserved separately; the hook was corrected without authorizing configuration or making any actual account change. A subsequent run was deliberately interrupted to fix shutdown reporting (preserved without a valid XML/receipt). The complete final suite was then rerun after all corrections. Offline tests cannot certify native venue execution or eliminate all future software/network risk.

## E. Standalone observation and restart demonstration

| Session | Observed source prefix | Completed scan windows | Public receipts | Terminal status | Two flat readbacks |
| --- | --- | ---: | ---: | --- | --- |
{run_table}

All demonstrations used zero signatures, zero exchange writes and zero execution intents. The same-state duplicate launch returned `PAPER_OWNER_ALREADY_RUNNING`; session-specific stop completed, all background threads stopped, and a restart reacquired account truth without restoring authority. Earlier engineering-source runs are not presented as final-source execution qualification; the final-source smoke run is separately identified. This is a bounded demonstration, not a claim that an entire overnight outage/uptime period was observed. The engine requires no continuous LLM or coding agent.

Final readbacks: {stamp(latest['readbacks'][0]['observed_ms'])} and {stamp(latest['readbacks'][1]['observed_ms'])}, each empty positions/orders. The local historical UNKNOWN remains blocked independently. Mac/process/power/internet remain operational dependencies; there is no remote failover or signing auto-renewal.

## F. Exact operator commands

[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) gives verified doctor, read-only start, refreshed dashboard, exact approval workflow, authorized-interface template, graceful stop, restart and accounting commands. Today's usable manual command from this repository is:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --state runtime/terminal --scan-seconds 60
```

It is strictly **read-only**. No currently valid native proof, new mandate or human acceptance exists for `--authorized`. No dummy files or expired approvals were substituted. An approved future signer must retain LONG-only, one global position, 1x CROSS, exact allocation, two total entry attempts, carried risk/P&L, protection and finite hard expiry; none is an activity target or guaranteed loss cap.

## G. Genuine trading and performance evidence

New entry acknowledgement/fill, protective event, exit fill and qualification P&L: **NOT VERIFIED**. This engineering task performed no actual-wallet signing. Public reconciliation still contains only the October 15 BUY order **62755970305**, fill **800659111758533**, 0.0002 at 81,512, fee 0.014672; SELL order **62805581662**, fill **260274449763192**, 0.0002 at 81,909, fee 0.014743. Gross +0.0794, total fees 0.029415, funding +0.000527, historical net **+0.050512 TEST USDPR**. It is not today's or scored P&L.

Current observation-session reported gross/fees/funding/net are zero, with no new fills. Initial reported balance is 1,000,000.050512; that is neither an approved allocation nor free margin. Session percentages name that first verified balance as denominator; balance change is not cash-flow-adjusted or official oracle-marked performance. Unrealized position values remain separately reported. Sampled drawdown is not an intrabar guarantee; daily volatility/official score stay null when evidence is insufficient.

The [published evaluation](https://perpetual-alpha26.github.io/about) uses oracle-marked return, daily return variability and jury assessment with cross-team normalization. Peer/jury inputs are unavailable, so no financial score or first-place claim is fabricated. The [schedule](https://perpetual-alpha26.github.io/schedule) leaves Oct17–18 outside published practice/scored windows. Registration, exact timezone/cutoff and any gap exception require organizer evidence; a funded public wallet is not organizer permission.

## H. Go/no-go

**BLOCKED_EXTERNAL_EVIDENCE**

Software hardening and bounded standalone read-only operation are demonstrated. Trading still requires admissible resolution of the exact UNKNOWN, genuine native/residual qualification, applicable organizer window permission and a new exact source-bound human approval. Neither more capital nor a new approval alone can erase those prerequisites. No next-day worker, trading monitor, automatic restart, transfer, leverage change or renewal was installed.
'''
(P/'final_report.md').write_text(report)
(P/'implementation_report.md').write_text(report)
summary=dict(verdict='BLOCKED_EXTERNAL_EVIDENCE',updated_ms=now,source_hash=source,tests=release['totals'],
    xml_sha256=release['xml_sha256'],receipt_sha256=sha(receipt),boundary_tests=boundary_receipt,actual_signatures=0,actual_exchange_writes=0,
    unknown_resolved=False,native_protection_qualified=False,autonomous_authority=False,
    authorized_executable_notional='0',original_nonce=1792217834069,preservation_passed=True,
    runs=[{k:r[k] for k in r if k!='last'} for r in runs],local_execution_state=local,
    current_positions=[],current_orders=[],actual_new_fills=[],actual_new_fees='0',actual_new_funding='0',
    historical_oct15_net='0.050512',official_score=None,leaderboard_rank=None)
(P/'release_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(verdict=summary['verdict'],tests=release['totals']['tests'],source=source,reports_saved=True)))
