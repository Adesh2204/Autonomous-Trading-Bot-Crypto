"""Replay a complete bounded public REST tape through the unchanged paper brain."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from crypto_paper_bot import CryptoPaperBot
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.replay import ReplayTape,ReplayExecution
from exchange.perpetual_economics import FeeSchedule
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy
from risk.models import RiskPolicy
from risk.portfolio_risk import PortfolioRisk
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze
from run_crypto_paper import ReportWriter,encode


def replay(tape_path,output):
    require_paper_migration()
    verify_strategy_freeze()
    tape=ReplayTape(json.loads(Path(tape_path).read_text()))
    parameters=tape.parameters
    fees=FeeSchedule(**parameters['fees'])
    scanner_policy=ScannerPolicy(**parameters['scanner'])
    risk_policy=RiskPolicy(**parameters['risk'])
    # Explicit transport prevents creation of requests.Session or any socket.
    client=HyperliquidClient(tape,clock_ms=tape.clock_ms)
    writer=ReportWriter(Path(output),'OFFLINE_REPLAY_OF_'+tape.provenance)
    try:
        client.startup()
        market=HyperliquidMarketData(client)
        scanner=MarketRegimeScanner(market,scanner_policy)
        execution=ReplayExecution(client.markets,fees=fees,clock_ms=client.clock_ms,
            starting_collateral=parameters['starting_collateral'],leverage=risk_policy.leverage)
        bot=CryptoPaperBot(market,scanner,execution,PortfolioRisk(risk_policy,fees))
        writer.results.bind(bot)
        snapshot=bot.cycle()
        report=writer.save(bot,snapshot)
        completion=tape.finish()
        (Path(output)/'replay_validation.json').write_text(encode(dict(completion,
            source_tape_sha256=json.loads(Path(tape_path).read_text())['sha256'],
            source_tape=str(Path(tape_path).resolve()),historical_candles_and_observed_quotes_only=True,
            signal_brain_frozen=True))+'\n')
        return report
    finally:
        client.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tape',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=replay(args.tape,args.output)
    except (ValueError,RuntimeError,OSError,TypeError,KeyError) as exc:
        print('Replay stopped: '+str(exc),file=sys.stderr)
        return 1
    print(encode(dict(execution_mode='REPLAY',scanned_markets=report['scanned_markets'],
        local_fills=report['local_fills'],exchange_orders_submitted=0,report=str(args.output/'report.json'))))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
