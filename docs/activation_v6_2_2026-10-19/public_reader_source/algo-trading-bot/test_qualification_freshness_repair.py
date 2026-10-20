"""Signing-time expiration, same-wire reacquisition and conservative recovery.
All signatures are ephemeral; synthetic outcomes cannot certify actual trading.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal as D
import json,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal,fingerprint
from exchange.qualification_intent_recovery import (assess,append_resolution,effective_rows,
    ORIGINAL_CLOID,ORIGINAL_PROPOSAL,ORIGINAL_SESSION,ROOT)
from exchange.qualification_signing_boundary import context_ages
from exchange.sdk_transport import OfficialSDKTransport
from test_delegated_qualification import delegated,bounded,emergency,live
from test_exchange_migration import NOW


def expire_at_signing(c,monkeypatch,*,change=None,at=3):
    original=c.live.executor.signing_boundary.refresh_permit;calls=[]
    def refresh(permit,action):
        calls.append(1)
        if len(calls)==at:
            c.live.fixture.now+=6000;c.live.fixture.book['time']=c.live.fixture.now
            if change:change()
        return original(permit,action)
    monkeypatch.setattr(c.live.executor.signing_boundary,'refresh_permit',refresh)
    return calls


def test_readiness_expiring_after_nonce_reacquires_real_account_and_same_wire(delegated,monkeypatch):
    c=delegated;old=c.context.readiness.observed_ms;expire_at_signing(c,monkeypatch)
    result=c.sequence.run()
    assert result['status']=='TRADE_CLOSED_RECONCILED',result
    assert len(c.venue.calls)==2 and result['final_flat']
    assert c.context.readiness.observed_ms==old
    records=[json.loads(v) for v, in c.live.journal.db.execute("SELECT data FROM events WHERE kind='QUALIFICATION_FRESH_ACCOUNT_ACQUIRED'")]
    assert records and records[0]['retimestamped'] is False
    assert records[0]['readiness']['observed_ms']==NOW+6000
    assert all(age is not None and 0<=age<=5000 for age in records[0]['ages_ms'].values())
    assert D(c.venue.calls[0]['orders'][0]['s'])==D('.0002')
    assert not result['certification_passed'] and not result['protection_accepted']


@pytest.mark.parametrize('which',['position','open_order','failed_read','price_jump','source_change','revocation'])
def test_reacquisition_never_overrides_changed_account_market_or_authority(delegated,monkeypatch,which):
    c=delegated
    def change():
        if which=='position':c.live.fixture.position('.0001','83500')
        if which=='open_order':c.live.fixture.orders=[dict(coin='par:BTC',oid=999,side='B',sz='.0001',
            origSz='.0001',limitPx='83440',isTrigger=False,reduceOnly=False,cloid='0x'+'a'*32,timestamp=c.live.fixture.now)]
        if which=='failed_read':c.venue.rest_down=True
        if which=='price_jump':c.live.fixture.book['levels']=[[dict(px='84980',sz='.1')],[dict(px='85000',sz='.1')]]
        if which=='source_change':c.auth.source_hash=lambda:'changed-source'
        if which=='revocation':c.acceptance_path.with_name('session_revocation.json').write_text('{}')
    expire_at_signing(c,monkeypatch,change=change)
    result=c.sequence.run()
    assert result['status']=='EMERGENCY_EXIT_REQUIRED',result
    assert not c.venue.calls and not result.get('final_flat')
    assert c.live.journal.intents()[0]['state']=='UNKNOWN'


def test_duplicate_callbacks_do_not_allocate_extra_nonces_or_entries(delegated,monkeypatch):
    c=delegated;calls=expire_at_signing(c,monkeypatch,at=99)
    nonces=[];original=c.live.nonces.next
    def next_nonce():
        value=original();nonces.append(value);return value
    monkeypatch.setattr(c.live.nonces,'next',next_nonce)
    assert c.sequence.run()['status']=='TRADE_CLOSED_RECONCILED'
    assert len(calls)>2
    assert len([a for a in c.venue.calls if not a['orders'][0]['r']])==1
    assert len(nonces)==2 and nonces[1]>nonces[0]


def test_rejected_pre_http_after_nonce_preserves_uncertainty_and_does_not_retry(delegated,monkeypatch):
    c=delegated;expire_at_signing(c,monkeypatch,change=lambda:setattr(c.venue,'rest_down',True))
    nonces=[];original=c.live.nonces.next
    def next_nonce():
        value=original();nonces.append(value);return value
    monkeypatch.setattr(c.live.nonces,'next',next_nonce)
    result=c.sequence.run();assert result['status']=='EMERGENCY_EXIT_REQUIRED'
    assert len(nonces)==1
    assert not c.venue.calls and not c.live.journal.control('qualification_entry_consumed')
    count=len(c.venue.calls)
    assert c.sequence.run()['status']=='EMERGENCY_EXIT_REQUIRED' and len(c.venue.calls)==count


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_fresh_boundary_zero_partial_full_fill_retains_one_entry(delegated,monkeypatch,fraction):
    c=delegated;c.venue.partial_entry=D(fraction);expire_at_signing(c,monkeypatch)
    result=c.sequence.run()
    assert result['status']==('NO_FILL_VERIFIED' if fraction=='0' else 'TRADE_CLOSED_RECONCILED'),result
    assert len([a for a in c.venue.calls if not a['orders'][0]['r']])==1
    if fraction!='0':assert D(c.venue.calls[-1]['orders'][0]['s'])==D('.0002')*D(fraction)


def test_five_second_age_requirement_is_not_changed():
    from exchange.qualification_signing_boundary import fresh
    ctx=SimpleNamespace(readiness=SimpleNamespace(observed_ms=NOW),account_ms=NOW,
        quote=SimpleNamespace(timestamp_ms=NOW,mark_timestamp_ms=NOW))
    assert fresh(ctx,NOW+5000) and not fresh(ctx,NOW+5001)
    assert context_ages(ctx,NOW+5001)['readiness']==5001 and ctx.readiness.observed_ms==NOW


@pytest.mark.parametrize('gate',['startup','client','feed','backoff','agent_expired','validation_age'])
def test_fresh_frame_keeps_all_original_signing_health_gates(delegated,gate):
    c=delegated;e=c.live.executor;context=c.context
    request=c.live.client.market('par:BTC').normalize_order('BUY','.0002',c.p.entry_limit,tif='Ioc')
    checked=c.live.fixture.now
    if gate=='startup':e.recovery.startup_coordinator=SimpleNamespace(entry_ready=False)
    if gate=='client':e.client.ready=False
    if gate=='feed':e.context_provider.feed_ready=lambda:False
    if gate=='backoff':e.rate_limits.backoff_until=checked+1
    if gate=='agent_expired':context=replace(context,readiness=replace(context.readiness,agent_expiry_ms=checked))
    if gate=='validation_age':checked-=5001
    e.signing_boundary.current=dict(request=request,context=context,checked_ms=checked)
    with pytest.raises(ExchangeError):e._guard(context,checked,entry=True,entry_request=request)
    assert not c.venue.calls


def proof_fixture():
    p=ROOT/'docs/readiness_repair_2026-10-14/unknown_review_v2/recovery_report.json'
    proof=json.loads(p.read_text())['proof'];proof['mode']='OFFLINE_FIXTURE';return proof


@pytest.mark.parametrize('damage',['claim','consumed','http_started','no_guard','no_nonce','wrong_nonce',
    'filled_oid','wrong_request','positions','orders','fills','status','incomplete_history','stale','wrong_source'])
def test_unknown_cannot_be_resolved_from_flatness_or_missing_records_alone(damage):
    proof=proof_fixture();now=proof['account_observations'][-1]['observed_ms']
    if damage=='claim':proof['local']['transmission_claim']=[dict(hash='anything')]
    if damage=='consumed':proof['local']['original_entry_consumed']=True
    if damage=='http_started':proof['local']['events'].append(dict(kind='QUALIFICATION_TRANSPORT_BOUNDARY',
        ms=now,data=dict(stage='HTTP_POST_STARTED',cloid=ORIGINAL_CLOID)))
    if damage=='no_guard':proof['local']['events']=[e for e in proof['local']['events'] if e['kind']!='P0_ENTRY_PRICE_GUARD']
    if damage=='no_nonce':proof['local']['events']=[e for e in proof['local']['events'] if e['kind']!='NONCE_GENERATED']
    if damage=='wrong_nonce':proof['nonce_record']['signer']='0x'+'1'*40
    if damage=='filled_oid':proof['local']['original_row']['oid']='11'
    if damage=='wrong_request':proof['local']['original_row']['request']='{}'
    if damage=='positions':proof['account_observations'][1]['positions_after']=[dict(quantity='.0001')]
    if damage=='orders':proof['account_observations'][0]['orders']=[dict(oid=999)]
    if damage=='fills':proof['account_observations'][0]['all_historical_fills']=[dict(oid=999)]
    if damage=='status':proof['account_observations'][0]['original_status']=dict(status='order')
    if damage=='incomplete_history':proof['account_observations'][0]['history_start_ms']=now-1000
    if damage=='stale':now+=5001
    if damage=='wrong_source':proof['source']['source_hash']='other'
    assert not assess(proof,now_ms=now)['certified']


def journal_with_original(tmp_path,proof):
    journal=ExecutionJournal(tmp_path/'recovery.sqlite',session_id='offline:recovery',team_address=proof['team'])
    row=proof['local']['original_row'];names=[x[1] for x in journal.db.execute('PRAGMA table_info(intents)')]
    journal.db.execute('INSERT INTO intents VALUES ('+','.join('?' for _ in names)+')',[row[k] for k in names])
    return journal


def test_append_only_resolution_keeps_unknown_row_and_all_events(tmp_path):
    proof=proof_fixture();journal=journal_with_original(tmp_path,proof)
    try:
        original=journal.intent(proof['local']['original_row']['intent_key'])
        result=append_resolution(journal,proof,proof['account_observations'][-1]['observed_ms'])
        assert result['certified'] and journal.intent(original['intent_key'])==original
        assert journal.intents()[0]['state']=='UNKNOWN' and effective_rows(journal.db)==[]
        assert journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='UNKNOWN_INTENT_NONTRANSMISSION_CERTIFIED'").fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError):journal.db.execute('DELETE FROM nontransmission_resolutions')
        with pytest.raises(sqlite3.IntegrityError):journal.db.execute("UPDATE nontransmission_resolutions SET checksum='fake'")
    finally:journal.close()


def test_resolution_invalidates_if_original_row_or_transmission_evidence_changes(tmp_path):
    proof=proof_fixture();journal=journal_with_original(tmp_path,proof)
    try:
        append_resolution(journal,proof,proof['account_observations'][-1]['observed_ms'])
        journal.control('certification_transmissions:'+ORIGINAL_PROPOSAL,[dict(hash='new-positive-claim')])
        with pytest.raises(ExchangeError):effective_rows(journal.db)
    finally:journal.close()


def test_synthetic_resolution_cannot_be_applied_to_real_session_identity(tmp_path):
    proof=proof_fixture();journal=ExecutionJournal(tmp_path/'real_identity.sqlite',
        session_id='anchorium-one-qualification-v1',team_address=proof['team'])
    try:
        with pytest.raises(ExchangeError,match='ACTUAL_NONTRANSMISSION'):append_resolution(journal,proof,proof['account_observations'][-1]['observed_ms'])
    finally:journal.close()


@pytest.mark.parametrize('response',['success','timeout','non200'])
def test_transport_boundary_distinguishes_actual_http_initiation(response):
    transport=OfficialSDKTransport.__new__(OfficialSDKTransport);events=[]
    transport.check=lambda action:None
    def post(*a,**k):
        if response=='timeout':raise TimeoutError('SYNTHETIC_HTTP_UNCERTAIN')
        return SimpleNamespace(status_code=200 if response=='success' else 503,json=lambda:dict(status='ok'))
    transport._sdk=SimpleNamespace(session=SimpleNamespace(post=post))
    transport.record_transport_boundary=lambda stage,payload,**details:events.append(stage)
    payload=dict(action=dict(type='order'))
    if response=='success':assert transport.transmit(payload)==dict(status='ok')
    else:
        with pytest.raises((TimeoutError,ExchangeError)):transport.transmit(payload)
    assert events[0]=='HTTP_POST_STARTED'
    assert events[-1]==('HTTP_POST_UNCERTAIN' if response=='timeout' else 'HTTP_POST_RESPONSE')


def observer_fixture(c,monkeypatch,tmp_path):
    import exchange.persistent_qualification_watcher as module
    import exchange.practice_preflight as preflight
    session=SimpleNamespace(client=c.live.client,account=c.live.account,market=c.live.market,
        recovery=c.live.executor.recovery,provider=c.live.provider,clock=c.live.clock,rates=c.live.rate,
        api=c.p.api_wallet,team=c.p.team_wallet,journal=c.live.journal,
        start=lambda:None,verify_signer=lambda:None,close=lambda:None,
        _reconcile=c.live.executor.recovery.recover)
    class Stream:
        thread=None
        def __init__(self,*a,**k):self.closed=False
        def start(self):pass
        def report(self):return dict(connected=True,attempts=1,exchange_actions=0)
        def close(self):self.closed=True
        def snapshot(self,symbol):return c.live.provider.last_book
    monkeypatch.setattr(module,'ReadOnlyQualificationSession',lambda *a,**k:session)
    monkeypatch.setattr(module,'PublicBookStream',Stream)
    monkeypatch.setattr(module,'NonceManager',lambda *a,**k:c.live.nonces)
    monkeypatch.setattr(module,'source_unchanged',lambda *a:None)
    monkeypatch.setattr(preflight,'verify_private_identity',lambda *a,**k:dict(status='MATCH',signature_created=False))
    observer=module.PersistentQualificationObserver(tmp_path,tmp_path/'watch','fixture-source','fixture-policy')
    observer.start();return observer,module


def test_persistent_repeated_public_observations_never_submit_order(delegated,monkeypatch,tmp_path):
    c=delegated;observer,module=observer_fixture(c,monkeypatch,tmp_path)
    try:
        candidates=[observer.poll() for _ in range(4)]
        assert observer.observations==4 and sum(p is not None for p in candidates)==1
        assert not c.venue.calls and not c.live.journal.intents()
        assert not c.live.nonces.db.execute('SELECT last FROM nonces').fetchall()
        assert len((observer.directory/'observations.jsonl').read_text().splitlines())==4
    finally:observer.close()
    assert json.loads((observer.directory/'health.json').read_text())['status']=='READ_ONLY_STOPPED'


@pytest.mark.parametrize('which',['wide_spread','thin_depth','no_book','wrong_quantity'])
def test_ineligible_market_keeps_observer_alive_without_attempt(delegated,monkeypatch,tmp_path,which):
    c=delegated;observer,module=observer_fixture(c,monkeypatch,tmp_path)
    if which in {'wide_spread','thin_depth','wrong_quantity'}:
        from exchange.base_exchange import BookLevel
        book=c.live.provider.last_book
        if which=='wide_spread':book=replace(book,asks=(BookLevel(D('85000'),D('.1')),))
        if which=='thin_depth':book=replace(book,asks=(BookLevel(D('83440'),D('.0001')),))
        if which=='wrong_quantity':book=replace(book,bids=(BookLevel(D('100100'),D('1')),),asks=(BookLevel(D('100120'),D('1')),))
        c.live.provider.last_book=book
    else:monkeypatch.setattr(observer.reader,'get',lambda *a:(None,'NO_FRESH_BOOK'))
    try:
        assert observer.poll() is None and observer.poll() is None
        assert observer.observations==2 and not c.venue.calls and not c.live.journal.intents()
    finally:observer.close()


def test_persistent_account_change_is_fatal_not_market_retry(delegated,monkeypatch,tmp_path):
    c=delegated;observer,module=observer_fixture(c,monkeypatch,tmp_path);c.live.fixture.position('.0001','83500')
    try:
        with pytest.raises(ExchangeError):observer.poll()
        assert not c.venue.calls
    finally:observer.close()


def test_persistent_nonce_lease_failure_blocks_before_market_poll(delegated,monkeypatch,tmp_path):
    c=delegated;observer,module=observer_fixture(c,monkeypatch,tmp_path);c.live.nonces.close()
    try:
        with pytest.raises(ExchangeError,match='SIGNER_LEASE'):observer.poll()
    finally:observer.close()


def test_observation_logs_are_appended_across_read_only_restart(delegated,monkeypatch,tmp_path):
    c=delegated;directory=tmp_path/'watch';directory.mkdir()
    (directory/'health.json').write_text(json.dumps(dict(observations=12,status='READ_ONLY_OBSERVATION')))
    (directory/'events.jsonl').write_text('{"event":"OLDER_PRESERVED"}\n')
    observer,module=observer_fixture(c,monkeypatch,tmp_path)
    try:
        observer.poll();assert observer.observations==13
        assert (directory/'events.jsonl').read_text().startswith('{"event":"OLDER_PRESERVED"}')
    finally:observer.close()


def test_execution_handoff_preserves_shared_rate_usage_and_closes_receiver(delegated,monkeypatch,tmp_path):
    c=delegated;observer,module=observer_fixture(c,monkeypatch,tmp_path)
    c.live.rate.weights.append((c.live.fixture.now,17))
    try:
        shared=observer.pause_for_execution()
        assert shared is c.live.rate and shared._usage()>=17
        assert observer.stream.closed and observer.nonce_owner() is c.live.nonces
        assert not c.venue.calls
    finally:observer.close()


def test_after_crash_persistent_runner_cannot_resume_signing(delegated,monkeypatch,tmp_path):
    from test_delegated_qualification import runner_fixture
    import exchange.persistent_qualification_watcher as watcher_module
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path)
    destination=tmp_path/'restart';state=destination/'persistent_observer';state.mkdir(parents=True)
    (state/'health.json').write_text(json.dumps(dict(status='READ_ONLY_OBSERVATION',observations=5)))
    class Observer:
        def __init__(self,*a,**k):pass
        def start(self):pass
        def poll(self):clock[0]=c.m.expires_ms-60000;return c.p
        def close(self):(state/'health.json').write_text(json.dumps(dict(status='READ_ONLY_STOPPED')))
    monkeypatch.setattr(watcher_module,'PersistentQualificationObserver',Observer)
    def forbidden(*a,**k):raise AssertionError('CRASH_MUST_NOT_AUTOMATICALLY_RESUME_SIGNING')
    monkeypatch.setattr(module,'build_runtime',forbidden)
    result=module.execute_persistent_session(destination,c.delegation,tmp_path/'receipt')
    assert result['restart_is_read_only'] and not result['authorized_entry_attempted']
    assert result['status']=='SESSION_ENTRY_WINDOW_CLOSED_NO_SUBMISSION'
