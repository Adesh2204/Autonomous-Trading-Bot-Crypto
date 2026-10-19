"""Read-only engineering evidence index. This is never a trading authorization.

JUnit is local test evidence, public receipts are observations, and self-reported
LIVE manifests are unverified records. None can turn on exchange permissions.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from exchange.hyperliquid_client import EXPECTED_MARKETS
from session_results import source_version
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


READINESS_KEYS=('REPOSITORY_INTEGRITY','STRATEGY_FREEZE','MARKET_DATA','PAPER','REPLAY',
    'SIGNED_EXECUTION','WALLET','USDPR','API_AGENT','UNIFIED_ACCOUNT','VENUE_RULES',
    'RATE_LIMIT','NONCE','CLOCK','RESTART_RECOVERY','RECONNECT_RECOVERY','PROTECTION',
    'SINGLE_POSITION','COMPLIANCE','ACCOUNTING','PRACTICE','PERFORMANCE_EVIDENCE',
    'VWAP_RESEARCH','ML_VALIDATION','HOLDOUT','JURY_EVIDENCE','COMPETITION_RELEASE',
    'LIVE_READY','HACKATHON_READY')

PRACTICE_CHECKS=('market_discovery','healthy_candles','healthy_books','mark_oracle',
    'funding_events','actual_account_reads','long_entry_exit','short_entry_exit',
    'partial_fill','cancel','modify','reduce_only_exit','actual_fees','actual_funding',
    'websocket_reconnect','process_restart','existing_position_recovery',
    'protection_restoration','duplicate_prevention','no_phantom_accounting',
    'multiple_hours','multiple_conditions','funding_boundary','stale_data',
    'rate_pressure','crash','normal_stop','normal_target')

# Existing components and their actual owner paths, not proposed replacements.
ARCHITECTURE=(
    ('configuration',('venue_config.py',),'scripts/run_crypto_paper.py'),
    ('market discovery',('exchange/hyperliquid_client.py',),'scripts/run_crypto_paper.py'),
    ('public REST / WebSocket',('exchange/hyperliquid_market_data.py','exchange/stream_first.py','market_stream.py'),'scripts/run_crypto_paper.py'),
    ('scanner / ranking',('market_regime_scanner.py',),'scripts/run_crypto_paper.py'),
    ('frozen indicators / strategy state',('signal_brain.py','frozen_strategy.py','crypto_strategy_state.py'),'crypto_paper_bot.py / live_execution_session.py'),
    ('economics / risk',('exchange/perpetual_economics.py','risk/portfolio_risk.py','risk/circuit_breakers.py'),'crypto_paper_bot.py / live_execution_session.py'),
    ('paper execution',('exchange/paper_execution.py','exchange/paper_portfolio.py'),'scripts/run_crypto_paper.py'),
    ('replay',('exchange/replay.py',),'scripts/run_crypto_replay.py'),
    ('future signed execution',('exchange/hyperliquid_execution.py','exchange/sdk_transport.py','exchange/exchange_rules.py'),'exchange/live_runtime.py:build_live_runtime'),
    ('account readiness',('exchange/live_readiness.py','exchange/hyperliquid_account.py'),'exchange/exchange_rules.py:LiveContextProvider'),
    ('durable intent / actual-fill recovery',('exchange/execution_journal.py','exchange/live_recovery.py','exchange/hyperliquid_reconciliation.py'),'exchange/startup_recovery.py'),
    ('startup / reconnect',('exchange/startup_recovery.py','exchange/live_account_stream.py'),'exchange/live_runtime.py'),
    ('rate / nonce / clock',('exchange/rate_limits.py','exchange/execution_safety.py','exchange/reliability_policy.py'),'exchange/live_runtime.py'),
    ('catastrophic protection',('exchange/position_protection.py',),'live_execution_session.py'),
    ('single position / compliance',('exchange/single_position_guard.py','exchange/compliance_guard.py'),'exchange/hyperliquid_execution.py / exchange/sdk_transport.py'),
    ('actual results',('live_session_results.py','exchange/compliance_report.py','opportunity_funnel.py'),'exchange/live_runtime.py:LiveRuntime.save_results'),
    ('paper results',('session_results.py',),'scripts/run_crypto_paper.py:ReportWriter'),
    ('isolated VWAP / ML research',('research_lab/forward_lab.py','research_intelligence/campaign.py','research_intelligence/readiness.py'),'scripts/run_research_readiness.py'),
    ('read-only certification',('certification_audit.py',),'scripts/run_hackathon_certification.py'),
    ('retired Angel / NSE',('disabled_angel_client.py','safe_trader.py','live_stream.py'),'LEGACY; guarded against exchange writes'),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_file(path):
    path=Path(path)
    return dict(path=str(path.resolve()),sha256=sha(path))


def code_hash(root):
    root=Path(root)
    return source_version(list((root/'algo-trading-bot').rglob('*.py'))+list((root/'scripts').glob('*.py')))


def junit_evidence(path,receipt=None,*,expected_source_hash=None):
    """Count test cases, not a caller's claimed all-green summary."""
    if path is None:
        return dict(status='UNTESTED',tests=None,failures=None,errors=None,skipped=None,current_source_bound=False)
    result=dict(status='UNTESTED',current_source_bound=False)
    try:
        result.update(evidence_file(path))
        tree=ET.parse(path).getroot()
        cases=list(tree.iter('testcase'))
        result.update(tests=len(cases),failures=sum(c.find('failure') is not None for c in cases),
            errors=sum(c.find('error') is not None for c in cases),skipped=sum(c.find('skipped') is not None for c in cases))
        suites=list(tree.iter('testsuite'))
        result['reported_tests']=sum(int(s.get('tests',0)) for s in suites if not s.findall('testsuite'))
        if not cases or result['reported_tests']!=len(cases):
            result['reason']='EMPTY_OR_INCONSISTENT_JUNIT'
            return result
        result['status']='BROKEN' if result['failures'] or result['errors'] else 'PARTIAL' if result['skipped'] else 'UNIT_TESTED'
        if receipt is not None:
            recorded=json.loads(Path(receipt).read_text())
            result['receipt']=evidence_file(receipt)
            result['current_source_bound']=(recorded.get('xml_sha256')==result['sha256'] and
                recorded.get('source_hash')==expected_source_hash and
                recorded.get('suite_scope')=='FULL_REPOSITORY' and recorded.get('command_exit_code')==0)
        result['meaning']='Local engineering evidence only; a receipt is reproducibility metadata, not external attestation.'
    except (OSError,ValueError,ET.ParseError,TypeError):
        result.update(status='BROKEN',reason='INVALID_TEST_EVIDENCE')
    return result


