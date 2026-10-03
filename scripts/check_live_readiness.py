"""Read-only par readiness; no key loading or /exchange actions."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.live_readiness import valid_address,verify_live_account_readiness
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor,HyperliquidRateLimitManager
from exchange.sdk_transport import verify_sdk
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--team-wallet',default=os.environ.get('TEAM_WALLET_ADDRESS'))
    parser.add_argument('--api-wallet-address',default=os.environ.get('API_WALLET_ADDRESS'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    require_paper_migration()
    freeze=verify_strategy_freeze()
    sdk=verify_sdk()
    result=dict(network='testnet',dex='par',market_data_ready=False,paper_ready=False,
        signed_transport_implemented=True,sdk_version=sdk,account_ready=False,live_ready=False,
        live_orders_permitted=False,execution_mode='PAPER',allow_live_orders=False,
        team_wallet_configured=valid_address(args.team_wallet),api_wallet_configured=valid_address(args.api_wallet_address),
        strategy_freeze=freeze,final_status='ACCOUNT_SETUP_REQUIRED')
    client=HyperliquidClient()
    try:
        client.startup()
        market=HyperliquidMarketData(client)
        clock=ClockHealthMonitor(clock_ms=client.clock_ms)
        sent=client.clock_ms()
        book=market.get_orderbook('par:BTC')
        clock.observe(book.timestamp_ms,sent,client.clock_ms())
        client.post_info('perpDexLimits')
        result.update(market_data_ready=True,paper_ready=True,market_rules_loaded=True,
            metadata=[asdict(s) for s in client.markets.values()],dex_index=client.dex_index,
            observed_ms=client.clock_ms(),clock_healthy=clock.healthy,account_reconciliation_ready=False)
        if valid_address(args.team_wallet) and valid_address(args.api_wallet_address):
            with tempfile.TemporaryDirectory(prefix='anchorium-readiness-') as temporary:
                journal=ExecutionJournal(Path(temporary)/'read-only.sqlite',session_id='read-only:readiness',
                                         team_address=args.team_wallet)
                try:
                    rates=HyperliquidRateLimitManager(journal,clock_ms=client.clock_ms)
                    client.rate_limits=rates
                    account=HyperliquidAccount(client,args.team_wallet)
                    # This read-only CLI never claims to restore strategy management
                    # state; funded-account technical readiness also needs that.
                    readiness=verify_live_account_readiness(account,args.api_wallet_address,
                        clock_health=clock,rate_limits=rates,reconciliation_ready=False)
                    result['account_verification']=readiness.report(market_ready=True)
                finally:
                    journal.close()
        else:
            result['reasons']=['TEAM_AND_APPROVED_API_WALLET_CONFIGURATION_REQUIRED']
    except Exception as exc:
        result['reasons']=['READ_ONLY_VERIFICATION_FAILED:'+type(exc).__name__]
    finally:
        client.transport.close()
    encoded=json.dumps(result,indent=2,default=str)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded)
    print(encoded)
    return 0 if result['market_data_ready'] else 1


if __name__=='__main__':
    raise SystemExit(main())
