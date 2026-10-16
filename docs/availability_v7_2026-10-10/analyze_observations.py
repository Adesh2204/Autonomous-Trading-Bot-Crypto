"""Offline, source-bound summaries/plots of actual V7 observations. No clients."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
from statistics import median,stdev
import csv,hashlib,json,math,os,sys
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1]
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/anchorium-v7-matplotlib')
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def iso(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat() if ms is not None else None
def quantiles(values):
 a=sorted(values)
 def q(p):
  if not a:return None
  i=(len(a)-1)*p;l=int(i);h=min(l+1,len(a)-1);return a[l]+(a[h]-a[l])*(i-l)
 return {'n':len(a),'median':q(.5),'p90':q(.9),'p95':q(.95),'p99':q(.99),'max':max(a) if a else None}

receipt=read(BASE/'short_15m/short_15m_paper_receipt.json')
assert receipt['source_unchanged'] and receipt['exit_code']==0
segment=Path(receipt['final_health']['segment']);snapshot=read(segment/'candle_availability.json')
rows=[];source_summary={};evidence=[]
for symbol,m in sorted(snapshot['markets'].items()):
 source_counts=Counter();delays={s:[] for s in ('REST','WS')};covered=rest_later=conflicts=0
 records=m['interval_observations']
 for t_str,r in sorted(records.items(),key=lambda kv:int(kv[0])):
  t=int(t_str);live=snapshot['observation_started_ms']<r['expected_close_ms']<=snapshot['observed_at_ms']
  rest=r['sources'].get('REST',{});ws=r['sources'].get('WS',{})
  completed=[k for k,v in r['sources'].items() if v.get('first_completed_observed_at_ms') is not None]
  if r['rest_absent_count']:
   covered+=1
   evidence.append({'market':symbol,'minute_start_utc':iso(t),'minute_start_ms':t,
    'expected_close_utc':iso(r['expected_close_ms']),'covering_rest_absent_count':r['rest_absent_count'],
    'first_missing_observation_utc':iso(r['missing_first_observed_ms']),
    'first_rest_completed_reception_utc':iso(rest.get('first_completed_observed_at_ms')),
    'first_ws_completed_reception_utc':iso(ws.get('first_completed_observed_at_ms')),
    'cache_missing_at_final':t in m['missing_timestamps_ms'],'rejected':r['rejected'],'conflict':r['conflict'],
    'cause':'UNDERLYING_CAUSE_UNDETERMINED; COVERED_RESPONSE_ABSENCE_OBSERVED'})
  if r['rest_absent_count'] and rest.get('first_completed_observed_at_ms') is not None and rest['first_completed_observed_at_ms']>r['missing_first_observed_ms']:rest_later+=1
  conflicts+=bool(r['conflict'])
  for source in ('REST','WS'):
   v=r['sources'].get(source,{})
   observed=v.get('first_completed_observed_at_ms')
   if live and observed is not None:delays[source].append(observed-r['expected_close_ms'])
   rows.append({'market':symbol,'source':source,'minute_start_utc':iso(t),'minute_start_ms':t,
    'logical_close_ms':r['expected_close_ms'],'first_observed_at_ms':v.get('first_observed_at_ms'),
    'first_completed_observed_at_ms':observed,'observation_delay_ms':observed-r['expected_close_ms'] if live and observed is not None else None,
    'censoring':'LIVE_OBSERVED' if live and observed is not None else 'LIVE_RIGHT_CENSORED' if live else 'STARTUP_LEFT_CENSORED',
    'observations':v.get('observations',0),'duplicate_observations':v.get('duplicates',0),
    'covered_rest_absences':r['rest_absent_count'],'conflict':r['conflict']})
 source_summary[symbol]={'intervals_absent_in_at_least_one_covered_rest':covered,
  'those_later_observed_completed_through_rest':rest_later,'conflicting_intervals':conflicts,
  'current_missing_classifications':dict(Counter(k for v in m['missing_classifications'].values() for k in v)),
  'latency':{s:quantiles(delays[s]) for s in delays},'censoring':m['latency']}
with (BASE/'candle_observation_intervals.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
atomic_json(BASE/'native_source_findings.json',{'source_hash':receipt['source_hash_before'],
 'availability_sha256':sha(segment/'candle_availability.json'),'markets':source_summary,
 'distinct_interval_scope':'RETENTION_WINDOW_ACROSS_THIS_FRESH_RUN; NOT ONLY_FINAL_300',
 'latency_scope':'LOCAL_COMPLETED_RECEPTION_MINUS_LOGICAL_CLOSE; STARTUP_EXCLUDED; NOT_EXCHANGE_PUBLICATION_TIME',
 'missing_reason_counts_overlap':True})
atomic_json(BASE/'organizer_missing_minute_evidence.json',{'source_hash':receipt['source_hash_before'],
 'network':'testnet','dex':'par','run_started_utc':iso(int(receipt['started_unix']*1000)),
 'run_finished_utc':iso(int(receipt['finished_unix']*1000)),
 'underlying_exchange_cause':'UNDETERMINED','intervals':evidence})

comparison=read(BASE/'external_capture/comparison.json');capture=read(BASE/'external_capture/native_and_external_capture.json')
by_symbol={r['symbol']:r for r in capture};by_result={r['native_symbol']:r for r in comparison['results']}
external_stats={};comparison_rows=[]
for symbol,m in sorted(snapshot['markets'].items()):
 item=by_symbol.get(symbol);result=by_result.get(symbol,{})
 if not item:
  external_stats[symbol]={'verdict':'EXTERNAL_SOURCE_UNVERIFIED','reason':result.get('reason','NO_RECORDED_CAPTURE'),'matched':0};continue
 decision=result['decision_ms']
 native={c['timestamp_ms']:c for c in item['candles'] if c['timestamp_ms']+60000<=decision and c.get('received_timestamp_ms') is not None and c['received_timestamp_ms']<=decision}
 external={c['timestamp_ms']:c for c in item['external'] if c['timestamp_ms']+60000<=decision and c['observed_at_ms']<=decision}
 times=sorted(native.keys()&external.keys());differences={k:[] for k in ('open','high','low','close')}
 for t in times:
  row={'market':symbol,'timestamp_ms':t,'utc':iso(t),'decision_ms':decision}
  for k in differences:
   a=float(native[t][k]);b=float(external[t][k]);bps=(b/a-1)*10000
   differences[k].append(bps);row.update({k+'_native':a,k+'_external':b,k+'_difference':b-a,k+'_difference_bps':bps})
  comparison_rows.append(row)
 # Return pairs must be exactly adjacent genuine matched minutes, never bridge gaps.
 nr=[];er=[]
 for a,b in zip(times,times[1:]):
  if b-a!=60000:continue
  nr.append(math.log(float(native[b]['close'])/float(native[a]['close'])))
  er.append(math.log(float(external[b]['close'])/float(external[a]['close'])))
 ext_latest=max(external,default=None)
 external_stats[symbol]={'verdict':result['verdict'],'matched':len(times),'decision_utc':iso(decision),
  'close_difference_bps':quantiles(differences['close']),
  'ohlc_difference_bps':{k:quantiles(v) for k,v in differences.items()},
  'realized_volatility':{'adjacent_matched_return_pairs':len(nr),'native_log_return_sample_sd':stdev(nr) if len(nr)>1 else None,
   'external_log_return_sample_sd':stdev(er) if len(er)>1 else None,'scope':'ONE_MINUTE_SAMPLE; NOT_ANNUALIZED; NO_GAP_INTERPOLATION'},
  'native_missing_percent':result.get('native_missing_percent'),'external_missing_percent':result.get('external_missing_percent'),
  'external_latest_close_age_ms':decision-ext_latest-60000 if ext_latest is not None else None,
  'source_publication_latency':'UNKNOWN; EXTERNAL_CAPTURE_IS_SINGLE_RECEPTION',
  'volume_comparable':False,'VWAP_EMA_ATR_signals':'NOT ENOUGH EVIDENCE; UNAPPROVED_VOLUME/UTC_PREREQUISITES',
  'signal_count':None,'signal_agreement':None,'signal_timing_divergence':None,
  'native_executable_quote_if_fresh':result.get('native_execution_quote'),
  'trade_feasibility':None,'fees_slippage_outcomes':None,
  'limit':'As-of price/volatility observation only; no approved signal, historical book or fills'}
atomic_json(BASE/'external_price_analysis.json',{'source_hash':receipt['source_hash_before'],
 'capture_sha256':sha(BASE/'external_capture/native_and_external_capture.json'),
 'label':'EXTERNAL_RESEARCH_ONLY_NO_EXECUTION','counterfactual_verdict':'NOT ENOUGH EVIDENCE',
 'markets':external_stats})
if comparison_rows:
 with (BASE/'external_ohlc_comparison.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(comparison_rows[0]));w.writeheader();w.writerows(comparison_rows)
try:
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams.update({'figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False})
 symbols=sorted(snapshot['markets']);fig,ax=plt.subplots(figsize=(10,5))
 present=[snapshot['markets'][s]['present'] for s in symbols];missing=[snapshot['markets'][s]['missing'] for s in symbols]
 ax.barh(symbols,present,color='#16a085',label='Genuine cached bars');ax.barh(symbols,missing,left=present,color='#c0392b',label='Missing expected minutes')
 ax.set(xlim=(0,300),xlabel='Latest 300 expected completed UTC minutes',title='Native par availability at PAPER shutdown')
 ax.legend(loc='lower center',bbox_to_anchor=(.5,1.09),ncol=2);fig.tight_layout();fig.savefig(BASE/'native_availability.png');plt.close(fig)
 fig,ax=plt.subplots(figsize=(10,5))
 for s in symbols:
  data=[r for r in rows if r['market']==s and r['source']=='WS' and r['censoring']=='LIVE_OBSERVED']
  if data:ax.scatter([datetime.fromtimestamp(r['logical_close_ms']/1000,timezone.utc) for r in data],[r['observation_delay_ms']/1000 for r in data],s=12,label=s)
 ax.set(xlabel='Genuine minute close (UTC)',ylabel='First completed WS reception delay (seconds)',title='Observed arrival delay — network and venue effects not separable')
 if ax.collections:ax.legend(fontsize=7,ncol=3)
 else:ax.text(.5,.5,'No completed WS reception samples',ha='center',transform=ax.transAxes)
 fig.autofmt_xdate();fig.tight_layout();fig.savefig(BASE/'native_ws_delay.png');plt.close(fig)
 fig,ax=plt.subplots(figsize=(10,5))
 for symbol in symbols:
  data=[r for r in rows if r['market']==symbol and r['source']=='REST' and r['censoring']=='LIVE_OBSERVED']
  if data:ax.scatter([datetime.fromtimestamp(r['logical_close_ms']/1000,timezone.utc) for r in data],[r['observation_delay_ms']/1000 for r in data],s=24,label=symbol+' (n='+str(len(data))+')')
 ax.set(xlabel='Genuine minute close (UTC)',ylabel='First completed REST reception delay (seconds)',title='Observed REST arrivals — small samples, polling/network effects included')
 if ax.collections:ax.legend(fontsize=8)
 else:ax.text(.5,.5,'No completed REST reception samples',ha='center',transform=ax.transAxes)
 fig.autofmt_xdate();fig.tight_layout();fig.savefig(BASE/'native_rest_delay.png');plt.close(fig)
 fig,axes=plt.subplots(5,2,figsize=(12,14));
 for s,ax in zip(symbols,axes.flat):
  data=[r for r in comparison_rows if r['market']==s]
  if data:
   x=[];y=[];previous=None
   for point in data:
    if previous is not None and point['timestamp_ms']-previous!=60000:
     x.append(datetime.fromtimestamp(point['timestamp_ms']/1000,timezone.utc));y.append(float('nan'))
    x.append(datetime.fromtimestamp(point['timestamp_ms']/1000,timezone.utc));y.append(point['close_difference_bps']);previous=point['timestamp_ms']
   ax.plot(x,y,linewidth=.8)
  else:ax.text(.5,.5,'No as-of matched data',ha='center',transform=ax.transAxes)
  ax.set_title(s+' — external/native close difference');ax.set_ylabel('bps');ax.tick_params(axis='x',labelrotation=30,labelsize=7)
 fig.suptitle('External price research only — volume equivalence unverified',y=.999);fig.tight_layout();fig.savefig(BASE/'external_close_basis.png');plt.close(fig)
except ImportError:
 (BASE/'plot_limit.txt').write_text('Plotting dependency unavailable; exact CSV/JSON observations preserved.\n')
print(json.dumps({'native_markets':len(source_summary),'covered_response_absent_intervals':len(evidence),'matched_price_rows':len(comparison_rows),'external_assets':len(external_stats)}))