def security_audit(root):
    """Return file/line references only. Never publish matching secret values."""
    root=Path(root)
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    scanned=sorted(set(filter(None,tracked+untracked)))
    findings=[]
    secret_pattern=re.compile(r'(?i)(?:private[_ ]?key|api[_ ]?key|password|totp_secret|seed_phrase)\s*[=:]\s*[\"\']([^\"\']+)[\"\']')
    for name in scanned:
        path=root/name
        if path.name=='.env' or path.suffix=='.key' or {'wallets','secrets'} & set(path.parts):
            findings.append(dict(path=name,line=None,kind='TRACKED_SECRET_CONTAINER'))
        if not path.is_file() or path.stat().st_size>10_000_000:
            continue
        try:
            lines=path.read_text().splitlines()
        except (UnicodeError,OSError):
            continue
        for line_no,line in enumerate(lines,1):
            for match in secret_pattern.finditer(line):
                literal=match.group(1)
                if len(literal)>=16 and re.fullmatch(r'(0x)?[0-9a-fA-F]{64}|[A-Z2-7]{16,}',literal):
                    findings.append(dict(path=name,line=line_no,kind='SECRET_SHAPED_LITERAL_REQUIRES_REVIEW'))
    ignored={name:subprocess.run(['git','check-ignore','-q','--no-index',name],cwd=root).returncode==0
             for name in ('.env','algo-trading-bot/.env','example.key','wallets/example','secrets/example')}
    return dict(status='PARTIAL' if findings or not all(ignored.values()) else 'VERIFIED',
        tracked_files_scanned=len(list(filter(None,tracked))),nonignored_working_files_scanned=len(scanned),findings=findings,ignored=ignored,
        scope='Current tracked and nonignored untracked text files up to 10 MB; pattern checks cannot prove absence of every possible credential. No ignored credential files, Git-history scan or external secret scanner were read.')


