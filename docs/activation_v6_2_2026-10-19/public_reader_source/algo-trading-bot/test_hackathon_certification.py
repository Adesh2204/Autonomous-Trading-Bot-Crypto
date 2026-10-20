"""Evidence integrity regressions. No exchange HTTP, wallet keys or activation."""
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from certification_audit import (READINESS_KEYS,PRACTICE_CHECKS,build_audit,code_hash,
    junit_evidence,session_evidence,sha,write_audit)
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import fingerprint
from exchange.live_runtime import LiveRuntime
from exchange.order_lifecycle import OrderRequest
from live_session_results import LiveSessionResults
from test_live_exchange_execution import live,permission,response
from test_restart_opportunity_diagnostics import session as live_session
from test_exchange_migration import NOW

ROOT=Path(__file__).resolve().parents[1]


def test_journal_event_has_real_session_envelope_and_null_unknowns(live):
    live.journal.event('GLOBAL_HEALTH',NOW,session_id='spoofed',event_type='spoofed')
    row=json.loads(live.journal.db.execute("SELECT data FROM events WHERE kind='GLOBAL_HEALTH'").fetchone()[0])
    assert row['session_id']==live.journal.session_id and row['event_type']=='GLOBAL_HEALTH'
    assert row['candidate_id'] is None and row['symbol'] is None and row['exchange_ts'] is None
    assert row['received_ts'] and row['processed_ts']


def test_fixture_result_events_never_export_exchange_reported_sources(live,tmp_path):
    writer=writer_for(live,tmp_path)
    live.journal.event('FIXTURE_ACCOUNT',NOW,source='EXCHANGE_REPORTED',fill={'source':'EXCHANGE_REPORTED_USER_FUNDING'})
    writer.save()
    records=[json.loads(line) for line in (writer.path/'candidate_traces.jsonl').read_text().splitlines()]
    row=next(r for r in records if r['kind']=='FIXTURE_ACCOUNT')
    assert row['source']==row['fill']['source']=='SYNTHETIC_SIGNED_FIXTURE'


def test_observed_exchange_clock_and_candidate_are_preserved(live):
    live.journal.event('OBSERVED',NOW,exchange_ts='2026-10-02T11:59:59Z',received_ts='2026-10-02T12:00:00Z',
                       candidate='actual:candidate',request={'symbol':'par:BTC'})
    row=json.loads(live.journal.db.execute("SELECT data FROM events WHERE kind='OBSERVED'").fetchone()[0])
    assert row['exchange_ts']=='2026-10-02T11:59:59Z' and row['candidate_id']=='actual:candidate'
    assert row['symbol']=='par:BTC'


def test_atomic_position_reconciliation_has_the_same_event_envelope(live):
    request=OrderRequest('par:BTC','BUY','.2','100')
    live.executor.position_guard.reconcile(live.provider.load(request),NOW)
    row=json.loads(live.journal.db.execute("SELECT data FROM events WHERE kind='GLOBAL_POSITION_RECONCILED' ORDER BY seq DESC").fetchone()[0])
    assert row['session_id']==live.journal.session_id and row['event_type']=='GLOBAL_POSITION_RECONCILED'
    assert row['candidate_id'] is None and row['symbol'] is None


def writer_for(live,tmp_path):
    session=live_session(live);session.startup()
    return LiveSessionResults(tmp_path,session)


