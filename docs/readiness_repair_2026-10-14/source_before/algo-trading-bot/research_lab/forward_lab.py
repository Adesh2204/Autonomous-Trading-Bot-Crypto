"""Independent local portfolios over the SAME verified public observation tape.

The existing scanner, management, risk and accounting kernels are reused. Only
the separate research brain's VWAP assignments and an optional risk veto vary.
No historical OHLC creates a fill. No production module imports this laboratory.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import json
import math
import numpy as np
from research_intelligence.common import ResearchError, digest, immutable_json, canonical, utc_day
from research_intelligence.campaign import campaign_identity
from research_intelligence.evidence import read_evidence
from research_intelligence.anchors import AnchorResearchBrain, VWAP_BASELINE_UTC,validate_frame
from research_intelligence.experiment import policies_from_config
from research_intelligence.dataset import build_dataset, feature_manifest, ASSET_CLASS, SETUPS, regime, feature_evidence_from_events
from research_intelligence.models import MetaController
from exchange.base_exchange import ExchangeError, BookLevel, OrderBook, Candle
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import make_quote
from exchange.paper_execution import PaperExecution
from exchange.perpetual_economics import FeeSchedule
from candle_normalizer import candles_to_frame
from crypto_paper_bot import CryptoPaperBot
from market_regime_scanner import MarketRegimeScanner, ScannerPolicy
from risk.models import RiskPolicy
from risk.portfolio_risk import PortfolioRisk
from session_manager import SessionManager
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def portable(value): return json.loads(json.dumps(value, default=str, allow_nan=False))


class RecordedMarket:
    def __init__(self, first):
        self.current = first; self.histories = {}; self.now = first['decision_ms']
        self.client = HyperliquidClient(self._info, clock_ms=lambda:self.now)
        self.update(first); self.client.startup()

    def _info(self, payload):
        if payload == {'type':'perpDexs'}: return deepcopy(self.current['dexes'])
        if payload == {'type':'meta', 'dex':'par'}: return deepcopy(self.current['metadata'])
        raise ResearchError('RECORDED_LAB_METADATA_READ_ONLY')

    def update(self, frame):
        if frame['decision_ms'] < self.now: raise ResearchError('LAB_CLOCK_REGRESSED')
        self.current = deepcopy(frame); self.now = frame['decision_ms']
        for symbol, rows in frame.get('histories', {}).items():
            parsed=[Candle(**{k:Decimal(v) if k in {'open','high','low','close','volume'} else v for k,v in c.items()}) for c in rows]
            if frame.get('history_mode','REPLACE')=='APPEND':
                values={c.timestamp_ms:c for c in self.histories.get(symbol,[])}
                values.update({c.timestamp_ms:c for c in parsed})
                parsed=[values[k] for k in sorted(values)]
            self.histories[symbol]=parsed[-frame.get('history_limit',5000):]

    def get_asset_contexts(self):
        contexts = self.current['contexts']
        if set(contexts) != set(self.client.markets): raise ExchangeError('LAB_CONTEXT_UNIVERSE_INCOMPLETE')
        for s in contexts:
            if not 0 <= self.now-self.current['context_times'][s] <= 60000:
                raise ExchangeError('ASSET_CONTEXT_STALE')
        return deepcopy(contexts)

    def get_orderbook(self, symbol):
        try: raw = self.current['books'][symbol]
        except KeyError: raise ExchangeError('NO_EXECUTABLE_TWO_SIDED_BOOK') from None
        return OrderBook(**dict(raw, bids=tuple(BookLevel(Decimal(x['price']),Decimal(x['quantity'])) for x in raw['bids']),
                               asks=tuple(BookLevel(Decimal(x['price']),Decimal(x['quantity'])) for x in raw['asks'])))

    def get_quote(self, symbol):
        if not self.current.get('connected'): raise ExchangeError('STREAM_NOT_HEALTHY')
        t = self.current['context_times'].get(symbol)
        if t is None or not 0 <= self.now-t <= 60000: raise ExchangeError('ASSET_CONTEXT_STALE')
        return make_quote(self.get_orderbook(symbol), self.current['contexts'][symbol], self.now, mark_timestamp_ms=t)

    def get_candles(self, symbol, start_ms, end_ms, *, now_ms=None):
        return [c for c in self.histories.get(symbol, []) if start_ms <= c.timestamp_ms <= end_ms and c.timestamp_ms+60000 <= self.now]


class HistoryBackedAnchorBrain(AnchorResearchBrain):
    """Only two assignments consult full anchor history; brain input stays baseline.

    Feeding a longer frame into the complete brain could change its anti-spam
    cursor. Keep the original scanner window for ALL other formula/state logic.
    The extra history supplies only the separately compiled VWAP assignments.
    """
    support=None

    def aligned(self,values,frame):
        lookup={t:float(v) for t,v in zip(self.support.Timestamp,values)}
        return np.asarray([lookup[t] for t in frame.Timestamp],dtype=float)

    def _vwap(self,frame):
        return self.aligned(super()._vwap(self.support),frame)

    def _slope(self,frame):
        full=self.support.copy(); full['VWAP']=super()._vwap(full)
        return self.aligned(super()._slope(full),frame)


class PolicyBrain:
    def __init__(self, policies,market=None):
        self.policies = policies
        self.market=market
        self.brains = {'VWAP_BASELINE_UTC':AnchorResearchBrain()}
        self.brains.update({p.policy_id:HistoryBackedAnchorBrain(p) for p in policies.values()})

    def policy(self, symbol): return self.policies.get(symbol, VWAP_BASELINE_UTC)

    def evaluate_candles(self, candles):
        if not candles: raise ExchangeError('NO_COMPLETED_CANDLES')
        p = self.policy(candles[0].symbol); brain = self.brains[p.policy_id]
        frame = candles_to_frame(candles)
        coverage=frame
        if p.anchor_type!='UTC_MIDNIGHT':
            if self.market is None: raise ResearchError('RECEIPTED_ANCHOR_HISTORY_REQUIRED')
            full=[c for c in self.market.histories[candles[0].symbol] if c.timestamp_ms<=candles[-1].timestamp_ms]
            coverage=candles_to_frame(full); validate_frame(coverage,self.market.now)
            brain.support=coverage
        if not brain.coverage_complete(coverage): raise ExchangeError('TRUNCATED_ANCHOR_HISTORY')
        return brain.evaluate_frame(frame)


def candidate_observation(arm, d, decision_ms, policy_brain, risk_policy):
    signal = d.signal or {}; setup = signal.get('signal_type')
    if setup not in SETUPS or not (signal.get('long') or signal.get('short')): return None
    if not d.snapshot: return None
    policy = policy_brain.policy(d.symbol)
    enriched = policy_brain.evaluate_candles(d.candles); last = enriched.iloc[-1]
    close = float(last.Close); source = d.candles[-1].timestamp_ms+60000
    available = max(c.received_timestamp_ms for c in d.candles)
    unit = {e['name']:e['units'] for e in feature_manifest()['features']}
    evidence = feature_evidence_from_events([dict(candidate_id='temporary', market_snapshot=portable(asdict(d.snapshot)))])['temporary']
    values = dict(atr_fraction=float(last.ATR_14)/close, vwap_distance_fraction=(close-float(last.VWAP))/close,
        vwap_slope_fraction=float(last.VWAP_Slope)/close, ema9=float(last.EMA_9), ema21=float(last.EMA_21),
        ema_separation_fraction=(float(last.EMA_9)-float(last.EMA_21))/close,
        candles_since_anchor=sum(c.timestamp_ms >= int(policy.anchor_at(last.Timestamp.to_pydatetime()).timestamp()*1000) for c in d.candles),
        realized_volatility=float(d.metrics['realized_volatility']), available_liquidity=float(d.metrics['window_notional_approx']),
        daily_bias=signal['bias'])
    for name, value in values.items():
        evidence[name] = dict(value=value, source='VERIFIED_RECEIPT_FROZEN_CANDIDATE', source_ms=source,
                              available_ms=available, units=unit[name])
    evidence['estimated_slippage_bps'] = dict(value=float(risk_policy.slippage_bps),
        source='UNCHANGED_PRESPECIFIED_RISK_ASSUMPTION_NOT_MEASURED_SLIPPAGE', source_ms=decision_ms,
        available_ms=decision_ms, units='bps')
    return dict(candidate_id=arm+':'+d.symbol+':'+str(decision_ms), original_candidate_id=d.symbol+':'+str(decision_ms),
        symbol=d.symbol, decision_ms=decision_ms, valid_strategy_candidate=True, setup_type=setup,
        direction=SETUPS[setup], anchor_policy_id=policy.policy_id, candidate_kind='REJECTED_CANDIDATE',
        feature_evidence=evidence, risk_decision='NOT_REACHED', source='VERIFIED_PUBLIC_TAPE_LOCAL_PAPER')


class PermissionRisk:
    """An optional numerical veto runs AFTER unchanged perpetual risk approval."""
    def __init__(self, baseline, mode, controllers):
        self.baseline=baseline; self.policy=baseline.policy; self.mode=mode; self.controllers=controllers
        self.rows={}; self.decisions=[]; self.last_audit={}

    def assess(self, spec, side, reference, atr, quote, portfolio, quotes, now_ms, **kwargs):
        result = self.baseline.assess(spec, side, reference, atr, quote, portfolio, quotes, now_ms, **kwargs)
        self.last_audit = deepcopy(self.baseline.last_audit)
        if not result.allowed or self.mode == 'NO_ML': return result
        row = self.rows.get(spec.symbol)
        if row is None: return replace(result, allowed=False, reasons=('ML_UNAVAILABLE',))
        controller = self.controllers.get(row['anchor_policy_id'], MetaController())
        scored = controller.score(row); self.decisions.append(scored)
        self.last_audit['meta_controller'] = scored
        if scored['status'] != 'ALLOW': return replace(result, allowed=False, reasons=(scored['status'],))
        return result


class AuditedPaperExecution(PaperExecution):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.fill_quotes={}
    def simulate_fill(self,order_id,quote):
        result=super().simulate_fill(order_id,quote)
        if result: self.fill_quotes[result.fill_id]=portable(asdict(quote))
        return result


class LabArm:
    def __init__(self, name, market, config, policies, controllers=None):
        self.name=name; self.market=market; self.config=config
        selected = policies if name.startswith('SESSION') else {}
        self.brain=PolicyBrain(selected,market)
        self.scanner=MarketRegimeScanner(market, ScannerPolicy(**config['scanner']))
        self.scanner.brain=self.brain
        fees=FeeSchedule(**config['fees']); risk=RiskPolicy(**config['risk'])
        self.risk=PermissionRisk(PortfolioRisk(risk,fees), 'ML' if name in {'UTC_ML','SESSION_ML'} else 'NO_ML', controllers or {})
        self.id_seq=0
        def ids(prefix):
            self.id_seq+=1; return name+'-'+prefix+str(self.id_seq)
        self.execution=AuditedPaperExecution(market.client.markets,fees=fees,clock_ms=market.client.clock_ms,
            starting_collateral=config['starting_collateral'],leverage=risk.leverage,id_factory=ids)
        self.bot=CryptoPaperBot(market,self.scanner,self.execution,self.risk)
        self.observations={}; self.equity=[]; self.faults=[]; self.scans=[]; self.frames=0
        self.generation=None; self.last_sample_ms=None

    def step(self, frame):
        self.frames+=1; self.market.update(frame); now=frame['decision_ms']
        try:
            if self.last_sample_ms is not None and now-self.last_sample_ms>5000:
                self.faults.append(dict(timestamp_ms=now,reason='OBSERVATION_GAP_OVER_FIVE_SECONDS'))
                self.bot.breakers.pause('research_gap','OBSERVATION_GAP_OVER_FIVE_SECONDS')
            if self.generation is not None and self.generation != frame['generation']:
                self.faults.append(dict(timestamp_ms=now,reason='RECONNECT_REQUIRES_NEW_CONTINUOUS_EVIDENCE_WINDOW'))
                self.bot.breakers.pause('research_gap','RECONNECT_REQUIRES_NEW_CONTINUOUS_EVIDENCE_WINDOW')
            self.generation=frame['generation']; self.last_sample_ms=now
            quotes={s:self.market.get_quote(s) for s in self.execution.portfolio.positions}
            snapshot=self.bot.observe(quotes)
            if self.bot.accounting_halt: raise ExchangeError(self.bot.accounting_halt)
            if frame.get('histories'): self.bot.observe_completed_candles(self.market.histories)
            if frame['scan']:
                scan=self.scanner.scan()
                for d in scan.diagnostics:
                    if d.snapshot:
                        d.snapshot=replace(d.snapshot,mark_observed_at_ms=frame['context_times'][d.symbol])
                    observation=candidate_observation(self.name,d,scan.observed_at_ms,self.brain,self.risk.policy)
                    if observation:
                        self.observations[observation['original_candidate_id']]=observation
                rows,_=build_dataset(list(self.observations.values()),assumptions=self.config)
                self.risk.rows={r['symbol']:r for r in rows if r['decision_ms']==scan.observed_at_ms}
                snapshot=self.bot.consume_scan(scan)
                if self.bot.accounting_halt: raise ExchangeError(self.bot.accounting_halt)
                self.scans.append(dict(decision_ms=now,status=scan.status,watchlist=scan.watchlist,
                    diagnostics=[dict(symbol=d.symbol,reasons=d.reasons,qualified=d.qualified,signal=portable(d.signal),metrics=portable(d.metrics),
                        candle_count=len(d.candles),policy_id=self.brain.policy(d.symbol).policy_id) for d in scan.diagnostics]))
            self.equity.append(dict(**portable(asdict(snapshot)),held_symbols=sorted(self.execution.portfolio.positions),
                                    frame_hash=frame.get('receipt_hash')))
        except (ExchangeError, ResearchError) as exc:
            self.faults.append(dict(timestamp_ms=now,reason=str(exc)))
            self.bot.breakers.pause('research_evidence',str(exc))

    def export(self):
        executed={f.candidate_id for f in self.execution.fills}
        risks={d['candidate_id']:d['decision']['allowed'] for d in self.bot.decisions if d['kind']=='RISK_DECISION'}
        observations=[]; outcomes={}; audits=[]
        for original, o in self.observations.items():
            o=deepcopy(o); o['risk_decision']='PASS' if risks.get(original) else 'REJECTED' if original in risks else 'NOT_REACHED'
            if original in executed: o['candidate_kind']='EXECUTED_CANDIDATE'
            observations.append(o)
        for trade in self.bot.closed_trades:
            if self.faults: continue  # Unknown management/funding intervals never produce training labels.
            original=trade['candidate_id']; o=self.observations.get(original)
            if not o: continue
            fills=[f for f in self.execution.fills if f.candidate_id==original]
            entries=[f for f in fills if f.side==('BUY' if o['direction']=='LONG' else 'SELL')]
            exits=[f for f in fills if f not in entries]
            if not entries or not exits or sum(f.quantity for f in entries)!=sum(f.quantity for f in exits):
                raise ResearchError('CLOSED_TRADE_FILL_QUANTITIES_UNBALANCED')
            entries_ids={f.fill_id for f in fills}
            ledger=[e for e in self.execution.portfolio.events if e.get('fill_id') in entries_ids]
            if len(ledger)!=len(fills): raise ResearchError('FILL_LEDGER_LINEAGE_INCOMPLETE')
            gross=sum((e['realized_pnl'] for e in ledger),Decimal(0)); fee=sum((f.fee for f in fills),Decimal(0))
            funding=[e for e in self.execution.portfolio.events if e['kind']=='FUNDING' and e['symbol']==o['symbol']
                and min(f.timestamp_ms for f in entries)<e['timestamp_ms']<=trade['completed_at_ms']]
            funding_cost=-sum((e['cashflow'] for e in funding),Decimal(0))
            if abs(gross-fee-funding_cost-trade['net_pnl'])>Decimal('0.00000001'):
                raise ResearchError('TRADE_CASH_COST_RECONCILIATION_FAILED')
            fill_audits=[]
            for f in fills:
                q=self.execution.fill_quotes[f.fill_id]; expected=q['ask'] if f.side=='BUY' else q['bid']
                if Decimal(expected)!=f.price: raise ResearchError('FILL_NOT_AT_RECORDED_BBO')
                fill_audits.append(dict(fill=portable(asdict(f)),quote=q))
            receipt=dict(candidate_id=o['candidate_id'],decision_ms=o['decision_ms'],symbol=o['symbol'],direction=o['direction'],
                anchor_policy_id=o['anchor_policy_id'],completed_ms=trade['completed_at_ms'],source='RECORDED_PAPER_SIMULATION',
                fill_model='OBSERVED_EXECUTABLE_BBO',entry_fill_ids=[f.fill_id for f in entries],exit_fill_ids=[f.fill_id for f in exits],
                management_version='FROZEN_BASELINE',assumptions_hash=digest(self.config),gross_result=float(gross),fees=float(fee),
                slippage=0.0,funding_cost=float(funding_cost),
                slippage_note='BBO spread is already included in executed prices. Additional price impact assumed zero; explicit fee/impact stress is reported separately.',
                label_audit_hash=digest(dict(fills=fill_audits,ledger=portable(ledger),funding=portable(funding))))
            outcomes[o['candidate_id']]=receipt
            audits.append(dict(candidate_id=o['candidate_id'],audit_hash=receipt['label_audit_hash'],fills=fill_audits,
                               ledger=portable(ledger),funding=portable(funding)))
        return observations,outcomes,audits


def portfolio_metrics(arm):
    samples=arm.equity; capital=float(arm.config['starting_collateral'])
    empty=dict(net_pnl=None,net_return=None,max_drawdown=None,daily_equity_volatility=None,time_in_market=None)
    if not samples: return dict(**empty,status='NO_VALUED_PORTFOLIO_OBSERVATIONS',closed_trades=0,samples=0,faults=len(arm.faults))
    eq=[capital]+[float(s['equity']) for s in samples]; peak=capital; dd=0
    for v in eq: peak=max(peak,v); dd=max(dd,(peak-v)/peak)
    days={utc_day(s['timestamp_ms']):float(s['equity']) for s in samples}
    returns=[]; prev=capital
    for day,equity in sorted(days.items()): returns.append(equity/prev-1); prev=equity
    duration=max(0,samples[-1]['timestamp_ms']-samples[0]['timestamp_ms'])
    held=sum(b['timestamp_ms']-a['timestamp_ms'] for a,b in zip(samples,samples[1:]) if a['held_symbols'])
    costs=[]
    last=samples[-1]
    # Analytical extra-friction stress on observed fills. This does not rerun
    # changed margins/stops/quantities under higher fees and is labelled so.
    filled_notional=sum(float(f.quantity*f.price) for f in arm.execution.fills)
    for multiplier,impact_bps in ((1,0),(1.5,5),(2,10)):
        costs.append(dict(fee_multiplier=multiplier,additional_impact_bps=impact_bps,
            stressed_net_pnl=eq[-1]-capital-(multiplier-1)*float(last['fees_paid'])-impact_bps/10000*filled_notional,
            scope='ANALYTICAL_STRESS_ON_OBSERVED_FILLS_NOT_NEW_EXECUTION_PATH'))
    return dict(status='LOCAL_PAPER_OBSERVED_PATH' if not arm.faults else 'INCOMPLETE_EVIDENCE_PATH',
        samples=len(samples),days=len(days),closed_trades=len(arm.bot.closed_trades),local_fills=len(arm.execution.fills),
        net_pnl=eq[-1]-capital,net_return=eq[-1]/capital-1,max_drawdown=dd,
        daily_equity_volatility=float(np.std(returns,ddof=1)) if len(returns)>=3 else None,
        daily_volatility_note='Observed UTC daily endpoints; first/final partial days must be excluded for promotion.',
        time_in_market=held/duration if duration else None,duration_ms=duration,fees=float(last['fees_paid']),
        funding_cost=-float(last['funding_cashflow']),open_positions=sorted(arm.execution.portfolio.positions),
        faults=len(arm.faults),cost_sensitivity=costs,
        valuation_scope='Sampled mark-equity drawdown, not intratick or official competition scoring')


def run_forward_lab(capture_path, output, *, sealed_models=None, evaluation_start_ms=None,evaluation_end_ms=None):
    require_paper_migration(); verify_strategy_freeze()
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    models=sealed_models or {}; arms={}; evidence_root=None; count=0; manifest=None; warmup=None
    try:
        for manifest, record in read_evidence(capture_path):
            frame=deepcopy(record['payload']); frame['receipt_hash']=record['sha256']
            if warmup is None: warmup=RecordedMarket(frame)
            else: warmup.update(frame)
            if evaluation_start_ms is not None and frame['decision_ms']<evaluation_start_ms: continue
            if evaluation_end_ms is not None and frame['decision_ms']>=evaluation_end_ms: continue
            if not arms:
                if not warmup.histories: raise ResearchError('INITIAL_LAB_HISTORY_REQUIRED')
                initial=deepcopy(frame)
                initial['histories']={s:[portable(asdict(c)) for c in cs] for s,cs in warmup.histories.items()}
                initial['history_mode']='REPLACE'
                policies=policies_from_config(manifest['anchor_config'])
                for name in ('UTC_NO_ML','SESSION_NO_ML','UTC_ML','SESSION_ML'):
                    arms[name]=LabArm(name,RecordedMarket(initial),manifest['parameters'],policies,models)
            for arm in arms.values(): arm.step(frame)
            count+=1; evidence_root=record['sha256']
        if manifest is None or not arms: raise ResearchError('NO_COMPLETE_PUBLIC_FRAMES')
        all_obs=[]; all_outcomes={}; totals={}
        for name,arm in arms.items():
            directory=output/name; directory.mkdir()
            obs,outcomes,audits=arm.export(); all_obs.extend(obs); all_outcomes.update(outcomes)
            for filename, rows in [('candidates.jsonl',obs),('label_audits.jsonl',audits),('equity.jsonl',arm.equity),
                ('fills.jsonl',[portable(asdict(f)) for f in arm.execution.fills]),('decisions.jsonl',arm.bot.decisions),
                ('scans.jsonl',arm.scans),('faults.jsonl',arm.faults),('ml_decisions.jsonl',arm.risk.decisions)]:
                with (directory/filename).open('x') as f:
                    for row in rows: f.write(canonical(portable(row))+'\n')
            immutable_json(directory/'outcomes.json',outcomes)
            metric=portfolio_metrics(arm)
            if name in {'UTC_ML','SESSION_ML'} and not models:
                metric['status']='ML_UNAVAILABLE'; metric['comparison_eligible']=False
                metric['reason']='No sealed model; ML arms refuse entries and their flat results are not evidence of benefit.'
            else: metric['comparison_eligible']=not arm.faults
            totals[name]=metric; immutable_json(directory/'portfolio_metrics.json',metric)
        with (output/'candidates.jsonl').open('x') as f:
            for o in all_obs: f.write(canonical(o)+'\n')
        immutable_json(output/'outcomes.json',all_outcomes)
        rows,quality=build_dataset(all_obs,all_outcomes,assumptions=manifest['parameters'])
        immutable_json(output/'data_quality.json',quality)
        immutable_json(output/'assumptions.json',manifest['parameters'])
        summary=dict(schema_version=1,capture_manifest_hash=manifest['sha256'],source=manifest['source'],
            source_identity=campaign_identity(),source_capture=str(Path(capture_path).resolve()),last_frame_hash=evidence_root,
            source_capture_completion_hash=digest(json.loads((Path(capture_path)/'capture_completion.json').read_text())),
            frames=count,models={k:v.model['model_version'] for k,v in models.items()},evaluation_start_ms=evaluation_start_ms,evaluation_end_ms=evaluation_end_ms,
            baseline_preserved=True,production_changed=False,exchange_orders_submitted=0,execution_mode='PAPER',
            portfolios=totals,quality=quality,model_evidence='PROSPECTIVE_ONLY' if evaluation_start_ms is not None else 'NO_PROSPECTIVE_MODEL_CLAIM',
            limitations=['Independent hypothetical portfolios, no wallet P&L.', 'Historical candles cannot supply historical BBO or past availability.',
                'Each arm has its own USDPR collateral, management, capital, cooldown, fills and funding.',
                'Unconfigured session assets remain explicit UTC controls.', 'All raw receipts and label audits must remain available.'])
        import hashlib
        summary['artifact_sha256']={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file()}
        summary['sha256']=digest(summary); immutable_json(output/'lab_manifest.json',summary)
        return summary
    except Exception as exc:
        immutable_json(output/'lab_failure.json',dict(reason=type(exc).__name__+':'+str(exc),
            production_changed=False,exchange_orders_submitted=0)); raise
