"""Read-only, idempotent decision evidence. No order or policy mutation methods."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from decimal import Decimal
from enum import Enum
import csv,json,math
from pathlib import Path

from exchange.execution_journal import safe_data,canonical

STAGES=('TOTAL_MARKETS_SEEN','VALID_MARKET_IDENTITY','MARKET_DATA_HEALTHY','ENOUGH_HISTORY',
 'LIQUIDITY_PASS','SPREAD_PASS','ATR_PASS','SCANNER_QUALIFIED','TOP3_SELECTED','STRATEGY_EVALUATED',
 'SIGNAL_GENERATED','BIAS_PASS','ANTI_SPAM_PASS','FRICTION_PASS','RISK_PASS','EXECUTION_PERMISSION',
 'ORDER_ATTEMPTED','FILLED','TRADE_COMPLETED')

class RejectionReason(str,Enum):
    STALE_CANDLE='STALE_CANDLE'
    STALE_BOOK='STALE_BOOK'
    STALE_MARK='STALE_MARK'
    HISTORY_GAP='HISTORY_GAP'
    INSUFFICIENT_HISTORY='INSUFFICIENT_HISTORY'
    INVALID_MARKET_DATA='INVALID_MARKET_DATA'
    MARKET_DATA_UNAVAILABLE='MARKET_DATA_UNAVAILABLE'
    ATR_BELOW_SCANNER_FLOOR='ATR_BELOW_SCANNER_FLOOR'
    SPREAD_TOO_WIDE='SPREAD_TOO_WIDE'
    INSUFFICIENT_DEPTH='INSUFFICIENT_DEPTH'
    ZERO_LIQUIDITY='ZERO_LIQUIDITY'
    NOT_TOP3='NOT_TOP3'
    NO_SETUP='NO_SETUP'
    BIAS_MISMATCH='BIAS_MISMATCH'
    WARMUP='WARMUP'
    ANTI_SPAM_LOCK='ANTI_SPAM_LOCK'
    COOLDOWN='COOLDOWN'
    ATR_BELOW_BRAIN_FLOOR='ATR_BELOW_BRAIN_FLOOR'
    NEGATIVE_NET_EDGE_OR_RR='NEGATIVE_NET_EDGE_OR_RR'
    FEES_TOO_HIGH='FEES_TOO_HIGH'
    FUNDING_TOO_EXPENSIVE='FUNDING_TOO_EXPENSIVE'
    SLIPPAGE_TOO_HIGH='SLIPPAGE_TOO_HIGH'
    DAILY_LOSS_LIMIT='DAILY_LOSS_LIMIT'
    MAX_DRAWDOWN='MAX_DRAWDOWN'
    EXPOSURE_LIMIT='EXPOSURE_LIMIT'
    MARGIN_LIMIT='MARGIN_LIMIT'
    LIQUIDATION_BUFFER='LIQUIDATION_BUFFER'
    POSITION_ALREADY_OPEN='POSITION_ALREADY_OPEN'
    ENTRY_PAUSED='ENTRY_PAUSED'
    RECOVERY_PENDING='RECOVERY_PENDING'
    RATE_LIMIT='RATE_LIMIT'
    ACCOUNT_UNREADY='ACCOUNT_UNREADY'
    UNCLASSIFIED='UNCLASSIFIED'

ALIASES={'COMPLETED_CANDLE_STALE':'STALE_CANDLE','SIGNAL_STALE_OR_OPEN':'STALE_CANDLE',
 'ORDERBOOK_STALE':'STALE_BOOK','MARK_DATA_STALE':'STALE_MARK','SCANNER_ASSET_CONTEXT_STALE':'STALE_MARK',
 'ASSET_CONTEXT_STALE':'STALE_MARK','INSUFFICIENT_COMPLETED_HISTORY':'INSUFFICIENT_HISTORY',
 'ATR_BELOW_BASELINE_SCANNER_FLOOR':'ATR_BELOW_SCANNER_FLOOR','WINDOW_LIQUIDITY_INSUFFICIENT':'ZERO_LIQUIDITY',
 'BBO_DEPTH_INSUFFICIENT':'INSUFFICIENT_DEPTH','NOT_SELECTED':'NOT_TOP3','NO_SIGNAL':'NO_SETUP',
 'DUPLICATE_SIGNAL_ALREADY_PROCESSED':'ANTI_SPAM_LOCK','NET_EDGE_OR_RR_INSUFFICIENT':'NEGATIVE_NET_EDGE_OR_RR',
 'DAILY_RISK_EXHAUSTED':'DAILY_LOSS_LIMIT','PORTFOLIO_MARGIN_LIMIT':'MARGIN_LIMIT',
 'INSUFFICIENT_MARGIN':'MARGIN_LIMIT','MAX_NEW_SETUPS_REACHED':'EXPOSURE_LIMIT',
 'POSITION_ALREADY_OPEN':'POSITION_ALREADY_OPEN','EXPOSURE_LIMIT_REACHED':'EXPOSURE_LIMIT',
 'ACCOUNT_STREAM_NOT_READY':'RECOVERY_PENDING','STARTUP_ENTRY_LOCK_REQUIRED':'RECOVERY_PENDING',
 'ACCOUNT_RECONCILIATION_NOT_READY':'RECOVERY_PENDING','ENTRY_RELIABILITY_GATE_REQUIRED':'ENTRY_PAUSED'}

def reason_code(reason):
    text=str(reason)
    if text in ALIASES:return ALIASES[text]
    if text in RejectionReason._value2member_map_:return text
    if 'CANDLE' in text and 'GAP' in text:return 'HISTORY_GAP'
    if 'FUNDING' in text:return 'FUNDING_TOO_EXPENSIVE'
    if 'LIQUIDATION' in text:return 'LIQUIDATION_BUFFER'
    if 'DRAWDOWN' in text:return 'MAX_DRAWDOWN'
    if 'EXPOSURE' in text:return 'EXPOSURE_LIMIT'
    if 'MARGIN' in text:return 'MARGIN_LIMIT'
    if 'RATE' in text or 'BUDGET' in text:return 'RATE_LIMIT'
    if 'RECOVERY' in text or 'RECONCILIATION' in text:return 'RECOVERY_PENDING'
    if 'ACCOUNT' in text:return 'ACCOUNT_UNREADY'
    if 'INVALID' in text:return 'INVALID_MARKET_DATA'
    return 'UNCLASSIFIED'


def distribution(values,threshold,*,below=False):
    values=sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not values:return dict(count=0,min=None,median=None,p75=None,p90=None,p95=None,max=None,threshold=threshold,pass_percent=None)
    def percentile(q):
        i=(len(values)-1)*q
        lo=int(i);hi=min(lo+1,len(values)-1)
        return values[lo]+(values[hi]-values[lo])*(i-lo)
    return dict(count=len(values),min=values[0],median=percentile(.5),p75=percentile(.75),p90=percentile(.9),
        p95=percentile(.95),max=values[-1],threshold=threshold,
        below_percent=100*sum(v<threshold for v in values)/len(values),
        at_or_above_percent=100*sum(v>=threshold for v in values)/len(values),
        pass_percent=100*sum(v<=threshold if below else v>=threshold for v in values)/len(values))


class OpportunityFunnel:
    def __init__(self,*,journal=None,source='LOCAL_PAPER_OBSERVATION'):
        self.journal=journal
        self.source=source
        self.traces={}
        if journal:
            self.traces={r['candidate']:json.loads(r['data']) for r in journal.db.execute('SELECT * FROM opportunity_traces')}

    def _save(self,trace):
        if self.journal:
            with self.journal.transaction():
                self.journal.db.execute('INSERT OR REPLACE INTO opportunity_traces VALUES (?,?)',
                                        (trace['candidate_id'],canonical(safe_data(trace))))

    def _stage(self,trace,stage,status,reason=None,*,blocking=False):
        trace['stages'][stage]=dict(status=status,reason=reason)
        if reason:
            if reason not in trace['all_observed_failed_conditions']:trace['all_observed_failed_conditions'].append(reason)
            if blocking and trace['first_blocking_reason'] is None:trace['first_blocking_reason']=reason

    def observe_scan(self,scan,policy=None):
        for d in scan.diagnostics:
            cid=f'{d.symbol}:{scan.observed_at_ms}'
            if cid in self.traces:continue
            dt=datetime.fromtimestamp(scan.observed_at_ms/1000,timezone.utc)
            t=dict(candidate_id=cid,symbol=d.symbol,decision_ms=scan.observed_at_ms,available_at_ms=scan.observed_at_ms,
                source=self.source,utc_day=dt.date().isoformat(),utc_hour=dt.hour,weekday=dt.strftime('%A'),
                session_context='CONTINUOUS_CRYPTO' if d.symbol in {'par:BTC','par:ETH','par:HYPE'} else 'TRADITIONAL_REFERENCE_SESSION_UNVERIFIED',
                metrics=dict(d.metrics),scanner_policy=vars(policy).copy() if policy else None,
                scanner_rank=getattr(d,'evidence',{}).get('scanner_rank'),selected=d.symbol in scan.watchlist,
                signal=dict(d.signal) if d.signal else None,side_channel_signal=bool(d.signal and (d.signal.get('long') or d.signal.get('short'))),
                data_evidence=dict(getattr(d,'evidence',{})),first_blocking_reason=None,raw_reasons=list(d.reasons),
                all_observed_failed_conditions=[],stages={s:dict(status='NOT_REACHED',reason=None) for s in STAGES})
            self.traces[cid]=t
            self._stage(t,'TOTAL_MARKETS_SEEN','PASS')
            self._stage(t,'VALID_MARKET_IDENTITY','PASS' if d.symbol.startswith('par:') else 'FAIL','INVALID_MARKET_DATA' if not d.symbol.startswith('par:') else None)
            p=policy
            history=len(d.candles)
            enough=history>=p.history_bars if p else bool(d.signal)
            data_fail=next((reason_code(r) for r in d.reasons if reason_code(r) in {'STALE_CANDLE','STALE_BOOK','STALE_MARK','HISTORY_GAP','INVALID_MARKET_DATA','MARKET_DATA_UNAVAILABLE'}),None)
            healthy=d.snapshot is not None and data_fail is None and bool(d.signal)
            self._stage(t,'MARKET_DATA_HEALTHY','PASS' if healthy else 'FAIL' if data_fail else 'NOT_OBSERVED',data_fail)
            self._stage(t,'ENOUGH_HISTORY','PASS' if enough else 'FAIL','INSUFFICIENT_HISTORY' if not enough else None)
            conditions={
              'LIQUIDITY_PASS':(all(k in d.metrics for k in ('window_notional_approx','bbo_notional')),
                  d.metrics.get('window_notional_approx',0)>0 and d.metrics.get('bbo_notional',0)>0 and
                  (not p or d.metrics['window_notional_approx']>=p.min_window_notional and d.metrics['bbo_notional']>=p.min_bbo_notional),'ZERO_LIQUIDITY'),
              'SPREAD_PASS':('spread_bps' in d.metrics,not p or d.metrics.get('spread_bps',float('inf'))<=p.max_spread_bps,'SPREAD_TOO_WIDE'),
              'ATR_PASS':('atr_fraction' in d.metrics,not p or d.metrics.get('atr_fraction',0)>=p.min_atr_fraction,'ATR_BELOW_SCANNER_FLOOR')}
            for stage,(observed,passed,reason) in conditions.items():
                self._stage(t,stage,'PASS' if observed and passed else 'FAIL' if observed else 'NOT_OBSERVED',reason if observed and not passed else None)
            self._stage(t,'SCANNER_QUALIFIED','PASS' if d.qualified else 'FAIL',reason_code(d.reasons[0]) if d.reasons else None)
            if d.reasons:t['first_blocking_reason']=reason_code(d.reasons[0])
            if d.qualified:
                self._stage(t,'TOP3_SELECTED','PASS' if t['selected'] else 'FAIL','NOT_TOP3' if not t['selected'] else None,blocking=True)
            if t['selected']:
                self._stage(t,'STRATEGY_EVALUATED','PASS' if d.signal else 'NOT_OBSERVED')
                generated=t['side_channel_signal']
                brain=t['data_evidence'].get('brain',{})
                failure=('ANTI_SPAM_LOCK' if brain.get('anti_spam_pass') is False else
                         'WARMUP' if brain.get('raw_setup') and brain.get('warmup_pass') is False else
                         'ATR_BELOW_BRAIN_FLOOR' if brain.get('raw_setup') and brain.get('brain_atr_pass') is False else 'NO_SETUP')
                self._stage(t,'SIGNAL_GENERATED','PASS' if generated else 'FAIL',None if generated else failure,blocking=True)
                if generated:self._stage(t,'ANTI_SPAM_PASS','PASS')
            for r in d.reasons:
                code=reason_code(r)
                if code not in t['all_observed_failed_conditions']:t['all_observed_failed_conditions'].append(code)
            self._save(t)

    def permission_observation(self,cid,manager,side):
        t=self.traces.get(cid)
        if t is None:return
        bias=not (side=='BUY' and manager.daily_bias=='SHORT_BIAS' or side=='SELL' and manager.daily_bias=='LONG_BIAS')
        cooldown=manager.candles_since_last_sl>=manager.parameters['REENTRY_COOLDOWN_CANDLES']
        self._stage(t,'BIAS_PASS','PASS' if bias else 'FAIL',None if bias else 'BIAS_MISMATCH',blocking=cooldown and not bias)
        if not cooldown:self._stage(t,'ANTI_SPAM_PASS','FAIL','COOLDOWN',blocking=True)
        self._save(t)

    def event(self,kind,cid,details,now_ms):
        t=self.traces.get(cid)
        if t is None:return
        if kind in {'RISK_DECISION','LIVE_RISK_DECISION'}:
            decision=details['decision']; allowed=decision['allowed']
            reasons=decision.get('reasons',())
            economics=decision.get('economics')
            audit=details.get('audit',{})
            if economics is not None:t['expected_economics']=economics
            elif audit.get('economics') is not None:t['expected_economics']=audit['economics']
            economic_failure=bool(reasons and reasons[0]=='NET_EDGE_OR_RR_INSUFFICIENT')
            if allowed or audit.get('friction_passed') is True or economic_failure:
                self._stage(t,'FRICTION_PASS','FAIL' if economic_failure else 'PASS',
                            'NEGATIVE_NET_EDGE_OR_RR' if economic_failure else None,blocking=economic_failure)
            self._stage(t,'RISK_PASS','PASS' if allowed else 'FAIL',reason_code(reasons[0]) if reasons else None,blocking=not allowed)
        elif kind=='ENTRY_REJECTED':
            raw=details.get('reason','UNCLASSIFIED');code=reason_code(raw)
            # Preserve the exact existing first failure; detailed bias/cooldown
            # observations already provide the more specific code.
            if raw!='BASELINE_BIAS_OR_COOLDOWN':
                stage='EXECUTION_PERMISSION'
                if code=='ANTI_SPAM_LOCK':stage='ANTI_SPAM_PASS'
                self._stage(t,stage,'FAIL',code,blocking=True)
            t['raw_reasons'].append(str(raw))
        elif kind=='EXECUTION_DECISION' and details.get('intent')!='REDUCE_ONLY_EXIT':
            self._stage(t,'EXECUTION_PERMISSION','PASS')
        elif kind=='ENTRY_ORDER_ATTEMPTED':self._stage(t,'ORDER_ATTEMPTED','PASS')
        elif kind=='ENTRY_FILL':self._stage(t,'FILLED','PASS')
        elif kind=='TRADE_PNL':self._stage(t,'TRADE_COMPLETED','PASS')
        self._save(t)

    def _summary(self,traces):
        n=len(traces)
        rows=[]
        survivors=list(traces)
        for stage in STAGES:
            statuses=Counter(t['stages'][stage]['status'] for t in traces)
            reached=statuses['PASS']+statuses['FAIL']
            previous=len(survivors)
            survivors=[t for t in survivors if t['stages'][stage]['status']=='PASS']
            rows.append(dict(stage=stage,passed=statuses['PASS'],failed=statuses['FAIL'],reached=reached,
                admission_survivors=len(survivors),admission_percent_of_previous=100*len(survivors)/previous if previous else None,
                not_reached=statuses['NOT_REACHED'],not_observed=statuses['NOT_OBSERVED'],
                percent_of_observations=100*statuses['PASS']/n if n else None,
                pass_percent_of_reached=100*statuses['PASS']/reached if reached else None,
                rejection_reasons=dict(Counter(t['stages'][stage]['reason'] for t in traces if t['stages'][stage]['status']=='FAIL'))))
        first=Counter(t['first_blocking_reason'] for t in traces if t['first_blocking_reason'])
        days={t['utc_day'] for t in traces}
        sufficient=n>=100 and len(days)>=3
        return dict(observations=n,dates=len(days),stages=rows,first_blocking_reasons=dict(first),
            first_blocking_percent_of_observations={r:100*c/n for r,c in first.items()} if n else {},
            all_observed_failures=dict(Counter(r for t in traces for r in set(t['all_observed_failed_conditions']))),
            bottleneck_status='OBSERVATIONAL_EVIDENCE' if sufficient else 'INSUFFICIENT OBSERVATIONS',
            top_bottlenecks=first.most_common(5) if sufficient else [],
            note='Counts are unique market-cycle candidates; stages reflect observed production checks. NOT_OBSERVED is not PASS. Existing decision order is retained, including combined friction/risk checks.')

    def report(self):
        traces=list(self.traces.values())
        by=lambda key:{str(v):self._summary([t for t in traces if t[key]==v]) for v in sorted({t[key] for t in traces})}
        distributions={}
        for symbol in sorted({t['symbol'] for t in traces}):
            values=[t for t in traces if t['symbol']==symbol]
            distributions[symbol]=dict(atr_fraction=distribution([t['metrics'].get('atr_fraction') for t in values],.004),
                spread_bps=distribution([t['metrics'].get('spread_bps') for t in values],15,below=True))
        return dict(source=self.source,exchange_orders_submitted=0,session=self._summary(traces),
            per_market=by('symbol'),per_utc_day=by('utc_day'),per_utc_hour=by('utc_hour'),per_weekday=by('weekday'),
            distributions=distributions,
            top3_exclusions=[dict(candidate_id=t['candidate_id'],symbol=t['symbol'],rank=t['scanner_rank'],
                available_setup=t['side_channel_signal'],source='FROZEN_INDICATOR_SIDE_CHANNEL_NOT_EXECUTED')
                for t in traces if t['scanner_rank'] and not t['selected']],
            staleness=[dict(candidate_id=t['candidate_id'],**t['data_evidence']) for t in traces],
            rejection_taxonomy=[r.value for r in RejectionReason])

    def export(self,directory):
        path=Path(directory);path.mkdir(parents=True,exist_ok=True)
        report=safe_data(self.report())
        (path/'funnel_summary.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
        rows=report['session']['stages']
        with (path/'funnel_summary.csv').open('w',newline='') as f:
            fields=['stage','admission_survivors','admission_percent_of_previous','passed','failed','reached','not_reached','not_observed','percent_of_observations','pass_percent_of_reached']
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
        (path/'opportunity_traces.jsonl').write_text(''.join(canonical(safe_data(t))+'\n' for t in self.traces.values()))
        for name,key in [('market_funnel','per_market'),('daily_funnel','per_utc_day'),('hourly_funnel','per_utc_hour'),
                         ('weekday_funnel','per_weekday'),('atr_spread_distributions','distributions'),
                         ('staleness_diagnostics','staleness'),('top3_exclusions','top3_exclusions')]:
            (path/(name+'.json')).write_text(json.dumps(report[key],indent=2,default=str)+'\n')
        summary=report['session']
        lines=['TEAM ANCHORIUM — OPPORTUNITY FUNNEL','Source: '+self.source,
               'Observations: '+str(summary['observations']),'Bottlenecks: '+summary['bottleneck_status']]
        lines.extend(r['stage']+': '+str(r['admission_survivors'])+' admitted through all previous stages; '+str(r['passed'])+' pass / '+str(r['reached'])+' observed checks' for r in rows)
        (path/'opportunity_report.txt').write_text('\n'.join(lines)+'\n')
        return report
