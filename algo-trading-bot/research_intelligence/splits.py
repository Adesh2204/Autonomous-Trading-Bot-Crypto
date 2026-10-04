"""Chronological candidate splits, outcome-boundary purge and explicit embargo."""
from dataclasses import dataclass, asdict
from .common import ResearchError, stamp, digest


@dataclass(frozen=True)
class ChronologicalSplit:
    validation_start_ms: int
    holdout_start_ms: int
    validation_tune_start_ms: int
    embargo_ms: int = 3600000

    def __post_init__(self):
        for t in (self.validation_start_ms,self.holdout_start_ms,self.validation_tune_start_ms,self.embargo_ms): stamp(t)
        if not self.validation_start_ms < self.validation_tune_start_ms < self.holdout_start_ms:
            raise ResearchError('CHRONOLOGICAL_SPLIT_BOUNDARIES_REQUIRED')

    def partition(self, rows):
        result = dict(train=[],calibration=[],validation=[],holdout=[],purged=[])
        seen = set()
        for row in sorted(rows,key=lambda r:(r['decision_ms'],r['candidate_id'])):
            cid = row['candidate_id']
            if cid in seen: raise ResearchError('DUPLICATE_CANDIDATE_SPLIT')
            seen.add(cid); t = stamp(row['decision_ms'])
            end = row.get('outcome_end_ms')
            if end is not None and (stamp(end)<t): raise ResearchError('OUTCOME_TIME_REGRESSION')
            if t < self.validation_start_ms:
                name='train'; boundary=self.validation_start_ms
            elif t < self.validation_tune_start_ms:
                name='calibration'; boundary=self.validation_tune_start_ms
            elif t < self.holdout_start_ms:
                name='validation'; boundary=self.holdout_start_ms
            else: name='holdout'; boundary=None
            # Purge decision and label horizons near each *next* split; no fabricated completion.
            if boundary is not None and (t >= boundary-self.embargo_ms or end is not None and end >= boundary-self.embargo_ms):
                result['purged'].append(dict(candidate_id=cid,reason='OUTCOME_OR_DECISION_OVERLAPS_NEXT_SPLIT'))
            else: result[name].append(row)
        return result

    def manifest(self, rows):
        p=self.partition(rows)
        return dict(policy=asdict(self),split_candidate_ids={k:[r['candidate_id'] for r in p[k]] for k in ('train','calibration','validation','holdout')},
                    purged=p['purged'],random_shuffle=False,transform_fit_scope='TRAIN_ONLY',
                    calibration_fit_scope='EARLY_VALIDATION_ONLY',threshold_selection_scope='LATE_VALIDATION_ONLY',
                    holdout_used_for_tuning=False,sha256=digest(asdict(self)))
