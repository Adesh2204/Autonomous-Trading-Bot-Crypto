"""Render actual release/readiness evidence; cannot accept or execute a mandate."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sys,time,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.pas_controller import assess
read=lambda p:json.loads((O/p).read_text())
write=lambda p,v:(O/p).write_text(json.dumps(v,indent=2,default=str)+'\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
now=time.time_ns()//1000000;source=active_source_hash(R);receipt=read('regression_release_final/test_receipt.json')
assert receipt['passed'] and receipt['source_hash']==receipt['source_hash_after']==source
assert sha(O/'regression_release_final/regression.xml')==receipt['xml_sha256']
assert receipt['totals']==dict(tests=3088,failures=0,errors=0,skipped=0)
assert read('preservation_receipt.json')['all_53_preserved']
launch=read('public_observer_release_launch.json');current=json.loads((Path(launch['state'])/'current.json').read_text())
live=json.loads((Path(current['output'])/'status.json').read_text())
assert source==live['source_hash']==launch['source_hash'] and live['signing_authority']=='NONE'
assert live['TRADING_AUTHORIZED'] is False and live['AUTO_TRADING_ACTIVE'] is False
write('final_observer_snapshot.json',live)
controller=assess(live,now);write('controller_verification.json',controller)
f=read('targeted_forensic.json');h=read('history_review/history_review.json');market=read('final_market_read/snapshot.json')
assert h['source_hash']==h['source_hash_after']==market['source_hash']==market['source_hash_after']==source
native={s:read(name+'/qualification_proposal.json') for s,name in [('pas:BTC','native_btc'),('pas:EWY','native_ewy')]}
markets={}
for s in ('pas:BTC','pas:EWY'):
    cache=live.get('market_history',{}).get(s,{})
    l=live.get('liquidity',{}).get(s,{})
    markets[s]=dict(probe_observed_ms=h['observed_ms'],probe_history=h['markets'][s]['history'],
        current_cache=cache,current_cache_age_ms=now-cache['latest_completed_ms'] if type(cache.get('latest_completed_ms')) is int else None,
        latest_public_liquidity=l,book_age_ms=now-l['book_ms'] if type(l.get('book_ms')) is int else None,
        account_limit_age_ms=now-l['active_asset_ms'] if type(l.get('active_asset_ms')) is int else None,
        broad_book_snapshot=market['markets'][s],authorized_executable_notional='0',expected_net_pnl=None,
        native_qualified=False,residual_qualified=False,qualification_proposal=native[s])
write('market_readiness.json',markets)
baseline=read('baseline.json');files={str(p.relative_to(R)):sha(p) for folder in ('scripts','algo-trading-bot')
    for p in (R/folder).rglob('*.py') if not {'venv','.venv','__pycache__'} & set(p.parts)}
write('source_manifest.json',dict(source_hash=source,starting_source=baseline['source_hash'],files=files,
    changed_or_added=[p for p,v in files.items() if baseline['files'].get(p)!=v],
    inventory_hashes={n:sha(R/n) for n in ('docs/legacy_dependency_inventory.csv','docs/legacy_dependency_inventory.json')}))
tests=ET.parse(O/'regression_release_final/regression.xml');write('test_case_manifest.json',
    [dict(module=x.get('classname'),name=x.get('name')) for x in tests.iter('testcase')])
statuses=dict(AUTOMATION_IMPLEMENTED=True,TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False,
    actual_pas_native_protection_qualified=False,actual_pas_residual_route_qualified=False,
    pas_subminimum_qualification_dispatch_available=False,complete_scored_activation_package_ready=False)
scope=('AUTOMATION_IMPLEMENTED is the tested guarded software lifecycle, funding detector, diagnostic state machine, '
    'source checks, risk controls and one accepted-mandate conditional handoff. It does not certify a usable PAS '
    'subminimum route or a genuine venue experiment. Unsupported PAS residual exceptions remain unimplemented; '
    'current native/exit minimum guards can keep all current BTC/EWY entries blocked. Venue evidence and any '
    'resulting reviewed narrow adapter/release remain necessary before that route can be used.')
external=[
    'Original organizer wallet binding and applicable PAS scored account/credit evidence; ambiguous local records are insufficient.',
    'Genuine USDP funding: current observed balance '+str(live.get('funding',{}).get('balance'))+'; practice USDPR is separate.',
    'Separate exact 1x CROSS configuration approval and authoritative BTC/EWY readbacks; current selected markets are 20x CROSS.',
    'Original terminal/rejection evidence OR an independently validated, separately accepted finite shared-domain isolation policy. Neither exists.',
    'Genuine PAS native protection and safe minimum-lot residual semantics/qualification. No PAS subminimum dispatch or PAR-proof substitution is admitted.',
    'Fresh authentic completed-bar history and eligible frozen LONG with current finite two-sided liquidity/fees/funding/account risk checks.',
    'Official scored window open, source-matched release and a genuinely accepted exact finite session; no current session acceptance exists.']
summary=dict(observed_ms=now,source_hash=source,starting_source=baseline['source_hash'],release=receipt,
    verdict='NO_GO',statuses=statuses,automation_scope=scope,remaining_conditions=external,
    historical_outcome=f['outcome'],historical_transmission=f['historical_transmission'],
    documented_nonce_window_has_passed=f['documented_nonce_window_has_passed'],historical_isolation_approved=False,
    account=live.get('account'),funding=live.get('funding'),funding_age_ms=now-live['funding']['observed_ms'],
    native_qualification=False,actual_human_acceptance_created=False,actual_session_mandate_created=False,
    observer=read('public_observer_verification.json'),controller=controller,
    original_53_preserved=True,actual_exchange_writes=0,actual_wallet_signatures=0,
    original_oct15_par_net='0.050512 TEST USDPR; historical PAR only, not current PAS PnL or organizer score',
    next_action='Obtain an attributable organizer response to EXTERNAL_EVIDENCE_REQUEST.txt; no changed message has been sent.',
    advance_approval='Not supported by the existing contract while funded source-bound discovery/native/organizer evidence are absent; later exact approval is necessary.',
    local_dependencies='Mac, Python process, power, internet and exchange. App-based supervision can stop; the standalone observer is independent of Codex/app.')
write('release_summary.json',summary);write('activation_decision.json',dict(observed_ms=now,source_hash=source,
    **statuses,scope=scope,verdict='NO_GO',remaining_conditions=external))
utc=datetime.fromtimestamp(now/1000,timezone.utc).isoformat()
lines=['# Anchorium V5.2 release and activation decision','',
    '**Trading verdict: NO-GO. No exchange action, real-wallet signature or human acceptance was created.**','',
    f'As of {utc}. Source `{source}` from verified V4 `{baseline["source_hash"]}`. '
    f'**{receipt["totals"]["tests"]} tests passed**, zero failures/errors/skips. XML SHA-256 `{receipt["xml_sha256"]}`. '
    'Strategy freeze and production-policy lockouts pass before/after; all 53 original journals and protected proof files are preserved.','',
    '| Verdict | Actual value |','|---|---|',
    *[f'| {k} | {str(v).upper()} |' for k,v in statuses.items()], '',scope,'',
    '## Engineering delivered','',
    '- Reproduced and repaired cross-market readiness composition: BTC native/residual evidence cannot qualify an EWY signal. Signal and capacity ages are checked independently; invalid/nonfinite capacity and corrupt cached funding clocks block safely.',
    '- Added `--authorized --wait-for-readiness` for an already genuinely accepted finite PAS mandate. The same pure acceptance validator serves waiting and runtime. Source, original acceptance, release/XML, organizer/discovery and raw native receipt hashes remain bound. The wait is consumed atomically once across state directories; no restart, renewal or acceptance creation exists.',
    '- Waiting has no signer. It stops its public collector, requires healthy persistence and actual terminal flat reconciliation, then calls the existing runtime builder once. Final fresh account/agent/configuration/source/native/nonce/clock/rate/liquidity/risk checks remain mandatory. A stale observed setup never becomes a forced order.',
    '- `AUTO_TRADING_ACTIVE` requires an owned transmitted order and matching actual account fill during the finite session. Merely running a scanner is insufficient. Failed startup/wait now saves a terminal result with unknown residual truth instead of leaving only a running-looking status.',
    '- Frozen strategy, 1x policy, 0.5% protective allowance, one global position, entry universe BTC/EWY, loss/action budgets, original UNKNOWN/nonces and consumed attempt remain unchanged. No fee/profit filter was relaxed.','',
    '## Original UNKNOWN: targeted forensic outcome','',
    f'**{f["outcome"]}**. Original CLOID `{f["original_cloid"]}`, nonce `{f["original_nonce"]}`. '
    'Fresh own historicalOrders returns four records, none identifying this CLOID; two direct orderStatus reads return unknownOid, with current PAR flat/no orders. '
    'Complete manifest identity and the original 2,726-test receipt/XML match. 267 original source files were recovered byte-for-byte, including SDK/native transport, authorization and nonce code; three other original content versions are unavailable locally. No complete content reconstruction is claimed.','',
    'The recovered guarded SDK signs expiresAfter equal to the original bounded approval expiry and disables raw SDK POST. The original wire payload/explicit causal failure was not retained. '
    'The documented two-day nonce horizon has now elapsed. These facts constrain future replay risk; they do not prove nontransmission, a past terminal outcome or complete historical accounting. '
    'The original durable nonce, signer-store binding, controls/checkpoints, old certificate identity and consumed terminal attempt were inspected without changes. '
    'PAR and PAS retain the same account/signer/nonce/position-safety domains. Distinct collateral and asset IDs do not establish isolation. '
    'An independently reviewed finite isolation procedure could be a separate path without asserting nontransmission, but no validated/accepted shared-domain policy exists. '
    'No generic certificate or blanket UNKNOWN bypass was added. See targeted_forensic.json and public_audit/.','',
    '## Protective execution decision','',
    'Retain the existing independent mark-trigger reduce-only fixed-size Stop Limit and exact-position reduce-only IOC cleanup guards. '
    'The full natural-trigger-to-linked-SELL-fill experiment is an internal unattended-release criterion in `long_session.require_native_evidence`, not an organizer rule found in the published guide. '
    'It cannot usefully be removed merely to activate sooner: genuine PAS armed/triggered/fill evidence and minimum residual semantics are still absent.','',
    '[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes mark triggers, fixed-size orders, parent-partial cancellation behavior and a 10% market-TP/SL tolerance. '
    'A Stop Market replacement would materially change the present allowance and contract; it needs independent risk review, route evidence and explicit authorization. '
    'An application watcher or immediate IOC is not exchange-resident outage protection. '
    '[Official error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) documents the ordinary $10 minimum; no reviewed PAS residual exemption has been established.','',
    'Separate unsigned BTC/EWY supervised-test proposals were refreshed without requiring production native qualification first. '
    'They bound one entry, <=25 TEST USDP, six signed actions, five-minute authority, a 120-second trigger observation with cleanup reserve, one owned cancellation round and at most two resolved cleanup IOC attempts. '
    'They remain blocked by unsupported minimum-lot cleanup, funding/configuration/history/organizer/approval conditions. '
    'Their observed prices are stale review evidence, not current approved order limits. No PAS qualification execution command is claimed; the PAR command is not a substitute.','',
    '## Account, market and advance approval','',
    f'Configured team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. '
    f'Observed Unified USDP balance: **{live.get("funding",{}).get("balance")}**, age at report {summary["funding_age_ms"]} ms. '
    'Organizer credit amount/provenance remains UNKNOWN. BTC/EWY are still actually 20x CROSS; configuration was not submitted. '
    'An older screenshot wallet differs; the prior ambiguous local-record acknowledgment did not resolve organizer registration.','',
    '| Market | Fresh probe contiguous bars | Latest completed in probe | Current cache age ms | Current leverage | Authorized capacity |',
    '|---|---:|---:|---:|---|---:|']
for s,x in markets.items():
    lines.append(f'| {s} | {x["probe_history"]["contiguous_tail_bars"]} | {x["probe_history"]["latest_completed_ms"]} | {x["current_cache_age_ms"]} | {x["latest_public_liquidity"].get("active_asset",{}).get("leverage")} | 0 |')
lines += ['', 'Both genuine probe histories now satisfy warmup. Freshness remains independent and is shown by the live controller/cache timestamp. '
    'The bounded stream review acknowledged eight subscriptions, received real book/context updates and no current candle update. '
    'No candles were synthesized or imported from PAR/mainnet. Book-only capacity is not funded/authorized capacity; expected net profit remains UNKNOWN without a current eligible setup. '
    'Actual PAS fills/fees/funding are reported separately in release_summary.json. Historical October 15 PAR net +0.050512 TEST USDPR is not today\'s PAS return or an official score.', '',
    'The existing mandate protocol cannot legitimately preapprove this missing-evidence environment: it requires funded fresh source-bound discovery, reviewed organizer provenance, actual native proof and a created/starts/approval/expiry ordering inside the scored phase. '
    'The five-minute genuine acceptance window and finite-session limits were preserved. No future-effective substitute or dummy acceptance was generated. '
    'A later valid accepted session needs no individual BUY/SELL prompts; the new wait can dispatch once only within that exact accepted scope after readiness and final checks pass.','',
    '[Published scored interval](https://perpetual-alpha26.github.io/schedule): October 19 12:00 UTC /17:30 IST to November 6 12:00 UTC /17:30 IST. '
    'The old October 17–18 special practice permission gate is not applied to open scored trading. Calendar opening does not establish funding, registration or signing authority.','',
    '## Shortest remaining path','',*['- '+x for x in external],'',
    '**Next concrete action:** obtain an attributable organizer response to [EXTERNAL_EVIDENCE_REQUEST.txt](EXTERNAL_EVIDENCE_REQUEST.txt), which specifies the exact wallet, original action and native/residual records. No changed message has been sent. '
    'Then refresh the separately approved configuration and qualification reviews; implement only an admissible route-specific exception if the evidence requires one, with another matched regression. '
    'Only after those conditions can the operator create and accept a fresh finite scored mandate using OPERATOR_RUNBOOK.md. No blocked/stale proposal is being submitted for approval.','',
    f'Public observer PID {launch["worker_pid"]}, caffeinate {launch["caffeinate_pid"]}, session {current["session_id"]}. '
    'It detects funding and updates readiness automatically without a signer. Both original trading heartbeats remain PAUSED. '
    'The previous observer stopped cleanly with two real flat/zero-order readbacks and healthy SQLite/history. '
    'The new observer is independent of Codex/app; it depends on this Mac, Python, power, internet and exchange availability. '
    'Source changes stop it. App-based supervision can be interrupted; caffeinate cannot guarantee uptime. '
    'No profit, loss cap, ranking or organizer whitelisting is guaranteed.','',
    'Validation: full source-matched regression and XML; reproductions.json; focused XML; test_case_manifest.json; preservation_receipt.json; source_manifest.json; targeted_forensic.json; raw public /info receipts; real controller_verification.json; public_observer_verification.json.']
(O/'FINAL_RELEASE_REPORT.md').write_text('\n'.join(lines)+'\n')
files={str(p.relative_to(O)):sha(p) for p in O.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in {'artifact_manifest.json','public_observer_release.log'}}
write('artifact_manifest.json',dict(observed_ms=now,source_hash=source,files=files,excluded_dynamic=['public_observer_release.log'],scope='Static report snapshot; runtime evidence continues independently'))
print(json.dumps(dict(source=source,tests=receipt['totals'],statuses=statuses,artifacts=len(files))))
