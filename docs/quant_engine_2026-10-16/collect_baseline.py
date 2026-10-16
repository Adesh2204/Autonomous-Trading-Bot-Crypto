"""Public-address and market audit only; no key access or signing capability."""
from dataclasses import asdict
from pathlib import Path
import json, sys, time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.exit_recovery import Environment
from exchange.paper_operations import atomic_json
from venue_config import require_paper_migration

def main():
    require_paper_migration();out=Path(sys.argv[1]);out.mkdir(exist_ok=False)
    env=Environment(ROOT);transport=env.client.transport
    receipts=(out/'info_receipts.jsonl').open('x')
    def read(payload):
        sent=env.client.clock_ms();response=transport(payload)
        receipts.write(json.dumps(dict(request=payload,response=response,sent_ms=sent,
            received_ms=env.client.clock_ms()),default=str)+'\n');receipts.flush()
        return response
    env.client.transport=read
    report=dict(started_ms=env.client.clock_ms(),source_hash=env.source,
        source='ACTUAL_TESTNET_PAR_PUBLIC_READS',signature_count=0,exchange_writes=0,
        markets={},metadata=env.client.metadata)
    try:
        env.recovery.recover()
        report['account']=env.recovery.state.report()
        report['account_observed_ms']=env.client.clock_ms()
        report['account_reconciliation']=asdict(env.recovery.last_report)
        report['fees']=env.account._query('userFees')
        report['fees_observed_ms']=env.client.clock_ms()
        env.provider.fee_scale();report['deployer_fee_scale']=env.provider.current_fee_scale
        report['account_mode']=env.account._query('userAbstraction')
        report['agents']=env.account._query('extraAgents')
        for symbol in sorted(env.client.markets):
            row=dict(symbol=symbol,spec=asdict(env.client.market(symbol)))
            try:
                now=env.client.clock_ms();end=now//60000*60000-1
                bars=env.market.get_candles(symbol,end+1-900*60000,end,now_ms=now)
                row['active_asset']=env.account._query('activeAssetData',coin=symbol)
                row['account_observed_ms']=env.client.clock_ms()
                row['context']=env.market.get_asset_contexts()[symbol]
                row['context_observed_ms']=env.client.clock_ms()
                row['book']=asdict(env.market.get_orderbook(symbol))
                row.update(candles=[asdict(c) for c in bars],observed_ms=env.client.clock_ms(),status='OBSERVED')
            except Exception as exc:row.update(status='FAILED_SAFE',error_type=type(exc).__name__)
            report['markets'][symbol]=row
            atomic_json(out/'snapshot.json',report)
        report['finished_ms']=env.client.clock_ms()
        atomic_json(out/'snapshot.json',report)
        print(json.dumps(dict(status='READ_ONLY_CAPTURE_COMPLETE',markets={k:v['status'] for k,v in report['markets'].items()},
            positions=report['account']['positions'],orders=report['account']['open_orders'],
            actual_pnl=report['account']['realized'],output=str(out)),default=str))
    finally:
        receipts.close();env.client.transport=transport;env.close()

if __name__=='__main__':main()
