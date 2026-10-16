"""Render the implementation/acceptance report from actual release artifacts."""
import json,time,hashlib,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json

def read(name):return json.loads((BASE/name).read_text())
def main():
    release=read('regression_release/test_receipt.json');preserved=read('preservation_verification.json')
    research=read('research_release/capital_and_exit_report.json');draft=read('session_proposal_draft.json')
    launch=read('public_day_launch_receipt.json');verification=read('launch_verification.json')
    health=read('daily_observation/operator_report.json');probe=read('public_verified_probe/terminal_result.json')
    source=active_source_hash(ROOT)
    if not (release.get('passed') and release['source_hash']==release['source_hash_after']==source
        and research['source_hash']==source and preserved['passed'] and verification['process_identity_matches']):
        raise RuntimeError('VERIFIED_SOURCE_MATCHING_RELEASE_AND_PROCESS_REQUIRED')
    acceptance=[
        ('Architecture map and gap analysis','PASS','architecture_audit.md; baseline recorded before new code'),
        ('Runtime market discovery','PASS','Ten par markets captured; bounded crypto watchlist BTC/ETH/HYPE'),
        ('LONG/SHORT/NO_TRADE explanation','PASS','Unchanged frozen brain, complete UTC bars, isolated HTF veto, deterministic tests; no qualifying setup claimed'),
        ('1k–50k sizing and finite-book stress','PASS','120 captured market/size/direction rows, 576 policy episodes, 72 failure episodes'),
        ('Current 1000+ genuine capacity','BLOCKED','All six targets unsupported by captured baseline-route liquidity'),
        ('Actual LONG opening/closing','PASS','Original Oct15 exchange fills preserved; one execution cycle, not strategy validation'),
        ('Actual SHORT opening/closing','NOT YET TESTED','Ephemeral SDK fixtures pass; no genuine SELL-open/BUY-close certificate'),
        ('Six isolated exit policies','PASS','Prespecified research only; risk exits allow losses, failure exposure retained'),
        ('Native protective exits','BLOCKED','No genuine account acceptance/trigger/cleanup proof'),
        ('Two-cycle daily state coordination','PASS','Offline durable lifecycle only; unknown/partial/restart barriers tested'),
        ('Actual authorized multi-trade session','BLOCKED','No fresh exact acceptance or signer bridge; production PAPER/false retained'),
        ('Risk/expiry/source/persistence checks','PASS','109 focused checks plus preserved baseline full suite'),
        ('Full source-bound regression','PASS',f"{release['totals']['tests']} tests; no failures/errors/skips; matching XML/source"),
        ('Bounded public observer launch','PASS','Matched live PID/command/output/source and fresh exchange observations'),
        ('Full-day completion','NOT YET TESTED','Day still in progress; 23:57 IST deadline, terminal audit and quiet supervisor'),
        ('Actual fee/funding accounting','PASS','Two original actual fills, reported fees/funding, repeated authoritative flat reads'),
        ('Public competition-rule review','PASS','official_rules.md with current primary sources'),
        ('Team-specific organizer whitelist/reset','BLOCKED','No organizer-controlled team whitelist or Oct18 reset confirmation'),
        ('Terminal safety of public probe','PASS','Clean deadline shutdown, two authoritative flat/zero-order reads, SQLite ok'),
        ('Terminal safety of full-day observer','NOT YET TESTED','end_of_day_audit.json/.md generated after the child stops')]
    changed=[
        ('algo-trading-bot/exchange/capital_allocation.py','allocate: Decimal lot-down sizing, risk/margin/exposure/cumulative limits, both best levels, runtime maxTradeSz and finite L2'),
        ('algo-trading-bot/exchange/quant_observation.py','explain_market/completed_higher_timeframe: frozen signals, UTC 15m confirmation and explicit rejection explanations'),
        ('algo-trading-bot/exchange/bounded_daily_session.py','DailyMandate/DailyLifecycle: exact bounded contract and non-signing durable state machine; offline fixture cycles only'),
        ('algo-trading-bot/exchange/public_quant_operator.py','observe: serialized public WS/REST, allowlisted cancellable info transport, report, source/deadline guard, terminal reconciliation'),
        ('algo-trading-bot/research_lab/quant_exits.py','episode/decision: six prespecified isolated exits and finite-depth accounting; no production strategy imports or promotion'),
        ('algo-trading-bot/research_lab/quant_campaign.py','run_campaign: 1k–50k matrix, eight synthetic regimes and preserved actual L2 capacity inspection'),
        ('algo-trading-bot/test_quant_engine_v2.py','109 focused checks, including actual central SDK wire with ephemeral fixtures and no HTTP exchange submission'),
        ('scripts/run_quant_engine.py','Research and public observe commands; no execution command')]
    result=dict(created_ms=time.time_ns()//1000000,source_hash=source,regression=release,
        preservation_passed=preserved['passed'],new_source_files=[x[0] for x in changed],existing_source_modified=0,
        acceptance=[dict(requirement=a,status=b,evidence=c) for a,b,c in acceptance],
        actual_genuine_unattended_notional='0',actual_prior_net='0.050512',
        original_buy_order='62755970305',original_buy_fill='800659111758533',
        original_sell_order='62805581662',original_sell_fill='260274449763192',
        actual_new_orders_submitted=0,actual_new_signatures_created=0,
        observation_launch=launch,launch_verification=verification,
        full_day_completion='IN_PROGRESS_NOT_CLAIMED_COMPLETE',
        research=dict(policy_episodes=576,failure_episodes=72,synthetic_closed=540,synthetic_recovery_required=36,
            intended_stop_overrun_scenarios=210,historical_l2_frames=449,historical_rows=23593,
            historical_targets_supported=0,strategy_edge_established=False),
        no_trading_acceptance_requested='Prerequisites are not met; the draft is blocked and cannot activate orders')
    atomic_json(BASE/'release_summary.json',result)
    when=datetime.fromtimestamp(health['updated_ms']/1000,ZoneInfo('Asia/Calcutta')).isoformat()
    lines=[
        '# Anchorium V2 engineering release — 16 October 2026','',
        '**Outcome:** The preserved engine now has an isolated capital/exit research layer, a durable non-signing daily contract and a running public-only operator. Larger autonomous trading remains BLOCKED. No new actual order, signature, account administration or authorization acceptance was created.','',
        '## A. What already worked','',
        'Reused the official SDK/central guards, exact reduce-only closing path, actual account reconciliation, nonce/ownership controls, dynamic par metadata, public WS/REST recovery, freeze checks, finite precision, startup checkpoints and original trade proof. All 243 existing source files and all recorded policies/proofs remain byte-identical. The original UNKNOWN row remains UNKNOWN; only its original immutable nontransmission certificate supplies the isolated effective view. The prior 2385-test receipt is preserved. The existing general LIVE builder remains locked by PAPER/false.','',
        'The original position is closed: BUY 62755970305 / fill 800659111758533; SELL 62805581662 / fill 260274449763192. The October 15 trading heartbeat remains PAUSED. No consumed or expired mandate is reused.','',
        '## B. What was newly built','',
        '| Added source file | Responsibility |','|---|---|']
    lines += [f'| `{p}` | {description} |' for p,description in changed]
    lines += ['',
        'New research stop/target/trailing/holding parameters are prespecified experiments only. The production brain, strategy methods, geometry, state and policy files are untouched. The unchanged scanner keeps 0.40% ATR, 15 bps spread, 300-bar warmup, Top-3, one global position, two daily setups and the existing stricter 1% daily-loss ceiling. The requested 2% daily loss is not an approved relaxation.','',
        '## C. What was tested','',
        f"Full regression: **{release['totals']['tests']} passed, 0 failures, 0 errors, 0 skipped**. This is the preserved 2385 baseline plus 109 focused tests. Phase-0 and strategy-freeze checks passed before and after. Source: `{source}`. XML SHA-256: `{release['xml_sha256']}`. Receipt: `regression_release/test_receipt.json`.",
        'Focused evidence covers all six sizes/directions; both-side liquidity/risk/lot limits; bullish, bearish and NO_TRADE classification; completed 15m buckets; stale/gapped/future data; changing fees/funding; loss-making risk exits; gap loss; rejected/partial/unknown execution; duplicate candidates; exact partial fill identities; immutable checkpoint hashes; corrupted checkpoints; restart/expiry/source/drawdown/attempt limits; observation transport lockout; metadata-restart serialization; public shutdown. Existing SDK/protection/recovery/rate/nonce/certificate tests remain in the full suite.',
        'The public probe genuinely connected WS and public REST, completed two terminal flat/zero-order readbacks and stopped cleanly with SQLite integrity ok. An earlier network-sandbox probe and a startup-race probe are preserved as failed diagnostics. An intermediate regression was intentionally interrupted for the partial-exit durability fix and is not a passing release receipt.',
        'The final campaign contains **576 synthetic policy episodes** (six sizes × two directions × six policies × eight regimes), plus **72 separate failure cases**. Of the policy scenarios, 540 close in simulation and 36 retain RECOVERY_REQUIRED exposure after liquidity deterioration. 210 scenarios exceed the simple intended-stop loss amount after costs/gaps; these are disclosed failures of a guaranteed-loss interpretation, not omitted observations. Synthetic results are not an investable portfolio or exchange P&L. Full records include entry/exit slippage, actual simulated fees, prospective funding, MAE/MFE units, margin, drawdown availability and residual exposure.',
        'Preserved actual Oct15 L2 data: 23,593 rows, 449 fresh minute-spaced book frames checked by SHA-256. None supports any requested 1000–50000 size under the preserved participation route. This is historical capacity evidence, not a strategy backtest. Sharpe, Sortino and calibrated confidence remain unavailable; a representative causal multi-regime dataset and chronological walk-forward evaluation are still required. No parameter is selected or promoted from synthetic performance.','',
        '## D. How much capital is genuinely safe to attempt','',
        '**Currently qualified unattended genuine notional: 0 TEST USDPR.** This reflects missing protective-exit qualification, unavailable validated setup, lack of exact session authority and unsupported 1000+ liquidity. A large account balance does not resolve those blockers.',
        'The first ten-market snapshot had a maximum displayed both-side route bound of about 98.45 TEST USDPR on BTC. The later public probe showed crypto caps around 49 TEST USDPR. These are timestamped liquidity bounds, not safe order recommendations or guaranteed closing capacity. BRENT/GOLD snapshot caps were even below the ordinary minimum order value.',
        '| Latest public crypto observation | LONG liquidity cap | SHORT liquidity cap |','|---|---:|---:|']
    for symbol,caps in sorted(health.get('liquidity',{}).items()):lines.append(f"| {symbol} | {caps['long']} | {caps['short']} |")
    lines += ['',
        f'As of {when}. Size is rounded down to runtime lots and bounded by approved bankroll, free collateral from activeAssetData, runtime maximum trade size, stop distance, costs, margin, loss/exposure/cumulative budgets, 10% of BOTH best levels and tighter L2. No splitting or aggregate-depth bypass is used.',
        'The account reported about 1,000,000.050512 TEST USDPR. Free collateral was separately observed through activeAssetData. No amount of that balance is a currently approved strategy bankroll. Fees in stress research use the disclosed conservative 0.27% bound when a current deployer-scale query is unavailable; actual past P&L uses reported fill fees, not that bound.','',
        '## E. LONG and SHORT readiness','',
        'LONG has one genuine, fully closed practice execution cycle. It has not established profitable strategy performance, verified native protection or a full-day autonomous cycle. SHORT SELL-open / reduce-only BUY-close passes the existing central guards and official SDK in ephemeral fixtures; no genuine SHORT cycle has been performed. Actual SHORT remains disabled. No offline fixture can satisfy either live prerequisite.','',
        '## F. Protective exits','',
        'Existing native catastrophic protection and qualification managers were preserved and exercised offline. Genuine account acceptance, trigger semantics, correct residual sizing, real protective closing records and post-close cleanup remain unverified. Larger unattended entry is blocked. Partial profit-taking is research only; no production partial-reduction or protection-resize authority is introduced.',
        'Protocol documentation supports native TP/SL but does not establish this account qualification. Trigger and executable prices differ, and neither stop-market nor stop-limit guarantees its intended fill. [Hyperliquid TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)','',
        '## G. Exact session authorization needed','',
        f"The blocked draft identity is `{draft['draft_identity']}` in `session_proposal_draft.json`. It is **NOT FOR ACCEPTANCE**, and no acceptance file was created. It records this Mac, the registered team/API identities, this exact source and an October 16 23:57 IST expiry.",
        'After protective qualification, representative forward evidence, adequate genuine liquidity and an appropriate signer integration exist, prepare a fresh executable contract: proposed bankroll 20,000; development starting/maximum notional 1,000 only when supportable; maximum exposure 1,000; cumulative entry allocation 2,000; at most two entry attempts; one position; 1x CROSS; per-trade intended risk ≤100 (0.5%); daily stop ≤200 (1%); preserved 10% best-level limits and 5 bps slippage. These numbers are proposals, not orders or approved risk. Current executable starting notional stays zero.',
        'Initial scope would be BTC/ETH/HYPE LONG only after per-market qualification. SHORT needs its own genuine qualification and inclusion in the new exact contract. Acceptance must bind the refreshed source, host, markets, directions, quantity/notional/price limits, loss-making risk exits, protection/cleanup actions, attempt counts and same-day deadline. Source change, expiry, drawdown or protection/account/nonce uncertainty revokes new entry authority. Uncertain orders require reconciliation, not another submission. No new trading approval is requested for an impossible or unqualified session.','',
        '## H. What is running','',
        f"Public observation worker PID **{launch['worker_pid']}**, supervisor PID {launch['supervisor_pid']}, process-bound caffeinate PID {launch['caffeinate_pid']}. PID command/output/source identity was independently checked. Deadline: **23:57 IST, October 16**. Scan interval: 300 seconds; heartbeat: 30 seconds. Source/deadline guard is independent of scan rate waits. No execution command or signer exists in this operator.",
        f"Last captured status: `{health['status']}` at {when}; WS connected/reconciled: {health.get('stream_connected')} / {health.get('stream_reconciled')}. Feed status: {health.get('feed_mode')}. Fresh account positions: {len(health.get('account',{}).get('positions',[]))}; open orders: {len(health.get('account',{}).get('open_orders',[]))}.",
        'Read `daily_observation/operator_report.md` and its JSON/receipt tape for current state. `public_day_launch_receipt.json` records exact process arguments. The observer halts on source change, unexpected exposure, account uncertainty, deadline or interruption; it never restarts or promotes itself. The supervisor writes `end_of_day_audit.json/.md` after termination. Full-day completion is still pending at this report time.',
        'Quiet supervision reports meaningful health/account/source/persistence failures and completion, then pauses. This is separate from the paused October 15 trading monitor. Local supervision requires the Mac, application, power and internet; an outage can interrupt observation and notification. [Scheduled-task operating guidance](https://developers.openai.com/training/walkthroughs/scheduled-tasks)','',
        '## I. Actual profitability','',
        'Original genuine gross closed P&L: +0.079400 TEST USDPR. Actual entry fee 0.014672 + exit fee 0.014743 = 0.029415. Actual funding +0.000527. **Actual net = +0.050512 TEST USDPR.** Original BUY/SELL proofs and both flat readbacks are preserved. This is one past practice round trip, not a predicted strategy return. This engineering task has submitted zero new exchange orders and created zero actual-wallet signatures. Synthetic wins/losses are in a separate report and do not change actual account P&L.','',
        '## J. What remains before scored deployment','',
        'Genuine independently approved native-protection and SHORT qualifications; representative multi-regime causal forward/OOS evidence; supportable entry/exit depth; controlled same-account session integration with fresh explicit authorization; independently reconciled multi-cycle evidence; and organizer confirmation of team-specific eligibility and any reset announcement remain outstanding.',
        'Public practice ends October 18; scoring is October 19–November 6, with a November 6 report/code deadline. Exact cutover timezone and an October 18 capital reset are not verified. [Official schedule](https://perpetual-alpha26.github.io/schedule) Public ranking currently requires at least one scored-phase fill, algorithmic entries and an eligible organizer account; this practice fill does not satisfy the scored requirement. [Official rules](https://perpetual-alpha26.github.io/about) See `official_rules.md` for the source-limited verification and unresolved organizer questions.','',
        '## Acceptance evidence','',
        '| Requirement | Status | Evidence / practical limit |','|---|---|---|']
    lines += [f'| {a} | **{b}** | {c} |' for a,b,c in acceptance]
    lines += ['',
        'Primary artifacts: `architecture_audit.md`, `baseline_preservation.json`, `preservation_verification.json`, `research_release/capital_stress_report.md`, `research_release/capital_and_exit_report.json`, `regression_release/test_receipt.json`, `official_rules.md`, `session_proposal_draft.json`, `launch_verification.json`, and the running operator report. Existing unrelated `.gitattributes` working-tree edits were left untouched.']
    (BASE/'implementation_report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(report=str(BASE/'implementation_report.md'),source_hash=source,
        tests=release['totals']['tests'],signing_authority='NONE',worker_pid=launch['worker_pid'])))

if __name__=='__main__':main()
