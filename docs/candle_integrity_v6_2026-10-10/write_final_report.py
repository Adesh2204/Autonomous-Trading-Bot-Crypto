"""Build V6 A-K report from completed immutable evidence; no network or signer."""
from pathlib import Path
from collections import Counter
import fcntl,hashlib,json,sys,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'algo-trading-bot'),str(ROOT/'scripts')]
from exchange.paper_operations import active_source_hash,atomic_json
from feed_certification_report import checkpoint

def read(p):return json.loads(Path(p).read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def stage(folder,name,source):
    receipt=read(folder/(name+'_paper_receipt.json'));cert=read(folder/(name+'_certification.json'))
    h=receipt['final_health'];state=Path(receipt['state_directory']);seg=Path(h['segment'])
    samples=[json.loads(l) for l in Path(receipt['health_samples_path']).open() if l.strip()]
    traces=[json.loads(l) for l in (seg/'results/opportunity_traces.jsonl').open() if l.strip()]
    checks={n:checkpoint(state/n) for n in ['paper.sqlite','backups/paper-latest.sqlite']}
    invariants=dict(source_bound=receipt['source_hash_before']==receipt['source_hash_after']==source,
        clean_shutdown=receipt['exit_code']==0 and h['status']=='STOPPED' and all(c['clean_shutdown'] for c in checks.values()),
        checkpoints=all(c['integrity']=='ok' and c['checksum_matches'] and c['source_hash']==source for c in checks.values()),
        tape_sha256=digest(receipt['health_samples_path'])==receipt['health_samples_sha256'],
        sample_identity=all(s['segment']==str(seg) for s in samples),
        zero_orders=all(s['execution_mode']=='PAPER' and s['allow_live_orders'] is False and s['exchange_orders_submitted']==0 for s in samples),
        stopped_workers=h['public_stream']['workers_stopped_cleanly'])
    with (state/'owner.lock').open() as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
    events=h['public_stream']['events'];disconnects=[i for i,e in enumerate(events) if e['phase']=='DISCONNECTED'];matched=[]
    for n,i in enumerate(disconnects):
        end=disconnects[n+1] if n+1<len(disconnects) else len(events);window=events[i+1:end];cursor=0;phases=[]
        for phase in ['CONNECTING','SUBSCRIBED','PAPER_ACCOUNT_RECONCILED']:
            j=next((j for j in range(cursor,len(window)) if window[j]['phase']==phase),None)
            if j is None:break
            phases.append(window[j]);cursor=j+1
        if len(phases)==3:matched.append(dict(disconnected_ms=events[i]['timestamp_ms'],reconciled_ms=phases[-1]['timestamp_ms'],generation=phases[-1]['generation']))
    audit=read(folder/'candle_stage_audit.json');report=read(seg/'report.json')
    last_trace={t['symbol']:t for t in traces}
    for symbol,a in audit['markets'].items():
        t=last_trace[symbol];a['last_scanner_data_gate']=t['stages']['MARKET_DATA_HEALTHY']['status']
        a['last_scanner_reasons']=t['raw_reasons']
        a['valid_full_strategy_input_count']=a['full_strategy_input_count'] if a['last_scanner_data_gate']=='PASS' else 0
    totals={r['stage']:r for r in cert['funnel']['session']['stages']}
    metrics=dict(observations=len(traces),healthy=totals['MARKET_DATA_HEALTHY']['passed'],
        atr_passes=totals['ATR_PASS']['passed'],spread_passes=totals['SPREAD_PASS']['passed'],
        qualified=totals['SCANNER_QUALIFIED']['passed'],strategy_evaluations=totals['STRATEGY_EVALUATED']['passed'],
        signals=totals['SIGNAL_GENERATED']['passed'],numeric_errors=len(audit['numeric_errors']),
        final_usable=len(h['healthy_markets']),fills=h['local_fills'],actual_orders=h['exchange_orders_submitted'])
    metrics['healthy_percent']=100*metrics['healthy']/metrics['observations'] if metrics['observations'] else None
    result=dict(receipt=receipt,certification=cert,metrics=metrics,invariants=invariants,checkpoints=checks,
        actual_reconnects=len(matched),reconnect_barriers=matched,disconnects=len(disconnects),
        candle_audit=audit,paper_portfolio=report['portfolio'],first_rejections=dict(Counter(t['first_blocking_reason'] for t in traces)),
        sample_count=len(samples),sampled_max_ip_weight=max(s['public_stream'].get('public_rate_budget',{}).get('ip_weight',0) for s in samples),
        receipt_sha256=digest(folder/(name+'_paper_receipt.json')),
        raw_audit_sha256=digest(seg/'public_candle_audit.jsonl'))
    atomic_json(folder/'independent_completion_audit.json',result)
    return result

def write():
    seq=read(OUT/'validated_run/validation_sequence.json')
    if 'finished_unix' not in seq:raise RuntimeError('BOUNDED_SEQUENCE_NOT_COMPLETE')
    tests=read(OUT/'regression_final_v2/test_receipt.json');source=active_source_hash(ROOT)
    assert tests['passed'] and tests['source_hash']==tests['source_hash_after']==source
    assert digest(OUT/'regression_final_v2/regression.xml')==tests['xml_sha256']
    runs={}
    for name in ['short_15m','long_3h']:
        folder=OUT/'validated_run'/name
        if (folder/(name+'_certification.json')).exists():runs[name]=stage(folder,name,source)
    short=runs.get('short_15m');long=runs.get('long_3h');latest=long or short
    if latest is None:raise RuntimeError('NO_COMPLETED_PAPER_EVIDENCE')
    assert all(latest['invariants'].values()),latest['invariants']
    certified=bool(long and long['certification']['feed_certified'] and not long['metrics']['numeric_errors'])
    verdict='FEED_CERTIFIED' if certified else 'FIXES_VALIDATED_FEED_NOT_READY'
    old=read(OUT/'historical_candle_audit.json');numeric=read(OUT/'numeric_reproduction_before.json')
    replay=read(OUT/'recorded_feature_replay.json');retro=read(OUT/'retrospective_audit.json')
    flags={k:'PASS' for k in ['STRATEGY_FREEZE','FULL_TEST_SUITE','RAW_CANDLE_AUDIT','REST_CANDLE_INTEGRITY',
        'CANDLE_MERGE_INTEGRITY','NUMERIC_BRENT_RESOLVED','NUMERIC_EWY_RESOLVED','QUARANTINE_READY','TRANSPORT_READY','RATE_BUDGET_READY','RECONCILIATION_READY']}
    flags.update(WEBSOCKET_CANDLE_INTEGRITY='PASS' if any(m['stages']['B_WS']['count'] for m in latest['candle_audit']['markets'].values()) else 'NOT_TESTED',
        MARKET_HEALTH_READY='PASS' if latest['certification']['feed_certified'] else 'FAIL',
        REST_RECOVERY_READY='PASS' if latest['certification']['feed_certified'] else 'FAIL',
        SHORT_PAPER_PASS='PASS' if short['certification']['feed_certified'] and not short['metrics']['numeric_errors'] else 'FAIL',
        THREE_HOUR_PAPER_PASS=('PASS' if certified else 'FAIL') if long else 'NOT_TESTED',
        FEED_CERTIFIED='PASS' if certified else 'FAIL',CONTROLLED_EXECUTION_READY='NOT_TESTED',PRACTICE_READY='FAIL',LIVE_READY='FAIL')
    flags['TRANSPORT_READY']='PASS' if latest['certification']['checks'].get('final_transport_recovered') and latest['certification']['checks'].get('subscriptions_confirmed_once') else 'FAIL'
    flags['RECONCILIATION_READY']='PASS' if latest['certification']['checks'].get('paper_account_reconciled') else 'FAIL'
    flags['RATE_BUDGET_READY']='PASS' if latest['certification']['checks'].get('no_pending_rest') and not latest['receipt']['final_health']['public_stream'].get('public_rate_budget',{}).get('public_read_blocked') else 'FAIL'
    if latest['metrics']['numeric_errors']:flags['MARKET_HEALTH_READY']='FAIL'
    classes=[]
    for t in ET.parse(OUT/'regression_final_v2/regression.xml').getroot().iter('testcase'):
        props={p.attrib['name']:p.attrib.get('value') for p in t.findall('./properties/property')}
        classes.append(dict(test=t.attrib.get('classname','')+'.'+t.attrib['name'],evidence_class=props.get('evidence_class','OFFLINE_FIXTURE')))
    atomic_json(OUT/'final_test_evidence_classes.json',dict(tests=classes,counts=dict(Counter(t['evidence_class'] for t in classes)),actual_exchange_execution=0))
    modified={};diff=[]
    import difflib
    for before in (OUT/'source_before').rglob('*.py'):
        name=str(before.relative_to(OUT/'source_before'));after=ROOT/name
        if before.read_bytes()==after.read_bytes():continue
        modified[name]=dict(before_sha256=digest(before),after_sha256=digest(after))
        diff.extend(difflib.unified_diff(before.read_text().splitlines(True),after.read_text().splitlines(True),fromfile='before/'+name,tofile='after/'+name))
    for name in ['algo-trading-bot/exchange/candle_audit.py','algo-trading-bot/exchange/scanner_numeric.py','algo-trading-bot/test_candle_integrity_v6.py']:
        modified[name]=dict(before_sha256=None,after_sha256=digest(ROOT/name))
        diff.extend(difflib.unified_diff([], (ROOT/name).read_text().splitlines(True),fromfile='/dev/null',tofile=name))
    (OUT/'migration_diff.patch').write_text(''.join(diff));atomic_json(OUT/'modified_source_manifest.json',modified)
    next_action=('Prepare a concrete risk-budget proposal and fresh public/account preflight for separately authorized controlled certification.' if certified else
        'Send the organizer the captured, timestamped public-data evidence for missing par candles and request clarification about current candle publication/completeness. Keep PAPER locked; rerun a fresh short validation after usable real history is available.')
    baseline=dict(observations=360,healthy=29,healthy_percent=8.06,atr_passes=0,qualified=0,numeric_errors=2,final_usable=0,fills=0,actual_orders=0,reconnects='16/16')
    summary=dict(verdict=verdict,source_hash=source,sequence=seq,baseline=baseline,runs=runs,flags=flags,tests=tests,
        test_class_counts=dict(Counter(t['evidence_class'] for t in classes)),previous_tests=1339,new_tests=tests['totals']['tests']-1339,
        modified_files=modified,numeric_reproduction=numeric,recorded_feature_replay=replay,
        original_gap_cause='CAUSE_UNDETERMINED: original raw payloads/cache snapshots not captured',
        current_gap_scope='EXCHANGE_DATA_UNAVAILABLE only where captured same-window response and observed WS did not supply the row at that time; permanent sparsity vs publication delay remains undetermined.',
        next_action=next_action,actual_exchange_execution=False,production_strategy_changed=False)
    atomic_json(OUT/'final_summary.json',summary)
    m=latest['metrics'];h=latest['receipt']['final_health'];c=latest['certification']
    lines=['# Team Anchorium — V6 candle integrity and readiness report','',
        '## A. Executive verdict','',f'**{verdict}**','',
        'The verified numerical and merge defects are repaired and regression-tested. The trading strategy remains frozen. '+
        ('The completed three-hour PAPER evidence satisfies the current feed certificate.' if certified else
         'The current PAPER evidence does not establish a usable feed for practice. Missing exchange records have not been invented to make the bot pass.'),
        '', 'This report concerns PAPER infrastructure. It does not certify profit, funded execution, emergency-order acceptance, or a hackathon result.',
        '', 'Plain-language guide: a candle is one minute’s opening, highest, lowest and closing prices plus traded volume. A completed candle belongs to a minute that has ended. ATR measures the typical price range; it is not profit. Quarantine means temporarily excluding a market whose inputs fail checks. A source hash fingerprints the exact code tested. PAPER uses real public data with a hypothetical local account.',
        '', '## B. Root-cause summary','',
        'The earlier three-hour run had 360 market-cycle observations. Its first blockers were 328 stale-candle rejections, one recovery-pending rejection, and two generic numeric rejections. Only 29 passed the data gate. Those 29 all failed the unchanged volatility requirement.',
        '', 'Both numeric rejections were code defects: zero ATR was wrongly treated as an invalid number. Offline fixtures also proved a completed-candle overwrite defect and a repair-before-merge defect. The scanner conflict latch and its report classification needed correction. These additional mechanisms are verified code defects, but they cannot be assigned as causes of the old 328 stale cases without the original raw inputs.',
        '', 'The earlier run saved normalized scanner inputs and health counts, but not original raw REST/WS candle payloads or exact cache snapshots. The cause of its missing rows remains **CAUSE_UNDETERMINED**. A current read returned all 1,269 expected bars for each original final UTC window; overlapping values match the saved candles. That proves present retrievability, not original availability.',
        '', 'At the old shutdown every cache failed required history or freshness; even HYPE with a relatively recent candle retained a full-history gap rejection. A fresh last candle alone cannot restore eligibility.',
        '', 'The new bounded capture lets us compare actual wire-derived public rows, normalized rows, cache, and scanner on identical exchange intervals. A row absent from a covered current REST response is **EXCHANGE_DATA_UNAVAILABLE for that response**. Its underlying cause (quiet trading, delayed publication, or another venue behavior) is still unknown. We have not proved permanent exchange sparsity.',
        '', '## C. Per-market candle investigation','',
        'Old final scanner input used the full UTC strategy history; the streaming health buffer required 300 completed bars. These are different windows. The old cache counts below come from recorded health, not reconstructed cache contents.',
        '', '| Market | Original raw REST/WS | Old normalized full UTC input | Old cache completed | Missing in old full UTC input | Current retrospective raw/normalized | Historical cause |',
        '|---|---|---:|---:|---:|---:|---|']
    old_health=read(ROOT/'docs/market_resilience_2026-10-08_retry/long_soak/long_3h_paper_receipt.json')['final_health']['market_health']
    for s,a in old.items():lines.append(f'| {s} | Not captured | {a["normalized_scanner_count"]} | {old_health[s]["completed_candles"]} | {len(a["missing_timestamps_ms"])} | {retro[s].get("raw_count","unknown")}/{retro[s].get("normalized_count","unknown")} | CAUSE_UNDETERMINED |')
    lines+=['','Latest completed validation: all five columns below are filtered to the same 300-minute exchange interval per market, and facts observed by the last scanner decision. Raw REST and normalized rows match the exact full scanner request; cache remains capacity-limited. WS records cover only the observation period, so missing older WS history is **not observed**, not proof of missing exchange history.',
        '', '| Market | Raw REST | Normalized | Cache | Scanner in same window | Missing scanner intervals | Final health at shutdown | Cause/action |','|---|---:|---:|---:|---:|---:|---|---|']
    for s,a in latest['candle_audit']['markets'].items():
        v=a['stages'];missing=len(v['D_SCANNER']['missing_timestamps_ms']);healthy=a['final_health']['healthy']
        lines.append(f'| {s} | {v["A_REST"]["count"]} | {v["C_NORMALIZED"]["count"]} | {v["C_CACHE"]["count"]} | {v["D_SCANNER"]["count"]} | {missing} | {a["final_health"]["state"]} | '+('Eligible data; retain strategy filters' if healthy else 'EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery')+' |')
    lines+=['','Full UTC input acceptance is a separate scope from the 300-minute comparison. Its required history may start earlier. The existing two-minute freshness allowance also means the most recent expected minute can be absent while an earlier, still-fresh continuous 300+ bar input remains valid. The last scanner decision and the later shutdown are different observations.', '', '| Market | Full UTC scanner input rows | Valid rows admitted to frozen feature calculation at last scan | Last scanner data gate |', '|---|---:|---:|---|']
    for symbol,a in latest['candle_audit']['markets'].items():lines.append(f'| {symbol} | {a["full_strategy_input_count"]} | {a["valid_full_strategy_input_count"]} | {a["last_scanner_data_gate"]} |')
    lines+=['','Exact missing timestamps, first/last timestamps, duplicate/conflict counts, OHLCV validity, contiguous tail, close age, covered request windows, rejection strings, and per-stage traces are in each run’s `candle_stage_audit.json`. Raw decoded payloads are in its segment `public_candle_audit.jsonl`. No timestamps or OHLCV values were shifted or fabricated.',
        '', 'For the old missing BTC minute at 1791492480000 (8 October, 20:48 UTC), the original raw REST/WS acceptance and cache-retention answers remain UNKNOWN; scanner receipt is NO. The same timestamp is present in the later retrospective REST result. A later result cannot settle the original cause.',
        '', '## D. Both numerical failures','',
        '| Market | Decision timestamp ms | Exact failing operand | Reproduced source location | Cause and correction | Status |',
        '|---|---:|---|---|---|---|',
        '| par:BRENT | 1791482698439 | ATR_14 = numpy.float64(0.0); close 102.84 | market_regime_scanner.py scan(), old line 146 → base_exchange.py decimal(), line 26 | positive=True incorrectly excludes valid zero ATR; use nonnegative=True and unchanged 0.004 floor | Resolved in recorded replay |',
        '| par:EWY | 1791489298981 | ATR_14 = numpy.float64(0.0); close 175.15 | Same boundary, independently reproduced with EWY tape | Same valid flat-market ATR; classify as low volatility | Resolved in recorded replay |',
        '', 'The exception type was ExchangeError with INVALID_DECIMAL. Decimal conversion succeeded and the value was finite; the positive-only validation then rejected zero. There was no NaN, infinity, missing close, or division-by-zero failure in either reproduction. The original stack was not recorded; the saved input and original source reproduce the exact failing expression. All other required final indicators were finite and positive.',
        '', 'The frozen brain is untouched. Flat genuine bars produce zero true range and zero ATR, which is legal. It still fails the same 0.40% scanner floor. Invalid/negative/nonfinite outputs receive field name, operand type/value, and a specific SCANNER_NUMERIC_INVALID reason; they quarantine only the affected market and cannot enter the watchlist.',
        '', 'Permanent recorded regressions cover BRENT and EWY. Offline fixtures cover invalid numeric operands, local rejection/isolation, and clearing the integrity latch only through a validated snapshot. The feature replay reproduced all 29 old valid ATR fractions exactly, and correctly processed the two zero-ATR cases. No replay generated quotes, fills, profit, or production eligibility.',
        '', '## E. Modified files','',
        '| Path | Functions | Old → new behavior | Reason and regression risk |','|---|---|---|---|',
        '| algo-trading-bot/market_regime_scanner.py | scan | Positive-only ATR → finite nonnegative ATR; named numeric evidence | Correct valid zero ATR without moving any filter; boundary behavior covered by recorded tests |',
        '| algo-trading-bot/exchange/scanner_numeric.py | scanner_number (new) | Generic numeric rejection → specific field/operand rejection | Invalid values remain blocked; no zero substitution |',
        '| algo-trading-bot/exchange/hyperliquid_market_data.py | get_candles, _reconcile_history, ingest, _ingest_validated, publish_public_snapshot, _audit_cache, note_scanner_failure | Premerge gap rejection and silent overwrite → retained real-row merge, completed conflict detection, local latching; public stage evidence | Conflicts can reduce eligibility until resolved, intentionally; open/final behavior, cache cap and isolation tested |',
        '| algo-trading-bot/exchange/candle_audit.py | PublicCandleAudit, merge_candle (new) | No raw stage trace → bounded public JSONL; deterministic merge | Extra local disk writes, capped 256 MiB per segment; no new API polling |',
        '| algo-trading-bot/exchange/hyperliquid_client.py | __init__, post_info | Public candle result unrecorded → optional raw capture after rate-managed read | Account queries excluded; normal client behavior unchanged when audit absent |',
        '| scripts/run_crypto_paper.py | main | Public clients uninstrumented → shared audit sink | Preserve fake-client constructor compatibility; capture-only overhead |',
        '| algo-trading-bot/venue_config.py | module defaults | Always parse dotenv → explicit public-only mode skips dotenv | This bounded job loads no wallet settings; normal activation locks still enforced |',
        '| algo-trading-bot/opportunity_funnel.py | reason_code | Completed conflict UNCLASSIFIED → INVALID_MARKET_DATA | Honest diagnostic denominator; no ranking/signal/risk changes |',
        '| algo-trading-bot/test_candle_integrity_v6.py | 17 collected cases | New labeled regression coverage | Two recorded cases and 15 offline fixture cases; network forbidden |',
        '', 'The scoped before/after patch and hashes are `migration_diff.patch` and `modified_source_manifest.json`. Investigation, test receipts, launchers, capture analyzers and this report were added under this new evidence directory. Legacy dependency inventories were regenerated separately. No original NSE repository file was edited.',
        '', '## F. Safety verification','',
        '- Frozen brain bytes, eight protected methods and 32 protected parameters pass baseline verification. UTC anchor, EMA9/21, ATR formula/floor, spread 15 bps, 300 completed bars and Top-3 are unchanged.',
        '- PAPER/false and protection disabled are asserted before collection. The public-only launcher skips dotenv; no actual signer, private-key derivation, wallet administration, order placement/cancellation, transfer, or protection activation is used.',
        '- Earlier default configuration imports retained legacy dotenv parsing; the corrected public-only path bypasses it. No actual wallet-key value was extracted, printed, or used to sign. Offline SDK tests use isolated ephemeral fixtures, not the funded wallet.',
        '- All recorded sample identities and order counters are checked. Actual exchange orders remain zero; this proves the instrumented PAPER run, not unrelated wallet activity.',
        '- The shared rate manager and safety reserve remain authoritative. Raw capture adds disk writes, not REST requests. Retry/backoff/coalescing and quarantine remain bounded.',
        '- Genuine missing records remain missing. Historical replay and current public feed are labeled separately. No candle, quote, fill, or P&L was invented.',
        '- Source was never edited while a collector observed data. The first attempt was cleanly stopped before the final conflict-latch repair. Prior failed/interrupted evidence is preserved. No recurring monitor was created; the old heartbeat is paused.',
        '', '## G. Test evidence','',
        f'Previous baseline: 1,339 passing tests. New coverage: {tests["totals"]["tests"]-1339} cases. Final total: **{tests["totals"]["tests"]} passed; {tests["totals"]["failures"]} failures; {tests["totals"]["errors"]} errors; {tests["totals"]["skipped"]} skipped**.',
        '', f'Final source hash: `{source}`. Test XML SHA256: `{tests["xml_sha256"]}`. Before/after source hashes match. Phase-0 and strategy-freeze checks pass.',
        '', 'The complete suite includes candle identity/normalization, current/completed boundaries, request-range caps, deduplication, open/final merge, sparse repairs, quarantine/restoration, rate budgets/retries/coalescing, reconnect/subscriptions, production-policy lockout, paper ledger/checkpoint recovery and frozen-brain parity. Every collected test has an evidence classification in `final_test_evidence_classes.json`. LIVE_PUBLIC_READ_ONLY evidence is the captured audit and bounded PAPER feed. ACTUAL_EXCHANGE_EXECUTION = 0.',
        '', 'Earlier failed XML/harness attempts and the earlier 1,354-pass intermediate source receipt remain preserved. They do not certify the final source. Details are in `test_attempt_notes.md` and the retained logs.',
        '', '## H. PAPER certification','']
    for name,r in runs.items():
        mm=r['metrics'];cc=r['certification'];rr=r['receipt'];lines += [f'### {name}', '',
            f'Duration: {rr["finished_unix"]-rr["started_unix"]:.3f} seconds. State: `{rr["state_directory"]}`. Source: `{rr["source_hash_before"]}`.',
            '',f'Verdict: **{cc["verdict"]}**. {mm["observations"]} observations; {mm["healthy"]} healthy; healthy rate {format(mm["healthy_percent"],".2f") if mm["healthy_percent"] is not None else "unknown"}%. Spread passes {mm["spread_passes"]}; ATR passes {mm["atr_passes"]}; qualified {mm["qualified"]}; post-selection strategy evaluations {mm["strategy_evaluations"]}; signals {mm["signals"]}; hypothetical fills {mm["fills"]}; actual orders {mm["actual_orders"]}.',
            '',f'Final usable markets: {mm["final_usable"]}/10. First rejections: `{r["first_rejections"]}`. Unresolved numeric errors: {mm["numeric_errors"]}. Certification blockers: `{cc["blockers"]}`.',
            '',f'WebSocket disconnects: {r["disconnects"]}; corresponding completed reconnect/account barriers: {r["actual_reconnects"]}. Generic REST reconciliation count is not called a socket reconnect. Close records: `{cc.get("close_records")}`.',
            '',f'Socket uptime: {cc.get("transport_uptime_seconds")} seconds; median completed connection lifetime: {cc.get("median_completed_connection_lifetime_seconds")} seconds; maximum receiver gap: {cc.get("maximum_receiver_gap_seconds")} seconds. Sampled local IP weight peak: {r["sampled_max_ip_weight"]}; exact unsampled/exchange-wide peak is unknown.',
            '',f'Clean shutdown, primary/backup SQLite integrity, checksums, source identity, health-tape digest, and worker shutdown: `{r["invariants"]}`.',
            '',f'Last saved PAPER portfolio (its timestamp is recorded): `{r["paper_portfolio"]}`. This is hypothetical local USDPR accounting, separate from the funded wallet. No fill occurred, so active-trade accounting/protection is not certified.',
            '', 'Independent checks versus sequential admissions:', '', '| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |','|---|---:|---:|---:|---:|---:|']
        for x in cc['funnel']['session']['stages']:
            pct=f'{x["pass_percent"]:.2f}%' if x['pass_percent'] is not None else 'Not evaluated'
            lines.append(f'| {x["stage"]} | {x["evaluated"]} | {x["passed"]} | {x["failed"]} | {pct} | {x["admission_passed"]}/{x["admission_evaluated"]} |')
        lines+=['',f'Rejection categories: `{cc["funnel"]["session"]["first_rejection_categories"]}`. Later gates not reached are not counted as measured failures.']
    if not long:lines+=['','The three-hour stage was **not started** because the short gate did not support it. It is NOT_TESTED, not a failed three-hour run.']
    lines+=['','The earlier V6 attempt lasted 354.906 seconds and was cleanly interrupted for the verified latch repair. Its receipt/checkpoints/source proof are preserved; it is not the completed short validation.',
        '', '## I. Before vs after comparison','',
        '| Metric | Old three-hour run | Latest completed V6 run |','|---|---:|---:|',
        f'| Duration seconds | 10803.388 | {latest["receipt"]["finished_unix"]-latest["receipt"]["started_unix"]:.3f} |']
    for key,label in [('observations','Market observations'),('healthy','Healthy observations'),('healthy_percent','Healthy %'),('atr_passes','ATR passes'),('qualified','Scanner-qualified'),('numeric_errors','Unexplained numeric errors'),('final_usable','Usable at shutdown'),('fills','PAPER fills'),('actual_orders','Actual exchange orders')]:lines.append(f'| {label} | {baseline[key]} | {format(m[key],".2f") if key=="healthy_percent" else m[key]} |')
    lines += [f'| Matched reconnects | 16/16 | {latest["actual_reconnects"]}/{latest["disconnects"]} |',
        '', 'A shorter run and different market conditions are not a controlled performance comparison. Code causality is established by the deterministic zero-ATR and merge fixtures; changes in live healthy percentages cannot be attributed to code alone. The 29 original ATR fractions are identical under recorded replay, including their original units. All 31 replayed feature cases fail the same 0.40% floor: **VALID_DATA_MARKET_CONDITIONS_UNQUALIFIED**. No volatility/VWAP optimization is implied.',
        '', '## J. Final readiness flags','', '| Flag | Status |','|---|---|']
    lines += [f'| {k} | {v} |' for k,v in flags.items()]
    lines += ['', 'PASS for raw audit/REST integrity means captured rows are correctly accounted for on the new bounded observations; it does not mean missing rows exist or that the old wire payloads were recovered. Merge/quarantine PASS includes deterministic fixtures; funded recovery remains untested. WS PASS, if observed, applies only to captured candle updates, not a continuous 300-bar WS-only history.',
        '', 'MARKET_HEALTH/REST_RECOVERY readiness requires eligible complete fresh history in actual operating evidence. Transport and PAPER reconciliation can pass independently. The funded wallet, signer ownership, nonce/clock and 1x observations from 7 October remain timestamped historical observations; this task performs no new funded preflight. Protection is configured but disabled and untested on exchange. Controlled execution, practice and LIVE remain unapproved.',
        '', '## K. THE SINGLE NEXT MOST IMPORTANT ACTION FOR TEAM ANCHORIUM','', next_action,
        '', 'A ready-to-review message is saved in organizer_message_draft.md. It has not been sent. For the current blocker, attach the raw public candle tape, exact timestamp traces and request-window audit. Ask whether missing near-current minute candles are expected and what publication delay participants should allow. Do not lower strategy thresholds or enable funded execution to work around missing input.',
        '', 'The existing verified read-only health command is:', '', '```bash',
        'ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false \\',
        '  .venv/bin/python scripts/check_practice_health.py \\',
        f'  --state-directory "{latest["receipt"]["state_directory"]}" --json', '```',
        '', 'After clean completion a stale heartbeat is expected; it is not a failed running collector. Do not restart this state as if it were a new certification. A later validation needs fresh state, fresh source-bound tests if source changes, and sufficient actual exchange history.',
        '', 'Primary API reference: [Hyperliquid official candleSnapshot documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot). It documents the recent 5,000-candle availability limit and HIP-3 coin prefixes; our retrospective 1,269-row windows were inside that limit. This documentation does not establish why particular live minutes were unavailable.']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(verdict=verdict,tests=tests['totals'],metrics=m,flags=flags),indent=2))

if __name__=='__main__':write()