def test_synthetic_account_labels_and_rejected_intents_never_claim_real_orders(live,tmp_path):
    writer=writer_for(live,tmp_path)
    req=OrderRequest('par:BTC','BUY','.2','100',client_order_id='rejected')
    live.transport.responses=[response({'error':'Insufficient margin'})]
    live.executor.submit(req,permission=permission(req))
    writer.save()
    data=json.loads((writer.path/'actual_account_report.json').read_text())
    assert data['source']=='SYNTHETIC_SIGNED_FIXTURE'
    assert data['confirmed_order_count']==0 and data['durable_intent_count']==1
    assert data['exchange_orders_submitted']==0 and data['signed_attempt_count']==1
    manifest=json.loads((writer.path/'session_manifest.json').read_text())
    assert manifest['source']=='SYNTHETIC_SIGNED_FIXTURE' and manifest['configuration']['model_version'] is None
    assert manifest['configuration_hash']==fingerprint(manifest['configuration'])
    assert manifest['strategy_source_hash']==sha(ROOT/'algo-trading-bot/signal_brain.py')
    assert manifest['working_source_hash']==code_hash(ROOT)
    import csv
    with (writer.path/'equity.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    assert rows and rows[0]['session_id']==live.journal.session_id
    assert rows[0]['execution_source']=='SYNTHETIC_SIGNED_FIXTURE' and rows[0]['event_type']=='EQUITY'


@pytest.mark.parametrize('field',['team_wallet','api_wallet','session_id','configuration_hash','working_source_hash'])
def test_result_resume_rejects_changed_identity_or_policy(live,tmp_path,field):
    writer=writer_for(live,tmp_path)
    manifest_path=writer.path/'session_manifest.json'
    data=json.loads(manifest_path.read_text());data[field]='changed';manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='RESULT_MANIFEST_IDENTITY_OR_POLICY_CHANGED'):
        LiveSessionResults(tmp_path,writer.session)
    assert json.loads(manifest_path.read_text())[field]=='changed'


def test_runtime_exports_after_cycle_and_before_close():
    stop=threading.Event();calls=[]
    session=SimpleNamespace(cycle=lambda:(calls.append('cycle'),stop.set()))
    runtime=LiveRuntime(session,None,None,None,None,None,results=SimpleNamespace(save=lambda:calls.append('save')))
    runtime.close=lambda *,clean=True:calls.append(('close',clean))
    runtime.run(stop)
    assert calls==['cycle','save','save',('close',True)]


def test_result_export_failure_pauses_and_stops_the_runtime(live):
    session=live_session(live);session.startup();cycles=[];closed=[]
    session.cycle=lambda:cycles.append('cycle')
    def fail():raise OSError('storage-full')
    runtime=LiveRuntime(session,None,None,None,live.journal,None,results=SimpleNamespace(save=fail))
    runtime.close=lambda *,clean=True:closed.append(clean)
    with pytest.raises(ExchangeError,match='RESULTS_EXPORT_FAILED'):runtime.run(threading.Event())
    assert cycles==['cycle'] and closed==[False] and session.execution.entries_paused
    assert live.journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='RESULTS_EXPORT_FAILED'").fetchone()[0]>=1


def test_funnel_does_not_claim_zero_live_exchange_submissions():
    from opportunity_funnel import OpportunityFunnel
    assert OpportunityFunnel(source='EXCHANGE_REPORTED_RUNTIME').report()['exchange_orders_submitted'] is None
    report=OpportunityFunnel(source='OFFLINE_SIGNED_FIXTURE').report()
    assert report['exchange_orders_submitted']==0 and report['diagnostic_orders_submitted']==0


@pytest.mark.parametrize('xml,status',[
    ('<testsuites><testsuite tests="0"/></testsuites>','UNTESTED'),
    ('<testsuites><testsuite tests="2"><testcase name="a"/></testsuite></testsuites>','UNTESTED'),
    ('<testsuite tests="1"><testcase name="a"><failure/></testcase></testsuite>','BROKEN'),
    ('<testsuite tests="1"><testcase name="a"><error/></testcase></testsuite>','BROKEN'),
    ('<testsuite tests="1"><testcase name="a"><skipped/></testcase></testsuite>','PARTIAL'),
    ('<testsuite tests="1"><testcase name="a"/></testsuite>','UNIT_TESTED'),
    ('broken XML','BROKEN')])
def test_junit_counts_actual_testcases(tmp_path,xml,status):
    path=tmp_path/'tests.xml';path.write_text(xml)
    result=junit_evidence(path,expected_source_hash='current')
    assert result['status']==status and result['current_source_bound'] is False


@pytest.mark.parametrize('damage',['source','xml','scope','exit'])
def test_wrong_test_receipt_never_binds_to_current_code(tmp_path,damage):
    path=tmp_path/'tests.xml';path.write_text('<testsuite tests="1"><testcase name="a"/></testsuite>')
    receipt=dict(xml_sha256=sha(path),source_hash='current',suite_scope='FULL_REPOSITORY',command_exit_code=0)
    if damage=='source':receipt['source_hash']='old'
    if damage=='xml':receipt['xml_sha256']='wrong'
    if damage=='scope':receipt['suite_scope']='FOCUSED'
    if damage=='exit':receipt['command_exit_code']=1
    p=tmp_path/'receipt.json';p.write_text(json.dumps(receipt))
    assert not junit_evidence(path,p,expected_source_hash='current')['current_source_bound']


