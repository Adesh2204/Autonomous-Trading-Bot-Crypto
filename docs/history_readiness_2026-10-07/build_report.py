"""Build an evidence-bound report; reads saved checks and never contacts an exchange."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from research_intelligence.common import source_identity
from session_results import source_version
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def read(relative):
    return json.loads((OUT / relative).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def link(label, relative):
    return f'[{label}](<{ROOT / relative}>)'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def main():
    history = read('history_verified/history_verification.json')
    validation = read('history_verified/csv_validation.json')
    analysis = read('history_verified/price_analysis.json')
    account = read('account_check.json')
    tests = read('test_receipt.json')
    paper = read('public_paper_smoke/report.json')
    manifest = read('public_paper_smoke/results/session_manifest.json')
    safety = require_paper_migration()
    freeze = verify_strategy_freeze()
    active_hash = active_source_hash(ROOT)
    assert active_hash == tests['source_hash_before'] == tests['source_hash_after'] == account['active_source_hash']
    assert tests['exit_code'] == 0 and tests['source_unchanged']
    assert tests['totals'] == dict(tests=1249, failures=0, errors=0, skipped=0)
    assert sha(OUT / 'regression.xml') == tests['xml_sha256']
    research_identity = source_identity()
    assert research_identity['source_hash'] == history['source']['source_hash']
    paper_paths = [p for p in (ROOT / 'algo-trading-bot').rglob('*.py') if '__pycache__' not in p.parts]
    paper_paths += list((ROOT / 'scripts').glob('*.py'))
    assert source_version(paper_paths) == manifest['working_source_hash']
    initial = read('history/csv_validation.json')
    initial_hashes = {m['market']: m['sha256'] for m in initial['markets']}
    for m in validation['markets']:
        assert sha(m['path']) == m['sha256'] == initial_hashes[m['market']]
        assert subprocess.run(['git', 'check-ignore', '-q', m['path']], cwd=ROOT).returncode == 0
    features = Path(history['features_path'])
    assert subprocess.run(['git', 'check-ignore', '-q', str(features)], cwd=ROOT).returncode == 0
    assert not subprocess.check_output(['git', 'ls-files', '--', 'algo-trading-bot/data/history',
                                       'algo-trading-bot/data/organizer-history-research'], cwd=ROOT)
    assert safety['EXECUTION_MODE'] == 'PAPER' and not safety['ALLOW_LIVE_ORDERS']
    assert account['exchange_orders_submitted'] == paper['exchange_orders_submitted'] == 0
    assert not account['signer_constructed'] and not account['manual_wallet_verification_performed']
    assert not account['controlled_execution_certified'] and not account['protection_policy']['enabled']

    # Verify features without exporting their underlying data into this report.
    feature_count = 0
    null_fields = ('spread', 'depth', 'slippage', 'fills', 'fee', 'funding', 'mark', 'oracle', 'label', 'production_signal')
    with features.open() as stream:
        for line in stream:
            row = json.loads(line)
            assert row['decision_ms'] < analysis['shared_utc_boundaries']['holdout_start_ms']
            assert row['decision_ms'] == row['candle_open_ms'] + 3_600_000
            assert all(row[field] is None for field in null_fields)
            assert not row['execution_capability'] and not row['ml_scoring_ready']
            feature_count += 1
    assert feature_count == history['feature_rows'] == analysis['feature_rows'] == 39821

    cases = list(ET.parse(OUT / 'regression.xml').getroot().iter('testcase'))
    history_cases = [c for c in cases if c.attrib.get('classname', '').endswith('test_organizer_history')]
    assert len(history_cases) == 35 and all(not list(c) or all(n.tag not in {'failure', 'error', 'skipped'} for n in c) for c in history_cases)
    case_names = {c.attrib['name'].split('[')[0] for c in cases}
    recovery_tests = {
        'Cancel': 'test_cancel_by_cloid_checks_team_order_and_exact_sdk_action',
        'Partial fill': 'test_close_partial_fill_rechecks_authoritative_position_retains_exit_intent',
        'WebSocket account barrier': 'test_websocket_disconnect_reconnect_team_subscriptions_rest_barrier',
        'Restart': 'test_restart_restores_known_partial_position_and_stop_target_cooldown',
        'Ambiguous protection / duplicates': 'test_uncertain_protection_never_duplicates_after_restart',
        'Existing position': 'test_restart_open_position_cannot_assume_flat_or_invent_stop',
    }
    assert all(name in case_names for name in recovery_tests.values())

    now = datetime.now(timezone.utc)
    observed = account['observed_at_ist']
    expiry = datetime.fromtimestamp(account['account_verification']['agent_expiry_ms'] / 1000, ZoneInfo('Asia/Kolkata')).isoformat()
    insufficient = [d['symbol'] for d in paper['diagnostics'] if 'INSUFFICIENT_COMPLETED_HISTORY' in d['reasons']]
    assert len(insufficient) == 9
    flags = dict(HISTORY_DATA_READY='NO', RESEARCH_DATA_READY='NO', LIVE_DATA_ISOLATED='YES',
                 STRATEGY_FREEZE='PASS', ACCOUNT_READY='YES', API_WALLET_READY='YES',
                 PAPER_READY='YES', CONTROLLED_LIVE_TEST='NOT RUN', LONG_CERTIFIED='NO',
                 SHORT_CERTIFIED='NO', RESTART_CERTIFIED='NO', RECONNECT_CERTIFIED='NO',
                 PRACTICE_READY='NO', LIVE_READY='NO', MARKET_DATA_READY='NO',
                 CSV_STRUCTURE_VALID='YES', PRICE_FEATURE_RESEARCH_PREPARED='YES')
    blockers = [
        'Official dataset origin unverified; original ZIP and organizer download/announcement link absent.',
        'Nine markets lack the required completed public one-minute history in this snapshot.',
        'Independent catastrophic protection is disabled and its distance/slippage approval is absent.',
        'Observed exchange leverage is 20x cross (10x HYPE), while the bot policy remains 1x cross.',
        'Actual API signer and persistent nonce ownership/health have not been verified.',
        'Human wallet verification and explicit activation after all gates pass are not recorded.',
        'Real LONG/SHORT execution, protection, accounting and funded-account recovery certification were not performed.',
    ]
    readiness = dict(
        report_created_at_utc=now.isoformat(), flags=flags,
        flag_scope=dict(HISTORY_DATA_READY='Verified official provenance, not just syntactically valid CSVs.',
                        RESEARCH_DATA_READY='Validated strategy/ML experiment inputs; price features alone do not establish this.',
                        ACCOUNT_READY='Timestamped real read-only technical check; not current signing authorization.',
                        API_WALLET_READY='Timestamped public agent approval and expiry only; private signer not tested.',
                        PAPER_READY='Guarded public-data smoke completed; feed/performance readiness is not certified.',
                        RESTART_CERTIFIED='Actual funded-account execution recovery; offline/PAPER results are separate.',
                        RECONNECT_CERTIFIED='Actual account/execution recovery; public market WebSocket recovery is separate.'),
        execution_mode='PAPER', allow_live_orders=False, exchange_orders_submitted=0,
        account_administration_actions=0, signer_constructed=False,
        controlled_live_test='NOT RUN — NOT LIVE VERIFIED',
        long_certification='NOT RUN — NOT LIVE VERIFIED', short_certification='NOT RUN — NOT LIVE VERIFIED',
        git_commit=research_identity['commit'], git_dirty=research_identity['dirty'],
        active_source_hash=active_hash, account_and_suite_active_hash_match=True,
        history_source_hash=research_identity['source_hash'], history_source_scope='research source_identity()',
        paper_manifest_source_hash=manifest['working_source_hash'], paper_source_scope='session_results.source_version()',
        research_and_paper_current_scoped_hashes_match=True,
        tests=tests['totals'], strategy_freeze=freeze, phase0=tests['checks']['phase0']['result'],
        history_directory=validation['directory'], discovered_files=validation['discovered'],
        original_archive_status='NOT_AVAILABLE', official_provenance_verified=False,
        csv_rows=validation['total_rows'], raw_csv_hashes_unchanged=True,
        csv_sha256={m['market']: m['sha256'] for m in validation['markets']},
        feature_rows=feature_count, feature_sha256=sha(features), feature_path=str(features),
        research_utc_boundaries=analysis['shared_utc_boundaries'], holdout_prices_feature_evaluated=False,
        research_state=dict(SESSION_ANCHOR_VALIDATED=False, ML_DATA_READY=False, ML_MODEL_VALIDATED=False,
                            HOLDOUT_COMPLETE=False, PROMOTION_RECOMMENDED=False, PRODUCTION_CHANGED=False),
        account_observed_at_ist=observed, team_wallet=account['team_address'],
        api_wallet=account['api_wallet_address'], api_name='anchorium-bot-1', api_expiry_ist=expiry,
        collateral=account['reported_equity']['collateral_balance'], account_mode=account['account_mode'],
        positions=len(account['positions']), open_orders=len(account['open_orders']),
        frontend_orders=len(account['frontend_open_orders']),
        configured_policy_leverage=1,
        observed_leverage={s: v['leverage'] for s, v in account['active_asset_data'].items()},
        protection=account['protection_policy'], clock=account['clock'], rate_limit=account['user_rate_limit'],
        account_reconciliation_scope='Reported account events from 2026-10-05 UTC to the saved observation; no lifetime claim.',
        paper_observed_at_utc=paper['observed_at_utc'], paper_result=paper['scan_status'],
        paper_orders=paper['local_orders'], paper_fills=paper['local_fills'],
        paper_rejections={d['symbol']: d['reasons'] for d in paper['diagnostics']},
        failure_tests={kind: dict(scope='OFFLINE_TESTED', real_exchange_status='NOT RUN — NOT LIVE VERIFIED',
                                  passed_test=name) for kind, name in recovery_tests.items()},
        blockers=blockers,
        evidence_sha256={str(p.relative_to(ROOT)): sha(p) for p in [OUT / 'test_receipt.json',
                          OUT / 'regression.xml', OUT / 'account_check.json',
                          OUT / 'history_verified/history_verification.json',
                          OUT / 'history_verified/csv_validation.json', OUT / 'history_verified/price_analysis.json',
                          OUT / 'public_paper_smoke/report.json', OUT / 'certification_plan.md']})

    sections = []
    def section(title, body):
        sections.append('## ' + title + '\n\n' + body.strip() + '\n')
    introduction = f'''# Team Anchorium — history integration and practice readiness

Report prepared {now.astimezone(ZoneInfo('Asia/Kolkata')).isoformat()}.

**The historical research integration is implemented and tested. The account is funded and unified according to real read-only queries. Actual funded practice is not yet certified or authorized.**

All ten local CSVs passed structural validation: **49,831 hourly rows**. The isolated research run prepared **39,821 price-feature rows**, with no invented execution data. The complete offline suite passed **1,249 tests, zero failures, zero errors and zero skips**. The frozen strategy and safety checks passed.

The files describe hourly mainnet reference prices. They cannot supply missing one-minute testnet candles or prove that the current strategy is profitable. Their claimed organizer origin remains unverified because no original ZIP or organizer source link was supplied. Actual LONG/SHORT tests were **NOT RUN — NOT LIVE VERIFIED**.

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

The account observations below are snapshots, not a permanent readiness certificate. No exchange order, cancellation, protective order, leverage change, transfer or account administration action was submitted during this work. No actual API signer was constructed.
'''

    section('1. History location', f'''
The existing directory is clean and appropriate, so it was kept:

{link('Historical data directory', 'algo-trading-bot/data/history')}

Exact path: `{validation['directory']}`.

It contains BTC, ETH, HYPE, SP500, EWY, EWJ, BRENT, GOLD, USDEUR and USDJPY CSVs, plus README.md. No raw file was moved, rewritten, repaired or replaced. Each CSV's SHA-256 still matches its initial validation hash.

The README labels the markets `pa:` and describes mainnet reference contracts. Research uses logical `par:` labels while preserving the distinct mainnet `source_market` and research-only source identity. This mapping does not turn the files into testnet data.

Raw CSVs and generated feature data are ignored in both repository .gitignore files. Git checks confirm that these data directories contain no tracked files. Existing secret-protection rules were retained. Small validation and readiness reports remain available for review.
''')

    section('2. Archive safety', f'''
**Original ZIP: NOT AVAILABLE. Original archive safety: NOT VERIFIED.** No archive was extracted in this task. The discovered data directory contains only the ten CSVs and README.md; it contains no unexpected executable or script file.

The new archive inspector accepts only the expected CSVs and optional README, either at the archive root or in an approved history folder. It rejects traversal paths, absolute paths, Windows-style paths, symlinks, executable files, encrypted entries, unexpected files, duplicate filenames and excessive expansion. It bounds member count, archive size and extracted size, reads text without executing it, and checks content hashes.

The extractor writes only to a new child of the dedicated history directory. It refuses existing destinations and symlink roots, verifies that archive contents did not change after inspection, and validates the extracted CSVs. Failure removes only the new output created by that call.

Those behaviors were tested with **local synthetic archives**, including malicious fixtures. That tests the implementation; it does not certify a missing organizer ZIP. See {link('archive status', 'docs/history_readiness_2026-10-07/history_verified/archive_safety.json')}.

An organizer download or announcement link is still needed to authenticate provenance. The local README alone is insufficient.
''')

    csv_rows = [(m['market'], m['rows'], m['start_timestamp'].replace('+00:00', 'Z'),
                 m['end_timestamp'].replace('+00:00', 'Z'), m['missing_rows'], m['duplicates'],
                 m['invalid_values'], m['status']) for m in validation['markets']]
    section('3. CSV validation', table(
        ['Market', 'Rows', 'First hour open, UTC', 'Last hour open, UTC', 'Missing hours', 'Duplicate times', 'Invalid rows', 'Status'], csv_rows) + f'''

**Total: {validation['total_rows']:,} rows across ten markets.** Duplicate complete rows are also zero. Each timestamp explicitly identifies UTC and an hourly boundary; timestamps increase strictly. All seven required columns are present. OHLC prices are finite and positive, highs/lows correctly contain open/close, volume is finite and nonnegative, and trade counts are nonnegative integers.

“Missing hours = 0” covers the interval between each file's first and last timestamp. It does not assert history before listing, beyond the last row, or during the current practice period. A row opening at 15:00 UTC is only available for analysis after its 16:00 UTC close.

No silent sorting, interpolation or repairs were performed. Structural validity does not independently prove the prices' accuracy or official origin. See {link('validation CSV', 'docs/history_readiness_2026-10-07/history_verified/csv_validation.csv')} and {link('full validation and hashes', 'docs/history_readiness_2026-10-07/history_verified/csv_validation.json')}.
''')

    usage_rows = [
        ('research_intelligence/organizer_history.py', 'Validates CSVs and safely inspects/extracts archives. HistoricalDataset.as_of(T) exposes only hours already closed at T.', 'Preserves hourly/source identity; offers no live market or order interface.'),
        ('research_intelligence/reference_price_analysis.py', 'Computes causal hourly returns, ATR distributions, UTC time features and a labeled hourly VWAP proxy.', 'Uses recorded OHLCV only; creates no fills, P&L, funding or outcome labels.'),
        ('scripts/verify_organizer_history.py', 'Runs PAPER/freeze checks and writes immutable validation, research summaries and optional isolated raw features.', 'Offline research launcher; cannot enable the exchange transport.'),
        ('algo-trading-bot/test_organizer_history.py', 'Exercises bad data, archive attacks, future-data leakage and production isolation.', 'Synthetic local fixtures are reported as offline tests.')]
    medians = [(m['symbol'], f"{100 * m['training_hourly_atr_fraction_quantiles']['0.5']:.4f}%",
                m['partitions']['TRAIN'], m['partitions']['VALIDATION'], m['partitions']['HOLDOUT_RESERVED']) for m in analysis['markets']]
    section('4. History usage and research results', table(['New component', 'What it does', 'Why this use is valid'], usage_rows) + f'''

In simple terms, the loader is a research library. It can tell us what past hourly prices did. It cannot tell us what price an order would have filled at in the competition.

The existing frozen ATR helper is reused without edits, with 14 **hourly** bars. The production strategy still uses its existing minute-bar inputs. The table below describes training-period price movement; it is not a trading result.

{table(['Market', 'Median training hourly ATR / close', 'Training rows', 'Validation rows', 'Reserved holdout rows'], medians)}

The generated feature file contains **{feature_count:,} rows** from training and validation only. It records source market, interval, candle-open time, decision time, hourly return, ATR, volume, UTC hour, weekday and a UTC daily hourly-bar VWAP proxy.

The VWAP proxy uses HLC3 multiplied by each hour's volume. It cannot recover the exact within-hour traded VWAP. It is null when the UTC day's preceding hourly coverage is incomplete. Research does not replace or optimize the production VWAP anchor.

The chronological boundaries are shared across markets:

- Training: decision times before **2026-07-14 07:00 UTC**.
- Validation: **2026-07-14 07:00 UTC** through times before **2026-08-25 00:00 UTC**.
- Reserved holdout: **2026-08-25 00:00 UTC onward**; no price features or performance statistics were evaluated there.

These form approximately 60/20/20 partitions by unique UTC bar-close times. No model or transform was fitted. Integrity validation reads every CSV, including holdout rows; this is separate from using holdout prices for model selection. At time T, the loader excludes an hour whose close is after T. Feature tests verify that later prices cannot change earlier results. Real missing-hour boundaries reset return/ATR continuity; no fake bars are inserted.

Every feature's spread, depth, slippage, fills, fee, funding, mark, oracle, outcome label and production signal remain null. No minute-strategy backtest, LONG/SHORT setup frequency, after-cost advantage, trained ML model or validated anchor is claimed. Chronological purging would additionally be required if future experiments introduce outcomes spanning multiple hours.

An hourly statistic crossing 0.40% is not permission to change the frozen **minute** scanner threshold. Research merely reports that comparison; production parameters remain unchanged.

See {link('price analysis', 'docs/history_readiness_2026-10-07/history_verified/price_analysis.json')} and {link('local raw price features', str(features.relative_to(ROOT)))}. Raw features are about {features.stat().st_size / 1_000_000:.2f} MB and ignored by Git. The earlier history/history_final runs are retained; history_verified is the current reviewed snapshot.
''')

    section('5. Live-data isolation', f'''
The production entry points `run_crypto_paper.py`, `run_practice.py` and `run_testnet_practice.py` continue to use Hyperliquid market data. A transitive import-graph test checks their reachable modules and confirms that they do not import the historical research modules.

HistoricalBar fixes its identity to one-hour mainnet reference data. It cannot be relabeled to one minute through the tested dataclass replacement path. The production minute-candle normalizer rejects these bars. HistoricalDataset exposes no get_candles, get_quote or order methods. The research CLI itself requires PAPER mode and a passing freeze check.

Thus, the reviewed entry points contain no historical-file fallback when public `par:` data is incomplete. This is evidence about the current code paths; any future wiring change must preserve and rerun those checks.

The real public PAPER smoke confirms the distinction: it used live testnet queries, rejected unavailable setups and created **zero local orders/fills**. It did not borrow hourly CSVs to make those setups pass.
''')

    section('6. Strategy integrity', f'''
**Freeze result: PASS against nse-working-baseline.** It checked one complete source file, eight protected methods and 32 protected parameter values. Phase-0 safety also passed every check, including independent cloned Git identity, PAPER mode, disabled Angel One execution and disabled testnet submissions.

signal_brain.py remains byte for byte unchanged, with SHA-256 `{sha(ROOT / 'algo-trading-bot/signal_brain.py')}`. The strategy-freeze manifest was not altered. Frozen VWAP, EMA, ATR, entry/exit concepts, cooldowns, direction flips and state behavior were preserved. Scanner defaults remain ATR 0.40%, spread 15 bps, 300 completed bars and Top-3. The original NSE repository was not edited.

Changes in this task are isolated research modules, their launcher/tests, ignore rules and evidence documentation. No research variant was promoted into production. The legacy occurrence inventory is maintained through its existing inventory script.
''')

    balances = account['reported_equity']
    account_rows = [
        ('Observation', observed), ('Network / DEX', 'Hyperliquid testnet / par, index 257'),
        ('Team wallet', account['team_address']), ('USDPR collateral balance', balances['collateral_balance']),
        ('Account mode', account['account_mode']), ('API wallet name', 'anchorium-bot-1'),
        ('API public address', account['api_wallet_address']), ('Public approval / expiry', 'Approved; ' + expiry),
        ('Position / ordinary open orders / frontend orders', '0 / 0 / 0'),
        ('Observed margin used / USDPR hold', '0 / 0'),
        ('Per-side availableToTrade', '1,000,000 USDPR on each queried coin, long and short'),
        ('Base userFees taker / maker', '0.00045 / 0.00015'),
        ('Observed venue fee scale', 'deployerFeeScale = 1.0'),
        ('Account rate count', f"{account['user_rate_limit']['nRequestsUsed']} used / {account['user_rate_limit']['nRequestsCap']} cap"),
        ('Clock observation', f"HEALTHY; {account['clock']['offset_ms']} ms offset; one fresh confirmation"),
        ('Read-only reconciliation', 'Ready within the explicit observed window'),
        ('Actual signer / nonce ownership', 'NOT LIVE VERIFIED'),
        ('Human wallet verification', 'Not performed / not recorded'),
        ('Emergency protection', 'Disabled; no approved distance or execution allowance')]
    section('7. Account readiness', table(['Check', 'Real read-only observation or limitation'], account_rows) + f'''

These are real public account-query results, not fixture balances. The technical account check passed. The fresh saved evidence contains **45 /info queries**, with no signed-action payloads. See {link('account check', 'docs/history_readiness_2026-10-07/account_check.json')}.

One million USDPR belongs to the **team account**. It is not the API wallet's balance. The API approval identifies a permitted public address; that alone cannot prove the actual private signer or persistent nonce manager is correct.

Unified collateral is read from the matching USDPR spot token, identified against runtime metadata (token 3032 in this snapshot). The unused per-DEX account summary may show zero; it is not substituted for the unified balance. The total balance is not treated as permission to spend all collateral. Coin-and-side capacity comes from activeAssetData, with existing risk limits still applied. Withdrawable is left unknown, rather than inferred.

For this venue's positive base rates, the fee-scale calculation implies **0.09% taker and 0.03% maker** before relevant discounts. Actual accounting must use each reported fill's fee and fee token, and actual reported funding payments. [Official participant guide](https://perpetual-alpha26.github.io/docs/)

**Leverage is a blocker:** activeAssetData reports 20x cross for nine markets and 10x cross for HYPE; the bot policy remains 1x cross. No leverage-setting action was performed, and the local policy was not weakened to accept those settings.

Reconciliation observed no fills or funding events from **2026-10-05 00:00 UTC** to this snapshot. Its zero observed event totals are not a test-trade P&L result, nor a claim of complete lifetime history.

The account subsystem emits the legacy label LIVE_TECHNICALLY_READY_BUT_LOCKED when its account-only checks pass. That label does **not** certify feed, signer, protection, execution or recovery readiness; its live_ready field remains false. This report uses the stricter complete readiness gate.
''')

    section('8. Tests and PAPER evidence', f'''
{table(['Check', 'Result', 'Scope'], [
    ('Complete repository suite', '1,249 passed; 0 failed; 0 errors; 0 skipped', 'Offline fixtures; no actual exchange actions'),
    ('New history tests, included above', '35 passed', 'CSV quality, ZIP safety, leakage and isolation'),
    ('Strategy freeze', 'PASS', 'Baseline hashes, protected methods and parameters'),
    ('Phase-0 safety', 'PASS', 'PAPER/false and Angel/testnet write lockouts'),
    ('Current public PAPER smoke', 'NO_TRADE; 0 local orders; 0 local fills', 'Real public par feed; hypothetical portfolio'),
    ('Controlled LONG / SHORT', 'NOT RUN — NOT LIVE VERIFIED', 'Actual account execution required')])}

The complete suite finished in 238.63 seconds. Source fingerprints were identical before and after it. See {link('test receipt', 'docs/history_readiness_2026-10-07/test_receipt.json')} and {link('per-test XML', 'docs/history_readiness_2026-10-07/regression.xml')}.

Current PAPER observation: **{paper['observed_at_utc']}** (approximately 09:55 IST on 7 October). Ten markets were scanned. Nine lacked sufficient completed history. SP500 had 300 completed candles but reported ATR 0.01414%, below 0.40%, and spread 19.69 bps, above 15 bps. None qualified, so the correct result was NO_TRADE. This is not a crash or a reason to relax the frozen rules.

The PAPER portfolio began with **20,000 hypothetical USDPR**, distinct from the real one-million-USDPR account. Its zero P&L/fees/funding reflect zero simulated activity; they establish no strategy profitability. The standalone smoke intentionally had no real account observer configured. The separate account check above supplies wallet evidence. See {link('PAPER report', 'docs/history_readiness_2026-10-07/public_paper_smoke/report.json')}.

Earlier evidence on 7 October includes an 11-minute continuous PAPER run, a 90-second flat PAPER restart and one real public BTC WebSocket reconnect. Those artifacts are retained under docs/prepractice_readiness_2026-10-07. They predate the research additions and use a different active-source fingerprint. They are not current-source continuous-operation certification or funded-account recovery certification.
''')

    section('9. Controlled real test', table(['Required evidence', 'Result'], [
        ('Entry request / individual exchange result', 'NOT RUN — no actual request submitted'),
        ('Actual fill ID, price and quantity', 'NOT RUN — no certification fill'),
        ('Position sign and size after entry', 'NOT RUN — no entry position'),
        ('Actual entry fee', 'NOT RUN — no fill fee'),
        ('Accepted reduce-only protection', 'NOT RUN — protection disabled'),
        ('Actual reduce-only exit and fill', 'NOT RUN — no exit action'),
        ('Actual test P&L / ledger reconciliation', 'NOT RUN — no test trade'),
        ('Final post-test flat state / stale orders', 'NOT RUN — read-only flat snapshot is not a completed test')]) + f'''

**Overall: NOT RUN — NOT LIVE VERIFIED.** The account was observed flat, but an account that never traded has not demonstrated successful entry, protection, exit or accounting.

Your request requires all readiness checks to pass and explicit authorization before the first actual order. Protection, leverage alignment, complete feed readiness and actual signer/nonce ownership remain unresolved. {link('Repository instructions', 'AGENTS.md')} additionally say: “Any later activation requires the human user's explicit change after the Team Anchorium wallet is funded, configured and manually verified.” Those conditions have not been completed; all exchange writes remain blocked.

The future flow is made reviewable in {link('inactive certification plan', 'docs/history_readiness_2026-10-07/certification_plan.md')}. It defines bounded entry, actual fill reconciliation, independent reduce-only protection, verified exit and authoritative flat-state checks. It is documentation, not an activation or approval file.
''')

    section('10. LONG certification', '''
**NOT RUN — NOT LIVE VERIFIED.** A future authorized LONG test must demonstrate an actual BUY fill, positive exposure of the correct filled size, actual fee, accepted protection, reduce-only SELL exit and reconciled flat state. A signal, an accepted request or a synthetic test alone is insufficient. No LONG certification was claimed or recorded as PASS.
''')
    section('11. SHORT certification', '''
**NOT RUN — NOT LIVE VERIFIED.** A future authorized SHORT test may begin only after LONG is authoritatively flat and reconciled. It must demonstrate an actual SELL fill, negative exposure of the correct size, actual fee, accepted protection, reduce-only BUY exit and reconciled flat state. Partial fills and unresolved orders count toward the one global position lock. No SHORT certification was claimed or recorded as PASS.
''')

    failure_rows = [(kind, 'OFFLINE_TESTED', 'NOT RUN — NOT LIVE VERIFIED', '`' + name + '`') for kind, name in recovery_tests.items()]
    section('12. Failure and recovery tests', table(['Case', 'Offline implementation evidence', 'Actual funded-account certification', 'Passing test in full suite'], failure_rows) + f'''

These execution tests use synthetic account/exchange responses and ephemeral API-wallet fixtures. Their offline transport cannot submit HTTP exchange actions. They verify cancellation interpretation, partial exposure, restarts beginning UNKNOWN, account barriers, ambiguous-response reconciliation and duplicate protection. They do not certify the funded team account.

The earlier real public-socket test closed a BTC connection, reconnected once, resubscribed and recovered market data through REST. That is **PUBLIC MARKET RECOVERY VERIFIED in its recorded scope**, not actual position/order/protection recovery. See {link('earlier public reconnect', 'docs/prepractice_readiness_2026-10-07/public_reconnect.json')}.

The earlier PAPER restart recovered a flat hypothetical ledger. No process was crashed with a real position, no actual order was created/cancelled for testing, and no live partial fill or real existing-position recovery was performed. RESTART_CERTIFIED and RECONNECT_CERTIFIED remain NO for the funded execution scope.
''')

    flag_rows = list(flags.items())
    section('13. Final status', table(['Flag', 'Value'], flag_rows) + '''

ACCOUNT_READY and API_WALLET_READY mean timestamped read-only technical readiness and public approval, respectively. PAPER_READY means that the guarded smoke completed; it does not mean that all feeds are healthy or profitability has been shown. HISTORY_DATA_READY stays NO until official provenance is authenticated. RESEARCH_DATA_READY stays NO for the complete validated strategy/ML pipeline, while PRICE_FEATURE_RESEARCH_PREPARED is YES.

The research flags remain honest:

```ini
SESSION_ANCHOR_VALIDATED = FALSE
ML_DATA_READY           = FALSE
ML_MODEL_VALIDATED      = FALSE
HOLDOUT_COMPLETE        = FALSE
PROMOTION_RECOMMENDED   = FALSE
PRODUCTION_CHANGED     = FALSE
```

Here PRODUCTION_CHANGED refers to research promotion into production strategy/policy. Research code and documentation were added; no research strategy/model was activated. No competition score, winning performance or ML advantage has been established.
''')

    section('14. What must happen before funded practice', '''
1. Authenticate the history files using the organizer's download/announcement source. If the original ZIP becomes available, inspect it before extraction and compare its member hashes to these CSVs. Keep all previous evidence.
2. Continue collecting real public one-minute par candles and books. Diagnose sparse/delayed histories without substituting mainnet CSVs or interpolating bars. A setup must meet the unchanged scanner and strategy rules.
3. Have the human verify the exact team account and API-wallet approval, then resolve exchange leverage to the reviewed policy through a separately authorized configuration action. Reading funding does not authorize this change.
4. Review and explicitly approve the independent catastrophic-protection distance and execution allowance. Enable it only as part of the separately authorized testnet activation after the other gates pass. Keep strategy stops and targets unchanged.
5. Verify the actual API signer, durable nonce ownership, fresh clock/rate state and reconciliation on the intended single host. The team-wallet secret stays outside the bot. Run only one signing process for anchorium-bot-1.
6. Once every required gate is green, obtain explicit activation and an exact bounded test budget. Perform LONG, verify fills/protection/exit/flat state, then SHORT. Never invent a qualifying strategy signal just to force the test.
7. Complete required real recovery evidence, clearly distinguishing cases safely tested offline. Begin supervised practice before considering unattended operation.

The earlier host setup remains local. No server/AWS deployment or external notification service was installed in this task. The new research integration changes the source fingerprint, so an older persistent PAPER ledger must not silently resume under it. Use a new clearly labeled PAPER state directory or a separately reviewed migration; preserve the old ledger and checkpoints. Do not erase a journal or nonce store to bypass a source or recovery guard.
''')

    section('15. Evidence and reproducibility', f'''
{link('Machine-readable readiness and evidence hashes', 'docs/history_readiness_2026-10-07/readiness.json')} binds this report to saved tests, data and account observations.

Git commit: `{research_identity['commit']}`; working tree dirty. Current active-source hash, excluding dependency environments: `{active_hash}`. The account audit and full suite match this hash. The protected brain hash and raw CSV hashes are separately retained.

The historical research receipt uses its narrower research/configuration source definition, hash `{research_identity['source_hash']}`. The PAPER session manifest uses session_results.source_version, hash `{manifest['working_source_hash']}`; that definition includes nested dependency Python files and a different JSON encoding. Each was recomputed under its own definition and matches the current saved artifact. Different definitions must not be compared as if identical. The validated report generator itself is local and performs no network or signed action.

For a new offline validation/research snapshot, run from the cloned project root with new output paths:

```sh
.venv/bin/python scripts/verify_organizer_history.py \\
  --output docs/history_next_snapshot \\
  --features-output algo-trading-bot/data/organizer-history-research/next_snapshot/price_features.jsonl
```

The script refuses an existing report directory and uses exclusive feature-file creation. Keep PAPER/false. Add --archive only when an actual archive is available; inspection does not authenticate its origin or activate trading. The CSV input directory defaults to the existing data/history directory.

Review {link('historical validator/loader', 'algo-trading-bot/research_intelligence/organizer_history.py')}, {link('hourly feature analysis', 'algo-trading-bot/research_intelligence/reference_price_analysis.py')}, {link('research CLI', 'scripts/verify_organizer_history.py')} and {link('35 history tests', 'algo-trading-bot/test_organizer_history.py')} for implementation details.
''')

    for path, value in [(OUT / 'readiness.json', json.dumps(readiness, indent=2, allow_nan=False) + '\n'),
                        (OUT / 'report.md', introduction + '\n' + '\n'.join(sections))]:
        with path.open('x') as stream:
            stream.write(value)
    print(json.dumps(dict(report=str(OUT / 'report.md'), readiness=str(OUT / 'readiness.json'),
                         tests=tests['totals'], csv_rows=validation['total_rows'], feature_rows=feature_count,
                         strategy_freeze=freeze['passed'], raw_csv_hashes_unchanged=True,
                         practice_ready=False, exchange_orders_submitted=0)))


if __name__ == '__main__':
    main()
