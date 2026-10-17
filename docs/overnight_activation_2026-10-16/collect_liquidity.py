"""Finite public-address audit. No signer, nonce manager, order transport or worker."""
from dataclasses import asdict
from pathlib import Path
from decimal import Decimal as D
import sys,time,json
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.exit_recovery import ExitRecovery
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.testnet_certification import TEAM,API
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.capital_allocation import depth_capacity,floor_quantity,walk_book
from exchange.quant_observation import explain_market
from venue_config import require_paper_migration

def main():
    require_paper_migration()
    out=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent/'fresh_liquidity'
    out.mkdir(exist_ok=False)
    journal=ExecutionJournal(out/'public.sqlite',session_id='public:long-activation-audit',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal,signer_address=API);rates.read_budget_wait_seconds=65
    transport=ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl')
    client=HyperliquidClient(transport,rate_limits=rates)
    result=dict(started_ms=client.clock_ms(),exchange_writes=0,signatures=0,samples=[],errors=[])
    try:
        client.startup();account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
        recovery=ExitRecovery(account,journal,initial_start_ms=0);recovery.recover()
        result.update(account=recovery.state.report(),account_ms=client.clock_ms(),metadata=client.metadata)
        result['fees']=account._query('userFees');result['fees_ms']=client.clock_ms()
        result['agents']=account._query('extraAgents');result['account_mode']=account._query('userAbstraction')
        result['fee_scale_evidence']=client.post_info('perpDexs')
        fee=D(result['fees']['userCrossRate'])*6  # conservative maximum when scale is unavailable
        bars={}
        for sample in range(3):
            if sample:time.sleep(15)
            for symbol in sorted(client.markets):
                row=dict(sample=sample,symbol=symbol,spec=asdict(client.market(symbol)))
                try:
                    if symbol not in bars:
                        now=client.clock_ms();end=now//60000*60000-1
                        bars[symbol]=market.get_candles(symbol,end+1-900*60000,end,now_ms=now)
                    active=account._query('activeAssetData',coin=symbol);active_ms=client.clock_ms()
                    context=market.get_asset_contexts()[symbol];context_ms=client.clock_ms()
                    book=market.get_orderbook(symbol);now=client.clock_ms();spec=client.market(symbol)
                    row.update(observed_ms=now,active_asset=active,active_ms=active_ms,context=context,
                        context_ms=context_ms,book=asdict(book),fee_rate_bound=fee,
                        spread_bps=(book.asks[0].price-book.bids[0].price)/((book.asks[0].price+book.bids[0].price)/2)*10000,
                        signal=explain_market(spec,book,bars[symbol],context,now_ms=now,context_ms=context_ms,fee_rate=fee),directions={})
                    row['one_lot_stop_notional']=spec.size_step*book.bids[0].price*D('.985')
                    row['partial_protection_qualified']=row['one_lot_stop_notional']>=10
                    for direction,side,index in [('LONG','BUY',0),('SHORT','SELL',1)]:
                        a=depth_capacity(book,side);b=depth_capacity(book,'SELL' if side=='BUY' else 'BUY')
                        q=floor_quantity(spec,min(a['best_quantity']*D('.1'),b['best_quantity']*D('.1'),
                            a['raw_l2_quantity']*D('.1'),b['raw_l2_quantity']*D('.1'),D(active['maxTradeSzs'][index]),
                            min(D(x) for x in active['availableToTrade'])/(a['best_price']*(1+fee*2))))
                        n=q*a['best_price'];entry=walk_book(book,side,q,limit=a['limit'],participation=D('.1'))
                        close=walk_book(book,'SELL' if side=='BUY' else 'BUY',q,limit=b['limit'],participation=D('.1'))
                        row['directions'][direction]=dict(capacity_quantity=q,capacity_notional=n,
                            proposed_quantity=q if n>=10 else D(0),entry=entry,exit=close,
                            estimated_roundtrip_fees=(entry['cost']+close['cost'])*fee,
                            targets={str(t):n>=t for t in (1000,2500,5000,10000,25000,50000)},
                            approval_granted=False,qualified_unattended_notional=0)
                    row['status']='OBSERVED'
                except Exception as exc:
                    row.update(status='FAILED_SAFE',error=str(exc))
                result['samples'].append(row);atomic_json(out/'audit.json',result)
        result['final_readbacks']=[]
        for _ in range(2):
            recovery.recover()
            result['final_readbacks'].append(dict(observed_ms=client.clock_ms(),source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',
                positions=[asdict(p) for p in account.get_positions().values()],orders=account.get_frontend_open_orders(),
                ready=recovery.last_report.ready))
            time.sleep(.3)
        result.update(finished_ms=client.clock_ms(),account_final=recovery.state.report(),
            sqlite_integrity=journal.db.execute('PRAGMA integrity_check').fetchone()[0])
    except Exception as exc:result['errors'].append(str(exc));raise
    finally:
        atomic_json(out/'audit.json',result);client.close();journal.close()
    print(json.dumps(dict(status='FINITE_AUDIT_COMPLETE',samples=len(result['samples']),errors=result['errors'])))

if __name__=='__main__':main()