def session_evidence(path,*,current_source_hash):
    """Index records without promoting their mode label to real certification."""
    path=Path(path)
    if (path/'results').is_dir():path=path/'results'
    result=dict(path=str(path.resolve()),status='UNTESTED',certifies_practice=False)
    try:
        manifest=json.loads((path/'session_manifest.json').read_text())
        configuration=manifest.get('configuration')
        configured_mode=configuration.get('execution_mode') if isinstance(configuration,dict) else None
        mode=manifest.get('execution_mode') or configured_mode
        if configured_mode is not None and mode!=configured_mode:
            raise ValueError('MANIFEST_MODE_CONFLICT')
        if mode not in {'PAPER','REPLAY','OFFLINE_SIGNED_FIXTURE','LIVE_TESTNET'}:
            raise ValueError('UNKNOWN_EXECUTION_MODE')
        result.update(mode=mode,manifest=evidence_file(path/'session_manifest.json'),
            source_compatible=manifest.get('working_source_hash')==current_source_hash,
            source_hash=manifest.get('working_source_hash'),git_commit=manifest.get('git_commit'),
            status='RECORDED_UNVERIFIED' if mode=='LIVE_TESTNET' else 'RECORDED_SIMULATION')
        fills=None
        if (path/'fills.jsonl').exists():
            fills=[json.loads(line) for line in (path/'fills.jsonl').read_text().splitlines() if line.strip()]
            for fill in fills:
                if fill.get('execution_mode')!=mode:
                    raise ValueError('MIXED_EXECUTION_MODES')
                if mode=='LIVE_TESTNET' and (fill.get('source')!='EXCHANGE_REPORTED' or fill.get('execution_source')!='EXCHANGE_REPORTED'):
                    raise ValueError('LIVE_SOURCE_NOT_PROVEN')
        result['recorded_fill_count']=len(fills) if fills is not None else None
        result['note']='Simulation/recorded records never certify the funded account or sustained practice. A LIVE label alone is unverified.'
        funnel=path/'funnel_summary.json'
        if funnel.exists():
            data=json.loads(funnel.read_text())
            result['funnel']=dict(evidence=evidence_file(funnel),source=data.get('source'),session=data.get('session'))
    except (OSError,ValueError,TypeError,KeyError):
        result.update(status='BROKEN',reason='INVALID_OR_MIXED_SESSION_EVIDENCE',certifies_practice=False)
    return result