@pytest.mark.parametrize('mode,fill_source,fill_mode',[('LIVE_TESTNET','SYNTHETIC_SIGNED_FIXTURE','LIVE_TESTNET'),
    ('PAPER','LOCAL_BBO_SIMULATION','REPLAY'),('REPLAY','LOCAL_BBO_SIMULATION','PAPER')])
def test_mixed_or_synthetic_live_records_cannot_certify_practice(tmp_path,mode,fill_source,fill_mode):
    (tmp_path/'session_manifest.json').write_text(json.dumps(dict(execution_mode=mode,working_source_hash='current')))
    (tmp_path/'fills.jsonl').write_text(json.dumps(dict(execution_mode=fill_mode,source=fill_source))+'\n')
    result=session_evidence(tmp_path,current_source_hash='current')
    assert result['status']=='BROKEN' and result['certifies_practice'] is False


def test_self_reported_live_data_is_still_unverified(tmp_path):
    (tmp_path/'session_manifest.json').write_text(json.dumps(dict(execution_mode='LIVE_TESTNET',working_source_hash='current')))
    (tmp_path/'fills.jsonl').write_text(json.dumps(dict(execution_mode='LIVE_TESTNET',source='EXCHANGE_REPORTED',execution_source='EXCHANGE_REPORTED'))+'\n')
    result=session_evidence(tmp_path,current_source_hash='current')
    assert result['status']=='RECORDED_UNVERIFIED' and result['recorded_fill_count']==1
    assert result['certifies_practice'] is False


@pytest.mark.parametrize('mode',['PAPER','REPLAY'])
def test_existing_paper_replay_manifest_schema_is_supported(tmp_path,mode):
    (tmp_path/'session_manifest.json').write_text(json.dumps(dict(configuration={'execution_mode':mode},working_source_hash='current')))
    (tmp_path/'fills.jsonl').touch()
    result=session_evidence(tmp_path,current_source_hash='current')
    assert result['mode']==mode and result['status']=='RECORDED_SIMULATION' and result['source_compatible']
    assert result['recorded_fill_count']==0 and not result['certifies_practice']


def test_conflicting_manifest_modes_are_rejected(tmp_path):
    (tmp_path/'session_manifest.json').write_text(json.dumps(dict(execution_mode='LIVE_TESTNET',configuration={'execution_mode':'PAPER'})))
    assert session_evidence(tmp_path,current_source_hash='current')['status']=='BROKEN'


def test_audit_missing_measurements_are_null_and_cannot_activate(tmp_path):
    report=build_audit(ROOT)
    assert set(report['readiness'])==set(READINESS_KEYS)
    assert set(report['practice']['checks'])==set(PRACTICE_CHECKS)
    assert report['practice']['net_pnl'] is None and report['practice']['runtime_seconds'] is None
    assert report['verdict']=='ACCOUNT_SETUP_REQUIRED'
    assert not report['live_ready'] and not report['hackathon_ready'] and not report['live_orders_permitted']
    output=write_audit(report,tmp_path)
    assert (output/'jury_evidence_index.json').exists()
    assert json.loads((output/'jury_evidence_index.json').read_text())['measured_actual_trade_explanations'] is None


def test_failing_tests_produce_not_ready(tmp_path):
    path=tmp_path/'tests.xml';path.write_text('<testsuite tests="1"><testcase name="a"><failure/></testcase></testsuite>')
    report=build_audit(ROOT,tests_xml=path)
    assert report['verdict']=='NOT_READY' and 'TEST_EVIDENCE_FAILED' in report['problems']


def test_invalid_market_evidence_never_claims_healthy_public_data(tmp_path):
    path=tmp_path/'market.json';path.write_text(json.dumps(dict(network='mainnet',dex='',market_data_ready=True,metadata=[])))
    report=build_audit(ROOT,market_evidence=path)
    assert not report['market_observation']['market_discovery']
    assert report['readiness']['MARKET_DATA']['status']=='UNTESTED'
