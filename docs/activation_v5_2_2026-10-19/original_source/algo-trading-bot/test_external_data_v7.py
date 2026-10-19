"""OFFLINE_FIXTURE external provenance/isolation, never LIVE validation."""
from dataclasses import replace
from pathlib import Path
import ast
import pytest
from exchange.base_exchange import ExchangeError
from research_intelligence.external_data import (ResearchCandle,AssetMapping,RecordedMarketDataSource,
    HyperliquidReferenceSource,compare_sources)
from test_exchange_migration import NOW,candle_row
from test_market_resilience import engine,ready


def candle(**kw):
    fields=dict(source_id='FIXTURE',symbol='BTC',timestamp_ms=NOW-60000,close_timestamp_ms=NOW-1,
        open='50000',high='50002',low='49998',close='50000',volume='1',volume_units='BTC',
        price_units='USD_PER_BTC',observed_at_ms=NOW)
    return ResearchCandle(**dict(fields,**kw))


def mapping(**kw):
    fields=dict(native_symbol='par:BTC',source_id='FIXTURE',source_symbol='BTC',price_units='USD_PER_BTC',
        volume_units='BTC',comparable_volume=True,review_reference='OFFLINE_FIXTURE_ONLY',
        instrument_status='EXTERNAL_SOURCE_VALIDATED_FOR_RESEARCH')
    return AssetMapping(**dict(fields,**kw))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests,websocket
    def reject(*a,**kw):raise AssertionError('EXTERNAL_FIXTURE_NETWORK_FORBIDDEN')
    monkeypatch.setattr(requests,'post',reject)
    monkeypatch.setattr(requests.Session,'post',reject)
    monkeypatch.setattr(websocket,'create_connection',reject)


def test_disabled_default_and_no_order_interface():
    with pytest.raises(ExchangeError,match='DISABLED'):RecordedMarketDataSource([candle()])
    with pytest.raises(ExchangeError,match='DISABLED'):HyperliquidReferenceSource(rates=None,clock_ms=lambda:NOW)
    source=RecordedMarketDataSource([candle()],research_enabled=True)
    for name in ('place_order','cancel_order','get_position','get_equity','publish_public_snapshot'):
        assert not hasattr(source,name)


@pytest.mark.parametrize('fields',[{'source_id':''},{'symbol':'par:BTC'},{'volume_units':''},
    {'price_units':''},{'timestamp_ms':NOW+1},{'observed_at_ms':NOW-1},{'high':'1'}])
def test_provenance_boundaries_and_bad_data_fail(fields):
    with pytest.raises(ExchangeError):candle(**fields)


@pytest.mark.parametrize('fields',[{'review_reference':None},{'source_symbol':'ETH'},
    {'price_units':'USDT_PER_BTC'},{'instrument_status':'UNVERIFIED'},{'native_symbol':'par:UNKNOWN'}])
def test_invalid_mapping_or_units_rejected(fields):
    with pytest.raises(ExchangeError):mapping(**fields).validate(candle())


@pytest.mark.parametrize('fields',[{'volume':None},{'volume_units':'TICK'}])
def test_missing_or_tick_volume_cannot_enter_vwap(fields):
    with pytest.raises(ExchangeError,match='VOLUME'):mapping().validate(candle(**fields),for_vwap=True)


def test_wrong_fx_direction_cannot_silently_invert():
    c=candle(symbol='EURUSD',price_units='USD_PER_EUR')
    m=mapping(native_symbol='par:USDEUR',source_symbol='EURUSD',price_units='USD_PER_EUR',fx_direction='EUR_PER_USD')
    with pytest.raises(ExchangeError,match='FX_DIRECTION'):m.validate(c)


def test_external_record_cannot_overwrite_native_cache_or_account_truth():
    _,e=engine();ready(e);before=dict(e.candles['par:BTC'])
    with pytest.raises(ExchangeError,match='IDENTITY'):
        e.publish_public_snapshot('par:BTC',[candle()]*300,e.books['par:BTC'],e.contexts['par:BTC'],NOW)
    assert e.candles['par:BTC']==before
    result=compare_sources(e.get_completed_candles('par:BTC'),[candle()],mapping(),decision_ms=NOW)
    assert result['execution_truth']=='NATIVE_PAR_ONLY' and result['accounting_truth']=='NATIVE_EXCHANGE_ONLY'
    assert result['hypothetical_fills'] is None and result['risk_adjusted_outcomes'] is None


