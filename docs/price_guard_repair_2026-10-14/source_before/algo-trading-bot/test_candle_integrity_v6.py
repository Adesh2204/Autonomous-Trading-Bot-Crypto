"""Labeled OFFLINE_FIXTURE and RECORDED_EXCHANGE_REPLAY; network forbidden."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
from exchange.base_exchange import Candle,ExchangeError,decimal
from exchange.candle_audit import PublicCandleAudit,merge_candle
from exchange.scanner_numeric import scanner_number
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy
from test_market_resilience import engine,ready
from test_exchange_migration import candle_row,NOW

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests,websocket
    def reject(*a,**k):raise AssertionError('OFFLINE_TEST_NETWORK_FORBIDDEN')
    monkeypatch.setattr(requests.Session,'post',reject)
    monkeypatch.setattr(websocket,'create_connection',reject)


@pytest.mark.parametrize('name',['brent','ewy'])
def test_recorded_zero_atr_is_valid_but_never_qualified(name,monkeypatch,record_property):
    record_property('evidence_class','RECORDED_EXCHANGE_REPLAY')
    row=json.loads((ROOT/'docs/candle_integrity_v6_2026-10-10'/f'{name}_numeric_candles.json').read_text())
    candles=[Candle(**{k:(decimal(v) if k in {'open','high','low','close','volume'} else v)
        for k,v in c.items() if k in Candle.__dataclass_fields__}) for c in row['candles']]
    source,e=engine();source.now=row['scan_observed_at_ms'];source.book['time']=source.now
    price=candles[-1].close
    source.book['levels'][0][0]['px']=str(price-Decimal('.001'))
    source.book['levels'][1][0]['px']=str(price+Decimal('.001'))
    monkeypatch.setattr(e.market,'get_candles',lambda symbol,*a,**kw:candles if symbol==row['symbol'] else [])
    s=MarketRegimeScanner(e.market,ScannerPolicy('.004',15,0,10));scan=s.scan()
    d=next(d for d in scan.diagnostics if d.symbol==row['symbol'])
    assert d.metrics['atr']==0 and d.metrics['atr_fraction']==0
    assert d.evidence['numeric_fields']['ATR_14']['valid']
    assert 'ATR_BELOW_BASELINE_SCANNER_FLOOR' in d.reasons
    assert not d.qualified and not scan.watchlist
    assert not any('INVALID' in r for r in d.reasons)


@pytest.mark.parametrize('value,field,nonnegative',[('NaN','ATR_14',True),('Infinity','Close',False),('-1','ATR_14',True),('0','VWAP',False)])
def test_invalid_numeric_field_records_exact_operand_and_fails_closed(value,field,nonnegative,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');evidence={}
    with pytest.raises(ExchangeError,match='SCANNER_NUMERIC_INVALID:'+field):
        scanner_number(value,field,evidence,nonnegative=nonnegative)
    assert evidence['numeric_fields'][field]['operand']==value
    assert not evidence['numeric_fields'][field]['valid']


def test_gapped_rest_response_can_join_retained_genuine_rows(record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');source,e=engine();ready(e)
    missing=NOW-120000;del e.candles['par:BTC'][missing]
    retained=NOW-600000
    source.history=[candle_row(t) for t in range(NOW-300*60000,NOW,60000) if t!=retained]
    e.reconcile_history(symbols=['par:BTC'])
    assert e.market_health()['par:BTC']['healthy']
    assert missing in e.candles['par:BTC'] and retained in e.candles['par:BTC']
    assert len(e.get_completed_candles('par:BTC'))==300


@pytest.mark.parametrize('kind',['WS','REST','SCANNER'])
def test_completed_conflict_preserves_cache_and_blocks_only_affected_symbol(kind,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');source,e=engine();ready(e)
    before=e.candles['par:BTC'][NOW-60000]
    if kind=='WS':assert e.ingest({'channel':'candle','data':candle_row(NOW-60000,close='50001')}) is False
    elif kind=='REST':
        source.history=[candle_row(t,close='50001') for t in range(NOW-3*60000,NOW,60000)]
        e.reconcile_history(symbols=['par:BTC'])
    else:
        bars=e.get_completed_candles('par:BTC');bars[-1]=replace(bars[-1],close=Decimal('50001'))
        with pytest.raises(ExchangeError,match='CONFLICTING_COMPLETED_CANDLES'):
            e.publish_public_snapshot('par:BTC',bars,e.books['par:BTC'],e.contexts['par:BTC'],NOW)
        e.note_scanner_failure('par:BTC','CONFLICTING_COMPLETED_CANDLES')
    assert e.candles['par:BTC'][NOW-60000]==before
    assert not e.market_health()['par:BTC']['healthy']
    assert e.market_health()['par:ETH']['healthy']


def test_open_row_can_evolve_but_cannot_replace_final_fact(record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');_,e=engine();ready(e)
    final=e.candles['par:BTC'][NOW-60000]
    partial=replace(final,close=Decimal('50001'),received_timestamp_ms=NOW-30000)
    assert merge_candle(final,partial,NOW)==final
    assert merge_candle(partial,final,NOW)==final
    newer=replace(partial,close=Decimal('50002'),received_timestamp_ms=NOW-10000)
    assert merge_candle(partial,newer,NOW-1)==newer


def test_audit_stages_use_same_request_and_never_capture_account_payload(tmp_path,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');source,e=engine()
    audit=PublicCandleAudit(tmp_path/'public.jsonl');e.client.candle_audit=audit
    e.market.get_candles('par:BTC',NOW-300*60000,NOW-1,now_ms=NOW)
    e.client.post_info('userAbstraction',user='0x'+'1'*40)
    rows=[json.loads(l) for l in audit.path.read_text().splitlines()]
    assert [r['stage'] for r in rows]==['RAW_REST','NORMALIZED_REST']
    assert rows[0]['request']['req']['startTime']==rows[1]['start_ms']
    assert len(rows[0]['response'])==len(rows[1]['candles'])==300
    assert 'userAbstraction' not in audit.path.read_text()


def test_audit_size_limit_fails_explicitly(tmp_path,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');a=PublicCandleAudit(tmp_path/'audit',max_bytes=1)
    with pytest.raises(ExchangeError,match='PUBLIC_CANDLE_AUDIT_SIZE_LIMIT'):a.record('CACHE')
    assert not a.path.exists()


def test_public_only_config_never_reads_dotenv(monkeypatch,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE')
    import importlib,venue_config,dotenv
    def forbidden(*a,**k):raise AssertionError('PUBLIC_ONLY_MUST_NOT_READ_WALLET_SETTINGS')
    monkeypatch.setenv('ANCHORIUM_PUBLIC_ONLY','true')
    monkeypatch.setattr(dotenv,'dotenv_values',forbidden)
    importlib.reload(venue_config)
    assert venue_config._defaults=={}
    assert venue_config.require_paper_migration()['ALLOW_LIVE_ORDERS'] is False


def test_ws_batch_audit_preserves_original_payload_once(tmp_path,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');_,e=engine();ready(e)
    a=PublicCandleAudit(tmp_path/'ws.jsonl');e.client.candle_audit=a
    message={'channel':'candle','data':[candle_row(NOW-60000),candle_row(NOW-60000,'par:ETH')]}
    e.ingest(message)
    records=[json.loads(l) for l in a.path.read_text().splitlines()]
    raw=[r for r in records if r['stage']=='RAW_WS']
    assert len(raw)==1 and raw[0]['message']==message
    assert len([r for r in records if r['stage']=='WS_MERGE'])==2


@pytest.mark.parametrize('reason',['CONFLICTING_COMPLETED_CANDLES','SCANNER_NUMERIC_INVALID:VWAP:NONFINITE_OR_NOT_DECIMAL'])
def test_scanner_integrity_latch_requires_validated_snapshot_to_restore(reason,record_property):
    record_property('evidence_class','OFFLINE_FIXTURE');_,e=engine();ready(e)
    from opportunity_funnel import reason_code
    assert reason_code(reason)=='INVALID_MARKET_DATA'
    e.note_scanner_failure('par:BTC',reason)
    assert not e.market_health()['par:BTC']['healthy'] and e.market_health()['par:ETH']['healthy']
    e.publish_public_snapshot('par:BTC',e.get_completed_candles('par:BTC'),e.books['par:BTC'],e.contexts['par:BTC'],NOW)
    assert e.market_health()['par:BTC']['healthy']
    e.note_scanner_failure('par:BTC','ATR_BELOW_BASELINE_SCANNER_FLOOR')
    assert e.market_health()['par:BTC']['healthy']
