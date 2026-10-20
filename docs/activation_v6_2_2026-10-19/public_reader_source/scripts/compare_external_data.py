"""One bounded, explicitly enabled public research capture. Never runs trading."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--research-enabled',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--symbols',nargs='+',default=['par:BTC','par:ETH','par:HYPE'])
    a=p.parse_args()
    if not a.research_enabled:p.error('Research is disabled by default; explicit --research-enabled required')
    if a.output.exists():p.error('Use a new output directory to preserve evidence')
    from venue_config import require_paper_migration
    from exchange.paper_operations import PaperOwner,atomic_json,active_source_hash
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.hyperliquid_market_data import HyperliquidMarketData,make_quote
    from exchange.execution_journal import ExecutionJournal
    from exchange.rate_limits import HyperliquidRateLimitManager
    from research_intelligence.external_data import HyperliquidReferenceSource,AssetMapping,compare_sources
    from session_manager import SessionManager
    require_paper_migration()
    if json.loads((ROOT/'configs/reliability_policy.json').read_text())['protection']['enabled']:
        p.error('Protection must remain disabled')
    # A research capture does not run alongside an owned PAPER collector.
    import fcntl
    for lock in (ROOT/'runtime/paper').rglob('*owner.lock'):
        with lock.open('r') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
            except BlockingIOError:p.error('Active PAPER owner: '+str(lock))
    mapping={'par:BTC':('BTC','USD_PER_BTC'),'par:ETH':('ETH','USD_PER_ETH'),
        'par:HYPE':('HYPE','USD_PER_HYPE'),'par:SP500':('xyz:SP500','INDEX_POINTS'),
        'par:EWY':('xyz:EWY','USD_PER_SHARE'),'par:EWJ':('xyz:EWJ','USD_PER_SHARE'),
        'par:BRENT':('xyz:BRENTOIL','USD_PER_BARREL'),'par:GOLD':('xyz:GOLD','USD_PER_TROY_OUNCE'),
        'par:USDEUR':('xyz:EUR','USD_PER_EUR'),'par:USDJPY':('xyz:JPY','JPY_PER_USD')}
    if len(set(a.symbols))!=len(a.symbols) or not set(a.symbols)<=mapping.keys():p.error('Explicit official par symbols only')
    a.output.mkdir(parents=True)
    owner=PaperOwner(ROOT/'runtime/paper/external-research-owner.lock')
    clock=lambda:time.time_ns()//1000000
    journal=ExecutionJournal(a.output/'research_reads.sqlite',session_id='v7-external-public-research',team_address='0x'+'0'*40)
    rates=HyperliquidRateLimitManager(journal)
    client=HyperliquidClient(rate_limits=rates);market=HyperliquidMarketData(client)
    def public_reference_read(payload):
        # Research libraries cannot import a network client. This standalone
        # public collector has a fixed read endpoint and no execution transport.
        if payload.get('type') not in {'meta','candleSnapshot'}:
            raise RuntimeError('EXTERNAL_PUBLIC_READ_ONLY')
        import requests
        from exchange.base_exchange import ExchangeError
        try:
            response=requests.post(HyperliquidReferenceSource.URL,json=payload,
                timeout=(5,10),allow_redirects=False)
            response.raise_for_status();return response.json()
        except requests.RequestException:raise ExchangeError('EXTERNAL_PUBLIC_READ_FAILED') from None
    reference=HyperliquidReferenceSource(rates=rates,clock_ms=clock,research_enabled=True,
        transport=public_reference_read)
    receipt=dict(started_ms=clock(),source_hash_before=active_source_hash(ROOT),
        execution_mode='PAPER',allow_live_orders=False,protection_enabled=False,
        exchange_orders_submitted=0,purpose='EXTERNAL_RESEARCH_ONLY_NO_SIGNAL_ACTIVATION')
    atomic_json(a.output/'receipt.json',receipt)
    results=[];native_capture=[]
    try:
        client.startup();contexts=market.get_asset_contexts();context_ms=clock()
        for symbol in a.symbols:
            now=clock();end=now//60000*60000-1
            anchor=int(SessionManager().get_vwap_anchor(datetime.fromtimestamp(now/1000,timezone.utc)).timestamp()*1000)
            start=min(end+1-300*60000,anchor-14*60000)
            try:
                bars=market.get_candles(symbol,start,end,now_ms=now)
                book=market.get_orderbook(symbol)
                quote=make_quote(book,contexts[symbol],clock(),mark_timestamp_ms=context_ms)
                source_symbol,units=mapping[symbol]
                external=reference.get_candles(source_symbol,start,end)
                m=AssetMapping(symbol,reference.source_id,source_symbol,units,
                    fx_direction=units if symbol in {'par:USDEUR','par:USDJPY'} else None,
                    review_reference='docs/availability_v7_2026-10-10/external_research.md#asset-mapping',
                    instrument_status='EXTERNAL_SOURCE_POTENTIALLY_COMPATIBLE')
                result=compare_sources(bars,external,m,decision_ms=clock(),quote=quote)
                expected=(end-start)//60000+1
                result.update(expected_intervals=expected,
                    native_missing_percent=100*(expected-len(bars))/expected,
                    external_missing_percent=100*(expected-len(external))/expected)
                result['candidate_units_scope']='Organizers identify reference; live unit/contract equivalence not approved. No scaling/inversion applied.'
                results.append(result)
                native_capture.append(dict(symbol=symbol,candles=[asdict(c) for c in bars],quote=asdict(quote),
                    external=[asdict(c) for c in external]))
            except Exception as exc:
                results.append(dict(native_symbol=symbol,label='EXTERNAL_RESEARCH_ONLY_NO_EXECUTION',
                    verdict='EXTERNAL_SOURCE_UNVERIFIED',reason=type(exc).__name__+':'+str(exc),live_signal_approved=False))
        atomic_json(a.output/'comparison.json',dict(results=results,
            counterfactual_verdict='NOT ENOUGH EVIDENCE; no approved volume equivalence or actual execution histories',
            actual_exchange_orders=0))
        atomic_json(a.output/'native_and_external_capture.json',native_capture)
        atomic_json(a.output/'external_raw.json',reference.evidence)
        receipt.update(finished_ms=clock(),source_hash_after=active_source_hash(ROOT),
            public_budget=rates.report(),native_metadata=client.metadata,
            source_unchanged=receipt['source_hash_before']==active_source_hash(ROOT),completed=True)
        atomic_json(a.output/'receipt.json',receipt)
        print(json.dumps(dict(output=str(a.output),compared=len(results),actual_orders=0)))
    finally:
        client.close();journal.close();owner.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