def build_audit(root,*,tests_xml=None,tests_receipt=None,market_evidence=None,sessions=(),research_evidence=None):
    root=Path(root).resolve()
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    source_hash=code_hash(root)
    policy=freeze=None
    problems=[]
    try:policy=require_paper_migration()
    except RuntimeError:problems.append('MIGRATION_POLICY_INVALID')
    try:freeze=verify_strategy_freeze(root)
    except (OSError,ValueError,RuntimeError):problems.append('STRATEGY_FREEZE_INVALID')
    tests=junit_evidence(tests_xml,tests_receipt,expected_source_hash=source_hash)
    baseline_present='nse-working-baseline' in git('tag','--list').splitlines()
    branch=git('branch','--show-current')
    if not baseline_present:problems.append('BASELINE_TAG_MISSING')
    if tests['status']=='BROKEN':problems.append('TEST_EVIDENCE_FAILED')
    engineering_pass=(tests['status']=='UNIT_TESTED' and tests['current_source_bound'])
    security=security_audit(root)
    if security['findings']:problems.append('SECURITY_FINDING_REQUIRES_REVIEW')
    indexed=[session_evidence(p,current_source_hash=source_hash) for p in sessions]
    market=dict(status='UNTESTED',team_wallet_configured=False,api_wallet_configured=False)
    if market_evidence is not None:
        try:
            observed=json.loads(Path(market_evidence).read_text())
            names={s['symbol'] for s in observed.get('metadata',[])}
            identity=observed.get('network')=='testnet' and observed.get('dex')=='par'
            discovery=identity and observed.get('market_data_ready') is True and EXPECTED_MARKETS<=names
            market=dict(status='RECORDED_PUBLIC' if discovery else 'PARTIAL',evidence=evidence_file(market_evidence),
                market_discovery=discovery,observed_ms=observed.get('observed_ms'),
                clock_sample_healthy=observed.get('clock_healthy') is True,
                team_wallet_configured=observed.get('team_wallet_configured') is True,
                api_wallet_configured=observed.get('api_wallet_configured') is True,
                reason='Public metadata/clock snapshot; current candle/stream health and funded-account certification are not established.')
        except (OSError,ValueError,TypeError,KeyError):
            market.update(status='BROKEN',reason='INVALID_PUBLIC_EVIDENCE')
    architecture=[]
    for stage,paths,owner in ARCHITECTURE:
        files=[root/'algo-trading-bot'/p for p in paths]
        exists=all(p.is_file() for p in files)
        status='LEGACY' if stage=='retired Angel / NSE' else 'PARTIAL' if exists else 'MISSING'
        architecture.append(dict(stage=stage,status=status,owner=owner,
            code=[evidence_file(p) for p in files if p.is_file()],
            verification='CURRENT_SOURCE_INSPECTED_AND_REGRESSION_TESTED' if exists and engineering_pass else 'SOURCE_PRESENT_RUNTIME_UNVERIFIED'))
    matrix={k:dict(status='MISSING',proof='NOT_OBSERVED',missing='Requires real account/practice/release evidence.') for k in READINESS_KEYS}
    def row(key,status,proof,missing):matrix[key]=dict(status=status,proof=proof,missing=missing)
    row('REPOSITORY_INTEGRITY','VERIFIED' if policy and baseline_present else 'BROKEN','CURRENT_SOURCE_CHECK','Uncommitted audit changes must be reviewed/versioned before release.')
    row('STRATEGY_FREEZE','VERIFIED' if freeze else 'BROKEN','CURRENT_HASH_CHECK','No strategy change is permitted.')
    for key in ('PAPER','REPLAY','SIGNED_EXECUTION','VENUE_RULES','RATE_LIMIT','NONCE','RESTART_RECOVERY',
                'RECONNECT_RECOVERY','PROTECTION','SINGLE_POSITION','COMPLIANCE','ACCOUNTING','VWAP_RESEARCH'):
        row(key,'PARTIAL' if engineering_pass else 'UNTESTED','UNIT_TESTED' if engineering_pass else 'UNBOUND_OR_MISSING_TEST_EVIDENCE',
            'Engineering implementation only; actual account/practice/OOS evidence remains required.')
    row('MARKET_DATA','PARTIAL' if market.get('market_discovery') else 'UNTESTED',market['status'],'Continuous healthy candles/books/context and prolonged observation required.')
    row('CLOCK','PARTIAL' if market.get('clock_sample_healthy') else 'UNTESTED','RECORDED_PUBLIC_SAMPLE','A past sample is not current runtime/NTP health.')
    for key in ('WALLET','USDPR','API_AGENT','UNIFIED_ACCOUNT'):
        row(key,'PARTIAL' if market.get('team_wallet_configured') else 'MISSING','CONFIGURED_UNVERIFIED' if market.get('team_wallet_configured') else 'NOT_CONFIGURED','Verify the funded Team wallet, separate approved API address, unified mode and permissions using read-only queries and human review.')
    row('JURY_EVIDENCE','PARTIAL','ENGINEERING_INDEX','Measured real trade explanations and final 2–4 page PDF/code submission are outstanding.')
    for key in ('LIVE_READY','HACKATHON_READY'):
        row(key,'MISSING','FALSE','Funded account, controlled execution, prolonged practice and reviewed competition release remain unverified.')
    research=dict(status='MORE_DATA_REQUIRED',flags={k:False for k in ('SESSION_ANCHOR_VALIDATED','ML_DATA_READY',
        'ML_MODEL_VALIDATED','HOLDOUT_COMPLETE','PROMOTION_RECOMMENDED')},production_strategy_changed=False)
    if research_evidence is not None:
        try:
            data=json.loads(Path(research_evidence).read_text())
            research.update(evidence=evidence_file(research_evidence),reported_flags=data.get('status'),
                counts={k:data.get('quality',{}).get(k) for k in ('candidate_rows','usable_labeled_rows','positive_outcomes','negative_outcomes')},
                holdout=data.get('holdout'),note='Historical research report; no promotion is inferred or performed.')
        except (OSError,ValueError):research.update(status='INVALID_RESEARCH_EVIDENCE')
    verdict='NOT_READY' if problems else 'ACCOUNT_SETUP_REQUIRED'
    return dict(schema_version=1,observed_at=datetime.now(timezone.utc).isoformat(),verdict=verdict,
        repository=dict(root=str(root),branch=branch,git_commit=git('rev-parse','HEAD'),git_dirty=bool(git('status','--porcelain')),
            baseline_tag_present=baseline_present,python=sys.version.split()[0],sdk=importlib.metadata.version('hyperliquid-python-sdk'),
            working_source_hash=source_hash,strategy_sha256=sha(root/'algo-trading-bot/signal_brain.py'),freeze=freeze),
        configuration=dict(migration=policy,network='testnet',dex='par',
            paper=evidence_file(root/'docs/paper_policy.example.json'),reliability=evidence_file(root/'configs/reliability_policy.json')),
        problems=problems,tests=tests,security=security,architecture=architecture,readiness=matrix,
        market_observation=market,recorded_sessions=indexed,research=research,
        practice=dict(execution_source='NO_CERTIFIED_LIVE_TESTNET_RUN',runtime_seconds=None,trades=None,realized_pnl=None,
            unrealized_pnl=None,net_pnl=None,fees=None,funding=None,max_drawdown=None,daily_volatility=None,
            errors=None,reconnects=None,checks={k:'NOT_OBSERVED' for k in PRACTICE_CHECKS}),
        live_ready=False,hackathon_ready=False,live_orders_permitted=False,
        authority='READ_ONLY_AUDIT; never consumed by signing/activation gates; imported files are not external attestation.',
        next_action='Provide and manually verify the funded Team Anchorium PUBLIC wallet and approved API PUBLIC address with read-only account checks. Keep PAPER/false.')


def write_audit(report,directory):
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    (path/'readiness.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    lines=['# Team Anchorium certification audit','',f"Verdict: **{report['verdict']}**",'',
        'This report indexes engineering evidence. It grants no trading permission. Missing measurements remain null.',
        '', '| Component | Status | Proof | Remaining requirement |','|---|---|---|---|']
    lines.extend(f"| {key} | {v['status']} | {v['proof']} | {v['missing']} |" for key,v in report['readiness'].items())
    lines.extend(['',f"Tests: {report['tests'].get('tests')} recorded; current source bound: {report['tests']['current_source_bound']}.",
                  '', 'Next action: '+report['next_action'],''])
    (path/'readiness.md').write_text('\n'.join(lines))
    index=dict(schema_version=1,working_source_hash=report['repository']['working_source_hash'],
        execution_permission=False,code=report['architecture'],market=report['market_observation'],
        tests=report['tests'],recorded_sessions=report['recorded_sessions'],research=report['research'],
        measured_actual_trade_explanations=None,note='Evidence index and draft preparation; not a completed jury submission or competition release.')
    (path/'jury_evidence_index.json').write_text(json.dumps(index,indent=2,allow_nan=False)+'\n')
    return path
