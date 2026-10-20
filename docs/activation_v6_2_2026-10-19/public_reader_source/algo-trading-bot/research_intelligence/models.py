"""Small deterministic NumPy models; JSON only, no pickle, network or signer.

Direction is metadata from the frozen strategy, never a learned output. Training
transforms fit once on the earlier split; probability calibration uses only the
earlier validation segment. Thresholds never consult the holdout.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import numpy as np
from .common import ResearchError, digest, finite, immutable_json
from .dataset import NUMERIC,CATEGORICAL,REQUIRED
from .metrics import classification,performance,grouped_performance,day_block_interval

SEED=20261004
LIFECYCLE=('RESEARCH','VALIDATED','PROMOTION_CANDIDATE','REJECTED','RETIRED')


def sigmoid(x): return 1/(1+np.exp(-np.clip(x,-35,35)))


def fit_transform(rows):
    if not rows: raise ResearchError('TRAINING_ROWS_REQUIRED')
    medians=[];means=[];scales=[]
    for name in NUMERIC:
        observed=[r['features'][name] for r in rows if r['features'][name] is not None]
        medians.append(float(np.median(observed)) if observed else 0.0)
    raw=np.array([[medians[i] if r['features'][n] is None else r['features'][n] for i,n in enumerate(NUMERIC)] for r in rows])
    means=raw.mean(axis=0);scales=raw.std(axis=0);scales[scales<1e-12]=1
    vocab={n:sorted({str(r['features'][n]) for r in rows if r['features'][n] is not None}) for n in CATEGORICAL}
    names=list(NUMERIC)+[n+':missing' for n in NUMERIC]+[n+'='+v for n in CATEGORICAL for v in vocab[n]]
    return dict(numeric=list(NUMERIC),categorical=list(CATEGORICAL),medians=medians,means=means.tolist(),scales=scales.tolist(),
                vocab=vocab,feature_names=names,fit_candidate_ids=[r['candidate_id'] for r in rows],fit_scope='TRAIN_ONLY')


def transform(rows, state):
    result=[]
    for row in rows:
        f=row['features'];values=[f[n] for n in state['numeric']]
        raw=np.array([state['medians'][i] if v is None else finite(v) for i,v in enumerate(values)])
        scaled=(raw-np.array(state['means']))/np.array(state['scales'])
        if not np.isfinite(scaled).all(): raise ResearchError('INVALID_TRANSFORM')
        result.append(list(scaled)+[float(v is None) for v in values]+[float(str(f[n])==v) for n in state['categorical'] for v in state['vocab'][n]])
    return np.array(result,dtype=float).reshape(len(rows),len(state['feature_names']))


def fit_logistic(x,y,*,iterations=600,l2=.05):
    w=np.zeros(x.shape[1]);b=0.0
    for _ in range(iterations):
        error=sigmoid(x@w+b)-y;w-=.05*(x.T@error/len(y)+l2*w);b-=.05*float(error.mean())
    return dict(weights=w.tolist(),intercept=b,iterations=iterations,l2=l2,learning_rate=.05)


def fit_tree(x,y,depth=3,min_leaf=15):
    p=float((y.sum()+1)/(len(y)+2));node=dict(probability=p,rows=len(y),positives=int(y.sum()))
    if not depth or len(y)<2*min_leaf or len(set(y))<2:return node
    base=len(y)*2*y.mean()*(1-y.mean());best=None
    for j in range(x.shape[1]):
        unique=np.unique(x[:,j])
        if len(unique)<2:continue
        thresholds=(unique[:-1]+unique[1:])/2
        if len(thresholds)>16:thresholds=thresholds[np.linspace(0,len(thresholds)-1,16,dtype=int)]
        for threshold in thresholds:
            left=x[:,j]<=threshold;n=int(left.sum());m=len(y)-n
            if min(n,m)<min_leaf:continue
            impurity=n*2*y[left].mean()*(1-y[left].mean())+m*2*y[~left].mean()*(1-y[~left].mean())
            gain=float(base-impurity)
            if best is None or gain>best[0]+1e-12:best=(gain,j,float(threshold),left)
    if best is None or best[0]<=1e-12:return node
    gain,j,threshold,left=best
    return dict(**node,feature=j,threshold=threshold,gain=gain,
                left=fit_tree(x[left],y[left],depth-1,min_leaf),right=fit_tree(x[~left],y[~left],depth-1,min_leaf))


def tree_probability(x,tree):
    result=[]
    for values in x:
        node=tree
        while 'feature' in node:node=node['left'] if values[node['feature']]<=node['threshold'] else node['right']
        result.append(node['probability'])
    return np.array(result)


def raw_probability(x, model):
    if model['model_type']=='LOGISTIC':return sigmoid(x@np.array(model['parameters']['weights'])+model['parameters']['intercept'])
    if model['model_type']=='SHALLOW_TREE':return tree_probability(x,model['parameters'])
    raise ResearchError('UNKNOWN_MODEL_TYPE')


def calibrate(raw,y):
    z=np.log(np.clip(raw,1e-6,1-1e-6)/(1-np.clip(raw,1e-6,1-1e-6)));a=1.0;b=0.0
    for _ in range(400):
        e=sigmoid(a*z+b)-y;a-=.03*(float(np.mean(e*z))+.01*(a-1));b-=.03*float(e.mean())
    return dict(type='PLATT_LOGIT',a=a,b=b,fit_scope='EARLY_VALIDATION_ONLY',iterations=400)


def probability(rows,model):
    x=transform(rows,model['transform']);raw=raw_probability(x,model);c=model['calibration']
    z=np.log(np.clip(raw,1e-6,1-1e-6)/(1-np.clip(raw,1e-6,1-1e-6)))
    return sigmoid(c['a']*z+c['b'])


def choose_threshold(rows,p):
    baseline=performance(rows);choices=[]
    for t in (.4,.5,.6,.7):
        accepted=[r for r,q in zip(rows,p) if q>=t];metric=performance(accepted)
        if len(accepted)>=20 and metric['max_realized_drawdown'] is not None and metric['max_realized_drawdown']<=baseline['max_realized_drawdown']+1e-9:
            choices.append((metric['net_pnl'],t))
    return max(choices)[1] if choices else .5


def train_models(partition, feature_hash, source_hash, dataset_hash):
    train=partition['train'];cal=partition['calibration'];val=partition['validation']
    for group in (train,cal,val):
        if not group or len({r['label'] for r in group})<2:raise ResearchError('BOTH_CLASSES_REQUIRED_IN_EACH_FIT_SPLIT')
    policies={r['anchor_policy_id'] for group in (train,cal,val) for r in group}
    if len(policies)!=1:raise ResearchError('ONE_ANCHOR_PROGRAM_PER_MODEL_REQUIRED')
    transformer=fit_transform(train);x=transform(train,transformer);y=np.array([r['label'] for r in train]);models=[]
    for kind in ('LOGISTIC','SHALLOW_TREE'):
        model=dict(schema_version=1,state='RESEARCH',model_type=kind,transform=deepcopy(transformer),
            parameters=fit_logistic(x,y) if kind=='LOGISTIC' else fit_tree(x,y),seed=SEED,
            feature_manifest_hash=feature_hash,source_hash=source_hash,dataset_hash=dataset_hash,anchor_policy_id=next(iter(policies)),
            direction_prediction=False,order_capability=False,sizing_multiplier=1.0)
        raw=raw_probability(transform(cal,transformer),model);model['calibration']=calibrate(raw,np.array([r['label'] for r in cal]))
        model['calibration']['fit_candidate_ids']=[r['candidate_id'] for r in cal]
        model['threshold']=choose_threshold(val,probability(val,model))
        model['threshold_candidate_ids']=[r['candidate_id'] for r in val]
        model['model_version']=digest(model)
        models.append(model)
    return models


def model_importance(model):
    names=model['transform']['feature_names'];values=np.zeros(len(names))
    if model['model_type']=='LOGISTIC':values=np.abs(model['parameters']['weights'])
    else:
        def visit(n):
            if 'feature' in n:values[n['feature']]+=n['gain'];visit(n['left']);visit(n['right'])
        visit(model['parameters'])
    total=float(np.sum(values))
    return [dict(feature=n,importance=float(v)/total if total else 0,method='ABS_STANDARDIZED_COEFFICIENT' if model['model_type']=='LOGISTIC' else 'TRAIN_GINI_GAIN') for n,v in zip(names,values)]


def evaluate_model(rows,model):
    p=probability(rows,model) if rows else [];accepted=[r for r,q in zip(rows,p) if q>=model['threshold']]
    market_metrics={}
    for symbol in sorted({r['symbol'] for r in rows}):
        indices=[i for i,r in enumerate(rows) if r['symbol']==symbol]
        market_metrics[symbol]=classification([rows[i]['label'] for i in indices],[p[i] for i in indices],model['threshold'])
    return dict(classification=classification([r['label'] for r in rows],p,model['threshold']),per_market_classification=market_metrics,
        accepted_candidates=len(accepted),conditional_trading=performance(accepted),baseline_no_ml=performance(rows),
        cost_sensitivity={str(m):performance(accepted,cost_multiplier=m) for m in (1,1.5,2)},
        per_market=grouped_performance(accepted,'symbol'),regime=grouped_performance(accepted,'regime'),
        per_direction=grouped_performance(accepted,'direction'),uncertainty=day_block_interval(accepted),
        unseen_market_rows=sum(r['symbol'] not in model['transform']['vocab']['symbol'] for r in rows),
        note='Recorded candidate subsets are conditional outcomes, not changed portfolio execution.')


class MetaController:
    order_capability=False
    def __init__(self,model=None,*,feature_hash=None):
        self.model=deepcopy(model)
        if self.model:
            m=self.model;version=m.pop('model_version',None);valid=digest(m)==version;m['model_version']=version
            if not valid or m.get('schema_version')!=1 or m.get('state') not in LIFECYCLE or m.get('direction_prediction') is not False or m.get('order_capability') is not False:
                raise ResearchError('MODEL_ARTIFACT_INVALID')
            if feature_hash is not None and m.get('feature_manifest_hash')!=feature_hash:raise ResearchError('FEATURE_MANIFEST_VERSION_MISMATCH')
            self._validate_schema(m)

    @staticmethod
    def _validate_schema(m):
        try:
            if not 0<=finite(m['threshold'])<=1:raise ResearchError('MODEL_THRESHOLD_INVALID')
            state=m['transform']
            if tuple(state['numeric'])!=NUMERIC or tuple(state['categorical'])!=CATEGORICAL or state['fit_scope']!='TRAIN_ONLY':raise ResearchError('TRANSFORM_SCHEMA_INVALID')
            for key in ('medians','means','scales'):
                if len(state[key])!=len(NUMERIC):raise ResearchError('TRANSFORM_SHAPE_INVALID')
                for x in state[key]:finite(x)
            if any(x<=0 for x in state['scales']):raise ResearchError('TRANSFORM_SCALE_INVALID')
            for n in CATEGORICAL:
                if any(type(v) is not str for v in state['vocab'][n]) or len(set(state['vocab'][n]))!=len(state['vocab'][n]):raise ResearchError('ENCODING_SCHEMA_INVALID')
            names=list(NUMERIC)+[n+':missing' for n in NUMERIC]+[n+'='+v for n in CATEGORICAL for v in state['vocab'][n]]
            if names!=state['feature_names']:raise ResearchError('FEATURE_ORDER_INVALID')
            cal=m['calibration']
            if cal['type']!='PLATT_LOGIT' or cal['fit_scope']!='EARLY_VALIDATION_ONLY':raise ResearchError('CALIBRATION_SCHEMA_INVALID')
            finite(cal['a']);finite(cal['b'])
            if m['model_type']=='LOGISTIC':
                if len(m['parameters']['weights'])!=len(names):raise ResearchError('MODEL_SHAPE_INVALID')
                for w in m['parameters']['weights']:finite(w)
                finite(m['parameters']['intercept'])
            elif m['model_type']=='SHALLOW_TREE':
                def validate(node,depth=0):
                    if depth>3 or not 0<=finite(node['probability'])<=1:raise ResearchError('TREE_SCHEMA_INVALID')
                    if 'feature' in node:
                        if type(node['feature']) is not int or not 0<=node['feature']<len(names):raise ResearchError('TREE_FEATURE_INVALID')
                        finite(node['threshold']);validate(node['left'],depth+1);validate(node['right'],depth+1)
                validate(m['parameters'])
            else:raise ResearchError('MODEL_TYPE_INVALID')
        except (KeyError,TypeError,IndexError) as exc:raise ResearchError('MODEL_SCHEMA_INVALID') from exc

    @classmethod
    def load(cls,path,**kwargs):
        try:return cls(json.loads(Path(path).read_text()),**kwargs)
        except (OSError,ValueError,KeyError,TypeError):return cls()

    def score(self,row):
        from .dataset import SETUPS
        if SETUPS.get(row.get('setup_type'))!=row.get('direction'):raise ResearchError('DETERMINISTIC_DIRECTION_REQUIRED')
        if row['features'].get('symbol')!=row['symbol'] or row['features'].get('direction')!=row['direction'] or row['features'].get('anchor_policy_id')!=row['anchor_policy_id']:
            raise ResearchError('SCORING_CANDIDATE_IDENTITY_MISMATCH')
        base=dict(candidate_id=row['candidate_id'],symbol=row['symbol'],direction=row['direction'],
                  setup_type=row['setup_type'],anchor_policy_id=row['anchor_policy_id'],regime=row['regime'],
                  feature_values=deepcopy(row['features']),risk_decision=row.get('risk_decision','NOT_OBSERVED'),
                  final_decision='RESEARCH_RECOMMENDATION_ONLY',exchange_orders_submitted=0)
        if not self.model or self.model['state'] in {'REJECTED','RETIRED'} or self.model.get('anchor_policy_id')!=row['anchor_policy_id'] or not row.get('scoring_ready') or any(row['features'].get(n) is None for n in REQUIRED):
            return dict(**base,status='ML_UNAVAILABLE',confidence=None,threshold=None,model_version=None,explanation=[])
        # Recheck timestamps at the scoring boundary, not just during dataset construction.
        for proof in row['feature_provenance'].values():
            if not proof['source_ms']<=proof['available_ms']<=row['decision_ms']:raise ResearchError('SCORING_FEATURE_LOOKAHEAD')
        from .dataset import feature_manifest
        for entry in feature_manifest()['features']:
            if row['features'].get(entry['name']) is not None:
                proof=row['feature_provenance'].get(entry['name'])
                if proof is None:raise ResearchError('SCORING_PROVENANCE_REQUIRED')
                if proof.get('units')!=entry['units'] or not proof.get('source'):raise ResearchError('SCORING_FEATURE_SCHEMA_INVALID')
                if entry['max_age_ms'] is not None and row['decision_ms']-proof['source_ms']>entry['max_age_ms']:
                    return dict(**base,status='ML_UNAVAILABLE',confidence=None,threshold=None,model_version=m.get('model_version') if (m:=self.model) else None,explanation=[])
        m=self.model;q=float(probability([row],m)[0]);x=transform([row],m['transform'])[0];names=m['transform']['feature_names']
        if m['model_type']=='LOGISTIC':
            contributions=[dict(feature=n,value=float(v),raw_logit_contribution=float(v*w)) for n,v,w in zip(names,x,m['parameters']['weights'])]
            explanation=sorted(contributions,key=lambda d:-abs(d['raw_logit_contribution']))[:6]
        else:
            explanation=[];node=m['parameters']
            while 'feature' in node:
                j=node['feature'];left=x[j]<=node['threshold'];explanation.append(dict(feature=names[j],transformed_value=float(x[j]),threshold=node['threshold'],branch='LE' if left else 'GT'))
                node=node['left'] if left else node['right']
        return dict(**base,status='ALLOW' if q>=m['threshold'] else 'ML_META_FILTER',confidence=q,threshold=m['threshold'],
            model_version=m['model_version'],explanation=explanation,
            explanation_scope='Actual raw-model coefficient contributions or tree path; calibrated confidence uses recorded Platt transform')


def save_model(path,model): immutable_json(path,model)
