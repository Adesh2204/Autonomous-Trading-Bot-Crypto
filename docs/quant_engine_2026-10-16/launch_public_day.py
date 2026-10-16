"""Launch one source-qualified public-only day; write a terminal accounting audit.

This supervisor has no SDK, key access, exchange action, restart or execution
mode. Its child is the tested public-info observer with its own hard deadline.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
import hashlib,json,os,sqlite3,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json,PaperOwner

TEAM='0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C'
DAY_START=int(datetime(2026,10,16,tzinfo=ZoneInfo('Asia/Calcutta')).timestamp()*1000)
DEADLINE=int(datetime(2026,10,16,23,57,tzinfo=ZoneInfo('Asia/Calcutta')).timestamp()*1000)

def terminal_audit(code):
    path=BASE/'daily_observation';terminal=path/'terminal_result.json'
    r=json.loads(terminal.read_text()) if terminal.exists() else {}
    account=r.get('account',{});fills=[f for f in account.get('fills',[])
        if DAY_START<=f['timestamp_ms']<=r.get('updated_ms',0)]
    funding=[f for f in account.get('funding_events',[])
        if DAY_START<=f['timestamp_ms']<=r.get('updated_ms',0)]
    complete=r.get('fresh_terminal_reconciliation') is True
    gross=sum((D(f['closed_pnl']) for f in fills),D(0)) if complete and all(f.get('closed_pnl') is not None for f in fills) else None
    fees=sum((D(f['fee']) for f in fills),D(0)) if complete else None
    cashflow=sum((D(f['cashflow']) for f in funding),D(0)) if complete else None
    opening=[];closing=[];unclassified=[]
    for f in fills:
        if f.get('start_position') is None:unclassified.append(f);continue
        before=D(f['start_position']);after=before+(1 if f['side']=='BUY' else -1)*D(f['quantity'])
        if before*after<0:unclassified.append(f)
        elif abs(after)>abs(before):opening.append(f)
        elif abs(after)<abs(before):closing.append(f)
    reads=r.get('terminal_readbacks',[])
    flat=(complete and len(reads)==2 and reads[0]['observed_ms']<reads[1]['observed_ms']
        and all(x['ready'] and not x['positions'] and not x['orders'] for x in reads))
    net=gross-fees+cashflow if gross is not None and fees is not None and cashflow is not None else None
    audit=dict(observed_ms=time.time_ns()//1000000,worker_exit_code=code,status=r.get('status','NO_TERMINAL_RESULT'),
        network='testnet',dex='par',team_wallet=TEAM,source_hash=r.get('source_hash'),
        observation_only=True,signing_authority='NONE',actual_signatures_created=0,exchange_actions_sent=0,
        day_start_ms=DAY_START,deadline_ms=DEADLINE,actual_day_fills=fills,actual_day_funding=funding,
        entry_fill_count=len(opening),exit_fill_count=len(closing),
        entry_order_count=len({f['order_id'] for f in opening}),exit_order_count=len({f['order_id'] for f in closing}),
        deployed_entry_notional=sum((D(f['quantity'])*D(f['price']) for f in opening),D(0)) if complete else None,
        completed_trade_cycles=0 if complete and not fills else None,
        gross_closed_pnl=gross,actual_fees=fees,actual_funding=cashflow,actual_day_net=net,
        actual_observed_lifetime_account_pnl=account.get('realized'),
        reported_account_equity=account.get('reported_account_equity'),
        equity_change_since_first_observation=r.get('observed_equity_change'),
        sampled_drawdown=r.get('sampled_equity_drawdown'),intraday_maximum_drawdown=None,
        official_daily_return=None,performance_note='No organizer score or continuous equity path inferred. Intraday maximum drawdown and size/direction strategy ratios need representative observations.',
        final_positions=r.get('final_positions'),final_orders=r.get('final_orders'),
        authoritative_flat_zero_orders_twice=flat,terminal_readbacks=reads,
        protection_status='NO_ACTIVE_POSITION' if flat else 'REQUIRES_OPERATOR_REVIEW',
        clean_shutdown=r.get('clean') is True,journal_integrity=r.get('journal_integrity'),
        unclassified_fills=unclassified,remaining_risks=['SHORT and native protection remain exchange-unqualified',
            'No multi-regime out-of-sample strategy qualification','Scored authority and organizer team eligibility require separate confirmation'],
        restart_permitted=False,old_mandates_reused=False)
    if not flat:audit['required_action']='Review residual/unknown exposure and orders. No automatic signing, retry, restart or next-day session.'
    atomic_json(BASE/'end_of_day_audit.json',audit)
    lines=['# October 16 terminal audit — public observation only','',
        f"Worker status: {audit['status']}; exit code: {code}; clean shutdown: {audit['clean_shutdown']}; SQLite integrity: {audit['journal_integrity']}.",
        f"Actual Oct16 entry/exit fill counts: {len(opening)} / {len(closing)}. Actual day net: {net} TEST USDPR; fees: {fees}; funding: {cashflow}.",
        f"Two authoritative terminal flat/zero-order reads: {flat}. Positions: {audit['final_positions']}; orders: {audit['final_orders']}.",
        f"Observed lifetime accounting: {audit['actual_observed_lifetime_account_pnl']}.",
        'No orders, signatures or new trading authority were created. Statistical strategy metrics, intraday maximum drawdown and official score are unavailable unless independently supported. All fill/order identities and raw terminal readbacks are in end_of_day_audit.json.',
        'SHORT and native protection are not exchange-qualified. This session cannot restart or extend itself. A new day requires a separate decision.']
    (BASE/'end_of_day_audit.md').write_text('\n\n'.join(lines)+'\n')
    return audit

def main():
    now=time.time_ns()//1000000
    if not DAY_START<=now<DEADLINE:raise RuntimeError('OCT16_PUBLIC_DAY_WINDOW_REQUIRED')
    receipt=json.loads((BASE/'regression_release/test_receipt.json').read_text())
    preservation=json.loads((BASE/'preservation_verification.json').read_text())
    source=active_source_hash(ROOT)
    if not (receipt.get('passed') is True and receipt['source_hash']==receipt['source_hash_after']==source
        and receipt['totals']==dict(tests=2494,failures=0,errors=0,skipped=0)
        and preservation.get('passed') is True and preservation['source_hash']==source
        and hashlib.sha256((BASE/'regression_release/regression.xml').read_bytes()).hexdigest()==receipt['xml_sha256']):
        raise RuntimeError('EXACT_PASSING_SOURCE_AND_PRESERVATION_REQUIRED')
    owner=PaperOwner(BASE/'public_day_supervisor.lock')
    launch=BASE/'public_day_launch_receipt.json'
    args=[sys.executable,str(ROOT/'scripts/run_quant_engine.py'),'observe','--output',str(BASE/'daily_observation'),
        '--team-wallet',TEAM,'--markets','par:BTC','par:ETH','par:HYPE','--expires-ms',str(DEADLINE),
        '--source-hash',source,'--scan-seconds','300']
    record=dict(created_ms=now,source_hash=source,expires_ms=DEADLINE,supervisor_pid=os.getpid(),
        command=args,scope='PUBLIC_INFO_AND_MARKET_DATA_ONLY',signing_authority='NONE',
        exchange_actions_authorized=0,restart_permitted=False,
        regression_receipt_sha256=hashlib.sha256((BASE/'regression_release/test_receipt.json').read_bytes()).hexdigest(),
        supervisor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with launch.open('x') as f:json.dump(record,f,indent=2)
    with (BASE/'daily_observation_process.log').open('x') as log:
        process=subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        power=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(process.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        record.update(worker_pid=process.pid,caffeinate_pid=power.pid);atomic_json(launch,record)
        code=process.wait()
        try:power.wait(timeout=10)
        except subprocess.TimeoutExpired:record['caffeinate_exit_unconfirmed']=True
    record.update(finished_ms=time.time_ns()//1000000,worker_exit_code=code)
    atomic_json(launch,record);terminal_audit(code);owner.close()
    return code

if __name__=='__main__':raise SystemExit(main())
