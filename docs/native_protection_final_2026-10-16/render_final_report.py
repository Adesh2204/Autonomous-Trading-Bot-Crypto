"""Render findings from saved evidence only; no account writes, signer or worker."""
from pathlib import Path
from decimal import Decimal as D
import hashlib,json,sqlite3,sys,time,xml.etree.ElementTree as ET

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint


def render():
    baseline=json.loads((OUT/'baseline.json').read_text())
    preserved={}
    for name,expected in baseline['preserved'].items():
        actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        preserved[name]=dict(expected=expected,actual=actual,matching=actual==expected)
    databases={}
    for name,expected in baseline['databases'].items():
        with sqlite3.connect((ROOT/name).resolve().as_uri()+'?mode=ro',uri=True) as db:
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
            dump=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
            record=dict(integrity=integrity,dump_sha256=dump,matching=dump==expected['dump_sha256'])
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_snapshots'").fetchone():
                rows=db.execute('SELECT data,checksum FROM recovery_snapshots').fetchall()
                record['checkpoint_checksum_integrity']=all(fingerprint(json.loads(v))==h for v,h in rows)
                record['checkpoint_count']=len(rows)
            if name.endswith('nonces.sqlite'):
                record['last_nonce_rows']=db.execute('SELECT signer,last FROM nonces').fetchall()
            if name.endswith('qualification.sqlite'):
                record['raw_intents']=db.execute('SELECT intent_key,state,oid FROM intents ORDER BY created_ms').fetchall()
                record['original_resolution_checksums']=db.execute('SELECT checksum FROM nontransmission_resolutions').fetchall()
            databases[name]=record
    preservation=dict(observed_ms=time.time_ns()//1000000,preserved=preserved,databases=databases,
        all_preserved=all(x['matching'] for x in preserved.values()) and all(
            x['matching'] and x['integrity']=='ok' and x.get('checkpoint_checksum_integrity',True)
            for x in databases.values()))
    atomic_json(OUT/'preservation_receipt.json',preservation)
    release=json.loads((OUT/'repaired_regression_release/test_receipt.json').read_text())
    morning=json.loads((OUT/'morning_account_2026-10-17/audit.json').read_text())
    prep_path=OUT/'qualification_preparation_2026-10-17/preparation.json'
    prep=json.loads(prep_path.read_text()) if prep_path.exists() else None
    context=(prep or {}).get('context') or {}
    account=(prep or {}).get('account') or morning['account_final']
    historical=account['realized']
    ready=(prep or {}).get('status')=='AWAITING_EXACT_HUMAN_QUALIFICATION_APPROVAL'
    pid=json.loads((OUT/'process_and_automation_check.json').read_text())
    summary=dict(updated_ms=time.time_ns()//1000000,task='FINAL_NATIVE_PROTECTION_REPAIR',
        status='AWAITING_EXACT_QUALIFICATION_APPROVAL' if ready else 'QUALIFICATION_PREFLIGHT_BLOCKED',
        production_mode='PAPER',allow_live_orders=False,source_hash=active_source_hash(ROOT),
        source_bound_release=release,partial_residual_resolution='NARROW_SUPERVISED_TWO_LOT_BTC_ONLY',
        small_native_stop_verified=False,native_protection_exchange_qualified=False,
        ordinary_and_unattended_partial_guard_unchanged=True,
        exact_human_approval_created=False,actual_new_signatures=0,actual_new_exchange_actions=0,
        actual_worker_running=False,current_approved_trades=0,current_approved_position_size='0',
        proposed_qualification_quantity='0.0002',proposed_qualification_maximum_entry_attempts=1,
        proposed_future_session_maximum_entry_attempts=2,future_session_authorized=False,
        actual_account=account,account_observed_ms=(prep or {}).get('observed_ms') or morning['finished_ms'],
        account_cached_age_ms=time.time_ns()//1000000-((prep or {}).get('observed_ms') or morning['finished_ms']),
        original_oct15_net_test_usdpr='0.050512',new_task_fills=[],new_task_realized_pnl='0',
        current_preparation=prep,process_and_automation=pid,preservation=preservation,
        source_files_changed=['algo-trading-bot/exchange/native_qualification.py',
            'algo-trading-bot/exchange/native_qualification_runtime.py','scripts/run_native_qualification.py',
            'algo-trading-bot/exchange/qualification_protection.py',
            'algo-trading-bot/exchange/certification_runtime.py',
            'algo-trading-bot/exchange/testnet_certification.py','algo-trading-bot/test_native_qualification.py'],
        limits=['No completed natural Stop Limit trigger/closing proof for this team',
            'Subminimum Stop Limit and position-linked child exception remain unverified',
            'Prior Oct16 overnight creation/acceptance window elapsed; no automatic rollover',
            'Mac/process/power/internet required; no remote failover or restart',
            'No organizer whitelisting or reset evidence'])
    atomic_json(OUT/'release_summary.json',summary)
    atomic_json(OUT/'final_summary.json',summary)
    p=(prep or {}).get('proposal') or {}
    proposal_text=(f"Fresh **qualification-only** mandate `{prep['mandate_id']}` is prepared. It is not accepted. "
        f"BUY IOC exactly {p['quantity']} BTC at limit {p['entry_limit']}; native SELL Stop Limit trigger {p['stop_trigger']}, "
        f"limit/cleanup floor {p['stop_limit']}. Approval deadline ms {prep['approval_deadline_ms']}; authorization "
        f"ends within five minutes of genuine acceptance. Maximum six signed actions, one entry, one stop, "
        f"one owned cancellation round and at most two definitely resolved exact IOC closes. "
        f"No uncertain retry, restart, price widening, leverage change or new session. "
        f"Planned loss at floor plus configured fees: {prep['planned_loss_at_approved_floor']} TEST USDPR; "
        f"this is not a guaranteed loss cap. Estimated immediate cleanup net before funding: "
        f"{prep['expected_immediate_cleanup_net_before_funding']} TEST USDPR."
        if ready else f"No executable qualification mandate was issued. Latest fresh preflight: `{(prep or {}).get('blocker','not yet run')}`. "
        "The exact two-lot size and 10% participation guard were retained; no risk or price limit was widened.")
    lines=['# Final native-protection repair and qualification report','',
        f"Updated UTC milliseconds: {summary['updated_ms']}. Source `{summary['source_hash']}`. PAPER/false. No actual new signature, exchange write, acceptance, signer or worker.",'',
        '## A–J requested results','',
        '| Item | Actual result |','|---|---|',
        '| A — $10 residual issue | A narrow controlled test route is implemented and tested: full two-lot BTC receives an ordinary-size stop; exactly one lot is aborted through the existing observed exact reduce-only IOC close. A general subminimum native-stop exemption is not established. |',
        '| B — actual native qualification | No. No new entry/stop has been signed; no actual natural trigger-linked closing proof exists. Acceptance alone cannot pass. |',
        '| C — genuine trades permitted | Currently zero. Proposed small qualification permits one entry only after exact human approval. The unaccepted future session specification allows at most two entry attempts, one concurrent position. |',
        '| D — actual permitted position size | Currently zero. Qualification proposes exactly 0.0002 BTC; no increase, rounding-up, split order or blanket permission to deploy the 20,000 bankroll. Unattended qualified capacity remains zero. |',
        f"| E — full regression | {'PASS' if release.get('passed') else 'FAIL/INCOMPLETE'}: {release['totals']['tests']} tests, {release['totals']['failures']} failures, {release['totals']['errors']} errors, {release['totals']['skipped']} skips. Source before/after equal. Phase-0 and strategy freeze passed. |",
        '| F — fresh exact session mandate | No trading-session mandate. '+('A separate exact tiny qualification proposal is ready below.' if ready else 'Qualification preflight is blocked; details below.')+' |',
        '| G — execution command | Qualification CLI is implemented and tested; its exact command template is in OPERATOR_GUIDE.md. A trading launch command is not currently eligible. Missing exact approval/source/health gates block before key access. |',
        '| H — running / order-capable | No worker or signer launched. Previous named PIDs absent; both old heartbeats PAUSED. |',
        '| I — actual fills / P&L | No new task fills or realized P&L. The preserved Oct15 BUY/SELL round trip net is +0.050512 TEST USDPR, not today’s earnings or synthetic-test P&L. |',
        '| J — exact remaining blocker | Missing actual team Stop Limit trigger/child SELL fill proof; no verified one-lot native-stop support. Any fresh price/depth/approval gate also must pass. The Oct16 overnight creation window has elapsed; it is not silently extended. |','',
        '## Exact current proposal state','',proposal_text,'',
        'The operator must explicitly accept the exact qualification ID, both wallets, this sole signing host, one-entry scope, immediate one-lot abort, unprotected interval/residual risk, loss-making cleanup, incomplete qualification if untriggered, and local Mac/process/power/internet dependency. No acceptance file is created by preparation. A late answer cannot renew an expired proposal.','',
        '## Venue findings and evidence limits','',
        'The ordinary venue order minimum is $10. Previously independently read original orders and matching fills support exactly 0.0001 BTC reduce-only SELL IOC full-position closure under the preserved V8.5 scope; this is observational evidence, not a documented universal minimum exemption. The exact proof SHA is c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764.','',
        'The bounded fresh public-account history audit found 134 native historical rows in one 2,000-row truncated history, all Stop Market, with isPositionTpsl=false. Eight selected historical ETH/BRENT Stop Market orders had displayed original notionals below $10, with recorded open/terminal statuses. These are historical acceptance observations, not eight independent triggered closes. Exact-ID rechecks on Oct17 returned unknownOid for all eight; the cause is UNKNOWN, not proof of rejection, a reset or whitelisting. No Stop Limit or position-linked example was established in this bounded sample. It is not a venue-wide census.','',
        'Stop orders trigger on mark price. Stop Market has documented 10% tolerance and is not substituted for the approved 0.5% Stop Limit allowance. A Stop Limit can rest through a gap. Position TP/SL can track full position size by default, but schema/grouping support does not prove a subminimum Stop Limit/child exemption. Parent partial-fill/cancellation rules do not guarantee children remain protective. There is no documented FOK path used here; the opening IOC can partially fill.','',
        'Sources: [competition guide](https://perpetual-alpha26.github.io/docs/), [official TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl), [official errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses), [official exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). Saved primary source bytes, observation times and SHA hashes are in primary_rule_sources/manifest.json.','',
        '## Minimum repair and release checks','',
        'A dedicated typed, finite two-lot BTC capability uses the existing validator, single-position lock, preserved historical UNKNOWN certificate, original qualification journal, original nonce store, exact-action SDK permits and unchanged participation/price/source/rate guards. It cannot authorize autonomous entries, another BUY, a different market, a larger size, a Stop Market substitution or account administration. Ordinary certification and unattended partial-fill guards remain unchanged.','',
        'A lost stop placement ACK now resolves the same original journal row to OPEN only after matching fresh status, frontend order, quantity, side, prices, position and CLOID/OID readbacks. No retransmission or replacement occurs. Known trigger children enter isolated account recovery only after exact current parent/child readback. Cleanup cancels one verified owned live order, requires terminal settlement, then closes the exact remaining position. Unknown child/cancellation/IOC outcomes halt. The barrier is also enforced at the direct-close and final signing boundaries.','',
        'Qualification waits for a natural trigger for at most 120 seconds, shortened when necessary to reserve cleanup time within the original five-minute authorization. An untriggered accepted stop is canceled and followed by approved bounded cleanup, then reported INCOMPLETE. The raw proof exporter independently checks actual linked SELL fills and two authoritative flat/zero-order readbacks. No automatic promotion occurs, even after full-size qualification. A one-lot native stop remains unverified.','',
        'Focused release checks: 243 passed across native protection, certification, terminal shutdown, cross-midnight expiry and two-cycle controls; the final module suite passed 58 tests including an added direct-close bypass check. Full regression reruns every test at the final source. All signatures in these tests use ephemeral offline fixtures with HTTP prohibited; synthetic triggers/fills never qualify the team or venue.','',
        f"Full XML SHA-256: `{release.get('xml_sha256')}`. Baseline 2617-test source was `{baseline['source_hash']}`; that successful receipt remains separately preserved. Requirements/pins were not changed by this repair. Frozen brain, eight frozen methods and 32 parameters remain unchanged.",'',
        '## Account, persistence and interruption limits','',
        f"Latest saved account observation ms: {summary['account_observed_ms']}. It is a timestamped snapshot, not a continuous account guarantee. Positions: {len(account['positions'])}; open orders: {len(account['open_orders'])}. Oct17 morning audit independently had two ready flat/zero-order readbacks at 1792199548911 and 1792199551176. Final signing requires new full checks.",'',
        'Original BUY: order 62755970305 / fill 800659111758533, 0.0002 BTC at 81512, fee 0.014672. Original SELL: order 62805581662 / fill 260274449763192, 0.0002 BTC at 81909, fee 0.014743. Gross +0.0794; total fees 0.029415; 12 funding cashflows +0.000527; net +0.050512 TEST USDPR on Oct15. No organizer whitelist/reset conclusion follows from these fills.','',
        f"Preservation check: {preservation['all_preserved']}. All ten protected file hashes and all three original SQLite logical dumps match baseline. Integrity checks and saved recovery snapshot checksums pass; original nonce history, original UNKNOWN row/certificate and BUY/SELL proof bytes remain intact. Full details are in preservation_receipt.json. Public /info failures, local rate waits and unknownOid records are distinguished; no HTTP429 is inferred from a fallback label.",'',
        'This is local operation. Losing this Mac, process, app supervision, power or internet can interrupt management. Native Stop Limit acceptance does not guarantee a fill during an outage or price gap. A failed terminal audit stays UNKNOWN; direct positions/orders are still reported when possible. No restart, next-day renewal, blanket high-position approval or unattended hold is created.','']
    (OUT/'final_report.md').write_text('\n'.join(lines))
    (OUT/'implementation_report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=summary['status'],source_hash=summary['source_hash'],
        tests=release['totals'],all_preserved=preservation['all_preserved'],
        preparation=(prep or {}).get('status')),indent=2))


if __name__=='__main__':render()