def test_as_of_reception_prevents_future_leakage_and_stale_signal():
    _,e=engine();ready(e)
    c=candle(observed_at_ms=NOW+1000)
    result=compare_sources(e.get_completed_candles('par:BTC'),[c],mapping(),decision_ms=NOW)
    assert result['matched_count']==0 and result['external_stale']
    result=compare_sources(e.get_completed_candles('par:BTC'),[candle()],mapping(),decision_ms=NOW+120001)
    assert result['external_stale'] and result['indicator_comparison'] is None


def test_research_outage_does_not_change_native_engine():
    _,e=engine();ready(e);before=dict(e.candles['par:BTC'])
    class Rates:
        def read(self,q,op,**kw):return op()
    def failure(payload):raise ExchangeError('EXTERNAL_PROVIDER_OUTAGE')
    source=HyperliquidReferenceSource(rates=Rates(),clock_ms=lambda:NOW,research_enabled=True,transport=failure)
    with pytest.raises(ExchangeError,match='OUTAGE'):source.get_candles('BTC',NOW-60000,NOW-1)
    assert e.candles['par:BTC']==before and e.market_health()['par:BTC']['healthy']


def test_reference_adapter_can_only_read_allowlisted_public_metadata_and_candles():
    class Rates:
        def read(self,q,op,**kw):return op()
    calls=[]
    def info(p):
        calls.append(p)
        return {'universe':[{'name':'BTC'}]} if p['type']=='meta' else [dict(candle_row(NOW-60000),s='BTC')]
    s=HyperliquidReferenceSource(rates=Rates(),clock_ms=lambda:NOW,research_enabled=True,transport=info)
    bars=s.get_candles('BTC',NOW-60000,NOW-1)
    assert bars[0].symbol=='BTC' and bars[0].source_id==s.source_id
    assert [p['type'] for p in calls]==['meta','candleSnapshot']
    with pytest.raises(ExchangeError):s.get_candles('par:BTC',NOW-60000,NOW-1)
    with pytest.raises(ExchangeError):s._read({'type':'order'})


def test_production_cannot_enable_external_mode_or_approve_itself(monkeypatch):
    from venue_config import require_paper_migration,MigrationPolicyError
    monkeypatch.setenv('SIGNAL_DATA_MODE','EXTERNAL');
    with pytest.raises(MigrationPolicyError,match='NATIVE_SIGNAL'):require_paper_migration()
    monkeypatch.setenv('SIGNAL_DATA_MODE','PAR_NATIVE_ONLY');monkeypatch.setenv('EXTERNAL_SIGNAL_LIVE_APPROVED','true')
    with pytest.raises(MigrationPolicyError,match='NATIVE_SIGNAL'):require_paper_migration()


def test_no_production_import_of_external_research_module():
    root=Path(__file__).parent
    for path in list((root/'exchange').glob('*.py'))+[root/'market_regime_scanner.py',root/'crypto_paper_bot.py',root/'market_stream.py']:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom):assert 'external_data' not in (node.module or '')
            if isinstance(node,ast.Import):assert all('external_data' not in x.name for x in node.names)


def test_research_features_cannot_shorten_full_utc_contract_to_300_bars():
    from research_intelligence.external_data import require_feature_history
    bars=[candle(timestamp_ms=NOW-i*60000,close_timestamp_ms=NOW-i*60000+59999)
        for i in range(300,0,-1)]
    with pytest.raises(ExchangeError,match='FULL_UTC'):require_feature_history(bars,NOW)


def test_native_quote_mark_context_must_also_be_fresh():
    _,e=engine();ready(e);q=e.get_quote('par:BTC')
    q=replace(q,mark_timestamp_ms=NOW-60001)
    result=compare_sources(e.get_completed_candles('par:BTC'),[candle()],mapping(),decision_ms=NOW,quote=q)
    assert result['native_execution_quote'] is None
