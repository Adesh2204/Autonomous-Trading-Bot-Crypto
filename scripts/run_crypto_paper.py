"""Bounded or continuous local paper trading from public par data. No signer."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))

from crypto_paper_bot import CryptoPaperBot
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine
from exchange.paper_execution import PaperExecution
from exchange.perpetual_economics import FeeSchedule
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy
from market_stream import MarketStream
from risk.models import RiskPolicy
from risk.portfolio_risk import PortfolioRisk
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def encode(value):
    return json.dumps(value,indent=2,default=str,allow_nan=False)


def load_policy(path):
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or set(value)!={'starting_collateral','fees','scanner','risk'}:
        raise ExchangeError('PAPER_POLICY_SCHEMA_INVALID')
    return value,FeeSchedule(**value['fees']),ScannerPolicy(**value['scanner']),RiskPolicy(**value['risk'])


class ReportWriter:
    def __init__(self,path,provenance):
        if path.exists() and any(path.iterdir()):
            raise ExchangeError('PAPER_RUN_OUTPUT_MUST_BE_NEW')
        path.mkdir(parents=True,exist_ok=True)
        self.path=path
        self.provenance=provenance
        self.order_cursor=0
        self.ledger_cursor=0
        self.scan_cursor=None

    def save(self,bot,snapshot):
        report=bot.report()
        report.update(provenance=self.provenance,observed_at_utc=datetime.now(timezone.utc).isoformat(),
            assumptions=['Hypothetical USDPR starting collateral; no wallet balance used.',
                'Taker fills only from fresh displayed BBO, bounded by displayed size.',
                'Displayed liquidity consumed once per observation; no invented queue or maker fill.',
                'Fee rates are explicit paper assumptions; actual wallet tiers not verified.',
                'Hourly funding uses observed boundary snapshots and is labelled estimated.',
                'Missed funding boundary pauses entries; no fabricated historical oracle.',
                'Maintenance uses runtime tiers; no exchange liquidation-price claim.',
                'Current open positions remain unrealized; no stock EOD liquidation.'])
        temporary=self.path/'report.json.tmp'
        temporary.write_text(encode(report)+'\n')
        temporary.replace(self.path/'report.json')
        with (self.path/'events.jsonl').open('a') as stream:
            events=bot.execution.events[self.order_cursor:]+bot.execution.portfolio.events[self.ledger_cursor:]
            for event in sorted(events,key=lambda e:e['observed_ns']):
                stream.write(json.dumps(event,default=str,allow_nan=False)+'\n')
        self.order_cursor=len(bot.execution.events)
        self.ledger_cursor=len(bot.execution.portfolio.events)
        with (self.path/'equity.jsonl').open('a') as stream:
            stream.write(json.dumps(asdict(snapshot),default=str,allow_nan=False)+'\n')
        scan=bot.latest_scan
        if scan and scan.observed_at_ms!=self.scan_cursor:
            with (self.path/'candles.jsonl').open('a') as stream:
                for diagnostic in scan.diagnostics:
                    stream.write(json.dumps(dict(scan_observed_at_ms=scan.observed_at_ms,
                        symbol=diagnostic.symbol,candles=[asdict(c) for c in diagnostic.candles]),
                        default=str,allow_nan=False)+'\n')
            self.scan_cursor=scan.observed_at_ms
        return report

    def save_halt(self,bot,reason,*,name='halt.json'):
        # Persist known ledger facts without inventing equity from stale marks.
        ledger=bot.execution.portfolio
        (self.path/name).write_text(encode(dict(execution_mode='PAPER',
            exchange_orders_submitted=0,reason=str(reason),
            last_good_report=str(self.path/'report.json') if (self.path/'report.json').exists() else None,
            known_positions=[asdict(p) for p in ledger.positions.values()],
            cash=ledger.cash,collateral='USDPR',equity=None,
            order_events=bot.execution.events,ledger_events=ledger.events,
            decisions=bot.decisions))+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'docs/paper_policy.example.json')
    parser.add_argument('--cycles',type=int,default=1,help='1 for one public scan; 0 for continuous paper mode')
    parser.add_argument('--scan-interval-seconds',type=float,default=300)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--account-address',help='Optional public team address for a separate read-only account observer')
    parser.add_argument('--account-history-start-ms',type=int,help='Explicit start of the observed account-event window')
    args=parser.parse_args()
    if args.cycles<0 or not 1<=args.scan_interval_seconds<=3600:
        parser.error('cycles must be nonnegative; scan interval must be 1–3600 seconds')
    try:
        require_paper_migration()
        verify_strategy_freeze()
        config,fees,scanner_policy,risk_policy=load_policy(args.config)
        if args.account_address:
            HyperliquidAccount(None,args.account_address)  # Address format only; no network.
            if args.account_history_start_ms is None or args.account_history_start_ms<0:
                raise ExchangeError('ACCOUNT_HISTORY_START_REQUIRED')
        elif args.account_history_start_ms is not None:
            raise ExchangeError('PUBLIC_TEAM_ADDRESS_REQUIRED')
    except (ValueError,RuntimeError,OSError,TypeError) as exc:
        parser.error(str(exc))
    output=args.output or ROOT/'algo-trading-bot/data/crypto-paper'/(
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    writer=ReportWriter(output,'LIVE_PUBLIC_PAR_DATA_LOCAL_PAPER_SIMULATION')
    client=HyperliquidClient()
    feed_client=None
    scan_client=None
    stop=threading.Event()
    workers=[]
    bot=None
    try:
        client.startup()
        market=HyperliquidMarketData(client)
        scanner=MarketRegimeScanner(market,scanner_policy)
        execution=PaperExecution(client.markets,fees=fees,clock_ms=client.clock_ms,
            starting_collateral=config['starting_collateral'],leverage=risk_policy.leverage)
        bot=CryptoPaperBot(market,scanner,execution,PortfolioRisk(risk_policy,fees))
        account_recovery=None
        if args.account_address:
            account=HyperliquidAccount(client,args.account_address)
            truth=ExchangeTruthState()
            reconciler=HyperliquidReconciliation(account)
            def account_recovery():
                try:
                    return reconciler.recover_incremental(truth,initial_start_ms=args.account_history_start_ms)
                finally:
                    bot.exchange_account_report=truth.report()
        if args.cycles==1:
            if account_recovery:
                bot.breakers.pause('account','REST_ACCOUNT_RECONCILIATION_REQUIRED')
                try:
                    if not account_recovery()['entries_paused']:
                        bot.breakers.clear('account')
                except ExchangeError as exc:
                    bot.breakers.pause('account',str(exc))
            snapshot=bot.cycle()
            report=writer.save(bot,snapshot)
        else:
            # Separate public clients: metadata refresh never invalidates a
            # streaming client's cache, and the ledger has a single owner thread.
            feed_client=HyperliquidClient()
            feed_client.startup()
            scan_client=HyperliquidClient()
            scanner=MarketRegimeScanner(HyperliquidMarketData(scan_client),scanner_policy)
            bot.scanner=scanner
            engine=ParMarketDataEngine(HyperliquidMarketData(feed_client),history_bars=scanner_policy.history_bars,
                                      include_trades=True)
            stream=MarketStream(engine,risk_policy,account_recovery=account_recovery)
            bot.breakers.pause('stream','STREAM_RECOVERY_REQUIRED')
            scans=queue.Queue(maxsize=1)
            failures=queue.Queue()
            def stream_worker():
                try:
                    stream.run(stop)
                except Exception as exc:
                    failures.put(exc)
                    stop.set()
            def scan_worker():
                try:
                    for scan in scanner.run(stop,args.scan_interval_seconds):
                        while not stop.is_set():
                            try:
                                scans.put(scan,timeout=.25)
                                break
                            except queue.Full:
                                continue
                except Exception as exc:
                    failures.put(exc)
                    stop.set()
            workers=[threading.Thread(target=stream_worker,daemon=True),
                     threading.Thread(target=scan_worker,daemon=True)]
            for worker in workers:
                worker.start()
            completed=0
            while not stop.is_set():
                try:
                    ready=stream.poll(bot)
                    active=list(execution.portfolio.positions)
                    if active:
                        if not ready or any(not bot.feed_health[s]['healthy'] for s in active):
                            raise ExchangeError('HELD_MARKET_FEED_PAUSED')
                        snapshot=bot.observe({s:engine.get_quote(s) for s in active})
                    if ready:
                        bot.observe_completed_candles({s:engine.get_completed_candles(s) for s in engine.symbols
                                                      if bot.feed_health[s]['healthy']})
                        snapshot=execution.portfolio.snapshot(bot.quotes,client.clock_ms())
                    try:
                        scan=scans.get_nowait()
                    except queue.Empty:
                        scan=None
                    if scan:
                        if not ready:
                            # Save diagnostics but do not trade before feed warmup.
                            bot.latest_scan=scan
                            bot._record('FEED_NOT_READY')
                            snapshot=execution.portfolio.snapshot(bot.quotes,client.clock_ms())
                        else:
                            if {d.symbol for d in scan.diagnostics}!=set(engine.symbols):
                                raise ExchangeError('RUNTIME_UNIVERSE_CHANGED_FEED_RESTART_REQUIRED')
                            snapshot=bot.consume_scan(scan)
                        report=writer.save(bot,snapshot)
                        completed+=1
                        if args.cycles and completed>=args.cycles:
                            stop.set()
                    elif active:
                        writer.save(bot,snapshot)
                except ExchangeError as exc:
                    if str(exc) not in {'HELD_MARKET_FEED_PAUSED','STREAM_NOT_HEALTHY','STREAM_WARMUP_REQUIRED',
                                       'ORDERBOOK_STALE','ASSET_CONTEXT_STALE','PORTFOLIO_MARK_MISSING_OR_STALE',
                                       'PORTFOLIO_MARK_CONTEXT_MISSING_OR_STALE'}:
                        bot.accounting_halt=str(exc)
                        bot.breakers.pause('accounting',str(exc))
                    bot._record('FEED_OR_ACCOUNTING_HALT',reason=str(exc))
                    writer.save_halt(bot,exc)
                stop.wait(.25)
            if not failures.empty():
                failure=failures.get()
                bot.breakers.pause('worker',str(failure))
                raise failure
            report=bot.report()
        print(encode(dict(report= str(output/'report.json'),execution_mode='PAPER',
            scanned_markets=report['scanned_markets'],watchlist=report['watchlist'],
            scan_status=report['scan_status'],local_fills=report['local_fills'],
            exchange_orders_submitted=0,portfolio=report['portfolio'])))
        return 0
    except KeyboardInterrupt:
        stop.set()
        if bot:
            try:
                snapshot=bot.execution.portfolio.snapshot(bot.quotes,bot.clock_ms())
                writer.save(bot,snapshot)
            except (ExchangeError,OSError) as exc:
                writer.save_halt(bot,'INTERRUPTED_WITH_UNVALUED_STATE: '+str(exc),name='shutdown.json')
        return 0
    except Exception as exc:
        (output/'failure.json').write_text(encode(dict(error=type(exc).__name__,reason=str(exc),
            execution_mode='PAPER',exchange_orders_submitted=0,
            risk_state=bot.breakers.report(bot.clock_ms()) if bot else None,
            public_stream=bot.stream_report if bot else None))+'\n')
        print('Paper run stopped: '+type(exc).__name__+':'+str(exc),file=sys.stderr)
        return 1
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=1)
        for connection in (client,feed_client,scan_client):
            if connection is not None:
                connection.close()


if __name__=='__main__':
    raise SystemExit(main())
