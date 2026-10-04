"""Fit/seal BEFORE future evaluation. No production activation operation exists."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import time
from .common import ROOT, ResearchError, digest, immutable_json, source_identity, HoldoutLedger, canonical,stamp
from .dataset import build_dataset, feature_manifest
from .experiment import data_gate, policies_from_config
from .models import train_models, evaluate_model, MetaController, save_model
from .splits import ChronologicalSplit


def verified_json(path, hash_field='sha256'):
    value=json.loads(Path(path).read_text()); body=deepcopy(value); expected=body.pop(hash_field,None)
    if digest(body)!=expected: raise ResearchError('ARTIFACT_CHECKSUM_INVALID')
    return value


def read_lines(path): return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def campaign_identity():
    identity=source_identity()
    paths=[p for p in (ROOT/'algo-trading-bot').rglob('*.py') if not p.name.startswith('test_') and '__pycache__' not in p.parts]
    paths += [ROOT/'scripts/collect_research_evidence.py',ROOT/'scripts/run_research_readiness.py']
    identity['file_sha256'].update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    identity['source_hash']=digest(identity['file_sha256'])
    return identity


def verified_lab(directory):
    directory=Path(directory); manifest=verified_json(directory/'lab_manifest.json')
    from .evidence import read_evidence
    capture_path=Path(manifest['source_capture'])
    capture_manifest=verified_json(capture_path/'capture_manifest.json')
    if capture_manifest['sha256']!=manifest['capture_manifest_hash'] or digest(json.loads((capture_path/'capture_completion.json').read_text()))!=manifest.get('source_capture_completion_hash'):
        raise ResearchError('SOURCE_CAPTURE_MODIFIED')
    for _ in read_evidence(capture_path): pass  # Verify all source receipts and the sealed tail again.
    if not manifest.get('artifact_sha256'): raise ResearchError('LAB_ARTIFACT_HASHES_REQUIRED')
    for name, expected in manifest['artifact_sha256'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()): raise ResearchError('ARTIFACT_PATH_OUTSIDE_LAB')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ResearchError('LAB_ARTIFACT_MODIFIED')
    for arm in ('UTC_NO_ML','SESSION_NO_ML','UTC_ML','SESSION_ML'):
        outcomes=json.loads((directory/arm/'outcomes.json').read_text())
        audits={a['candidate_id']:a for a in read_lines(directory/arm/'label_audits.jsonl')}
        for cid, o in outcomes.items():
            a=audits.get(cid)
            if a is None: raise ResearchError('LABEL_AUDIT_MISSING')
            body={k:a[k] for k in ('fills','ledger','funding')}
            if digest(body)!=a['audit_hash'] or o.get('label_audit_hash')!=a['audit_hash']:
                raise ResearchError('LABEL_AUDIT_HASH_MISMATCH')
            ids={r['fill']['fill_id'] for r in a['fills']}
            if ids!=set(o['entry_fill_ids']+o['exit_fill_ids']): raise ResearchError('LABEL_FILL_IDS_MISMATCH')
            net=sum(float(e['realized_pnl'])-float(e['fee']) for e in a['ledger'])+sum(float(e['cashflow']) for e in a['funding'])
            if abs(net-(o['gross_result']-o['fees']-o['slippage']-o['funding_cost']))>1e-7:
                raise ResearchError('LABEL_COST_RECONCILIATION_FAILED')
    return manifest


def audited_dataset(labs):
    observations=[]; outcomes={}; assumptions=None; source=[]; seen=set(); anchors=None
    for path in labs:
        m=verified_lab(path)
        if m['source']!='PUBLIC_TESTNET_PAR_FORWARD_CAPTURE': raise ResearchError('GENUINE_PUBLIC_EVIDENCE_REQUIRED')
        config=json.loads((Path(path)/'assumptions.json').read_text())
        capture=verified_json(Path(m['source_capture'])/'capture_manifest.json')
        if assumptions is None: assumptions=config; anchors=capture['anchor_config']
        if digest(config)!=digest(assumptions) or digest(capture['anchor_config'])!=digest(anchors):
            raise ResearchError('MATCHED_RISK_COST_ANCHOR_ASSUMPTIONS_REQUIRED')
        source.append(dict(lab=str(Path(path).resolve()),sha256=m['sha256']))
        # Filtered portfolios would change the training sample. Fit only no-ML
        # reference arms; overlap/replayed runs never become extra observations.
        for arm in ('UTC_NO_ML','SESSION_NO_ML'):
            rows=read_lines(Path(path)/arm/'candidates.jsonl')
            for r in rows:
                if arm=='SESSION_NO_ML' and r['anchor_policy_id']=='VWAP_BASELINE_UTC': continue
                if r['candidate_id'] in seen: raise ResearchError('DUPLICATE_TRAINING_EVIDENCE')
                seen.add(r['candidate_id']); observations.append(r)
            outcomes.update(json.loads((Path(path)/arm/'outcomes.json').read_text()))
    if assumptions is None: raise ResearchError('LAB_DATA_REQUIRED')
    rows,quality=build_dataset(observations,outcomes,assumptions=assumptions)
    return rows,quality,assumptions,anchors,source


def required_policies(anchors):
    # Named identical-boundary controls retain identities; do not pool their
    # labels under a different anchor/model domain to inflate sample counts.
    return ['VWAP_BASELINE_UTC']+sorted({p.policy_id for p in policies_from_config(anchors).values()})


def seal_campaign(labs, output, *, split, holdout_end_ms, now_ms=None):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    now=time.time_ns()//1000000 if now_ms is None else now_ms
    stamp(now); stamp(holdout_end_ms)
    if not now < split.holdout_start_ms < holdout_end_ms: raise ResearchError('SEAL_MUST_PRECEDE_FUTURE_HOLDOUT')
    rows,quality,assumptions,anchors,sources=audited_dataset(labs)
    if any(r['decision_ms']>=split.holdout_start_ms or r.get('outcome_end_ms') is not None and r['outcome_end_ms']>=split.holdout_start_ms for r in rows):
        raise ResearchError('ALREADY_OBSERVED_HOLDOUT_CANNOT_BE_UNTOUCHED')
    defaults=json.loads((ROOT/'research/configurations/experiment_defaults.json').read_text())
    checks={}; partitions={}; models={}; results={}; identities=campaign_identity()
    for policy in required_policies(anchors):
        group=[r for r in rows if r['anchor_policy_id']==policy and r['scoring_ready'] and r['label'] is not None]
        counts=dict(usable_labeled_rows=len(group),labeled_dates=sorted({r['utc_day'] for r in group}),
            labeled_markets=sorted({r['symbol'] for r in group}),positive_outcomes=sum(r['label']==1 for r in group),
            negative_outcomes=sum(r['outcome']['net_result']<0 for r in group),
            directions={d:sum(r['direction']==d for r in group) for d in ('LONG','SHORT')})
        # Single-asset session policies are assessed within their declared asset
        # domain. The three-market floor applies to the cross-asset UTC program.
        policy_defaults=dict(defaults,minimum_labeled_markets=3 if policy=='VWAP_BASELINE_UTC' else 1)
        gate=data_gate(counts,policy_defaults); p=split.partition(group)
        fit_ok=all(len(p[n])>=defaults['minimum_'+n] and len({r['label'] for r in p[n]})==2
            and min(sum(r['label']==c for r in p[n]) for c in (0,1))>=defaults['minimum_class_per_partition']
            for n in ('train','calibration','validation'))
        checks[policy]=dict(**gate,counts=counts,fit_partitions_ready=fit_ok,
            partition_counts={n:len(p[n]) for n in p},market_domain_floor=policy_defaults['minimum_labeled_markets'])
        partitions[policy]=p
    ready=all(g['status']=='ELIGIBLE_FOR_RESEARCH_FIT' and g['fit_partitions_ready'] for g in checks.values())
    if ready:
        for policy,p in partitions.items():
            fitted=train_models(p,digest(feature_manifest()),identities['source_hash'],digest(rows))
            for model in fitted:
                save_model(output/(model['model_version']+'.json'),model)
            # One model family chosen in advance; tree retained for diagnostics.
            chosen=next(m for m in fitted if m['model_type']=='LOGISTIC')
            models[policy]=dict(version=chosen['model_version'],path=chosen['model_version']+'.json',
                train_positive_fraction=sum(r['label'] for r in p['train'])/len(p['train']))
            results[policy]={m['model_version']:evaluate_model(p['validation'],m) for m in fitted}
    immutable_json(output/'training_readiness.json',dict(quality=quality,per_policy=checks,ready=ready,
        prospective_holdout_not_read=True,source_labs=sources))
    if not ready: return dict(status='MORE_DATA_REQUIRED',per_policy=checks,models={},production_changed=False)
    campaign=dict(schema_version=1,state='SEALED_RESEARCH',created_ms=now,source_identity=identities,
        assumptions=assumptions,anchor_config=anchors,source_labs=sources,dataset_hash=digest(rows),
        split=asdict(split),holdout_end_ms=holdout_end_ms,models=models,defaults=defaults,
        validation_metrics=results,model_family_prespecified='LOGISTIC',
        training_data_readiness=checks,
        holdout_used_for_tuning=False,production_changed=False,activation_authorized=False,
        recommendation_policy='Paired complete-day portfolio evidence, after-cost lower confidence bound, risk/cost stress and calibrated held-out candidate evidence required.')
    campaign['sha256']=digest(campaign); immutable_json(output/'sealed_campaign.json',campaign)
    return campaign


def load_campaign(directory):
    directory=Path(directory); campaign=verified_json(directory/'sealed_campaign.json')
    if campaign['state']!='SEALED_RESEARCH' or campaign['activation_authorized'] is not False or campaign['production_changed'] is not False:
        raise ResearchError('RESEARCH_CAMPAIGN_REQUIRED')
    if not campaign.get('training_data_readiness') or any(g['status']!='ELIGIBLE_FOR_RESEARCH_FIT' or not g['fit_partitions_ready'] for g in campaign['training_data_readiness'].values()):
        raise ResearchError('SEALED_TRAINING_DATA_READINESS_REQUIRED')
    if campaign['source_identity']['source_hash']!=campaign_identity()['source_hash']:
        raise ResearchError('SEALED_RESEARCH_SOURCE_CHANGED')
    if not campaign['created_ms']<campaign['split']['holdout_start_ms']<campaign['holdout_end_ms']:
        raise ResearchError('PROSPECTIVE_HOLDOUT_BOUNDARIES_REQUIRED')
    controllers={}
    for policy,entry in campaign['models'].items():
        path=(directory/entry['path']).resolve()
        if not path.is_relative_to(directory.resolve()): raise ResearchError('MODEL_PATH_OUTSIDE_CAMPAIGN')
        controller=MetaController.load(path,feature_hash=digest(feature_manifest()))
        if not controller.model or controller.model['model_version']!=entry['version'] or controller.model['anchor_policy_id']!=policy:
            raise ResearchError('SEALED_MODEL_MISSING_OR_MODIFIED')
        controllers[policy]=controller
    if sorted(controllers)!=sorted(required_policies(campaign['anchor_config'])): raise ResearchError('MODEL_DOMAIN_COVERAGE_INCOMPLETE')
    return campaign,controllers
