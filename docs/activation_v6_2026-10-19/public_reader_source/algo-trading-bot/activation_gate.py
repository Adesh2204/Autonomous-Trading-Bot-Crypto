"""Dated activation evidence. Configuration flags alone never authorize live execution."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from execution_safety import SafetyError

P0_CHECKS=(
    'instrument_identity','confirmed_fills','integer_quantity_risk','daily_reserved_risk',
    'partial_entry_exit','broker_protection','protection_failure_unwind','restart_recovery',
    'broker_local_mismatch','duplicate_accounting','environment_isolation','entry_cutoff',
    'flatten_sequence','broker_flat_confirmation','one_position','scale_in_disabled',
)
BROKER_CHECKS=('static_ip','limit_and_stop_limit','cancellation_and_partial_fills',
    'intraday_eligibility_and_restrictions','account_fee_plan','rms_flatten_deadline',
    'contract_note_reconciliation','observed_emergency_flatten')


def source_fingerprint():
    root=Path(__file__).parent
    digest=hashlib.sha256()
    for path in sorted(root.glob('*.py')):
        if path.name.startswith('test_') or path.name=='safety_test_support.py':continue
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_activation(path,now):
    try:
        evidence=json.loads(Path(path).read_text())
        start=datetime.fromisoformat(evidence['generated_at'])
        end=datetime.fromisoformat(evidence['verified_until'])
        if (evidence['recommendation']!='OBSERVED_LIVE_PILOT_READY' or evidence['environment']!='LIVE' or
            start.tzinfo is None or end.tzinfo is None or not start<=now<=end or
            evidence['source_fingerprint']!=source_fingerprint() or
            evidence['tests']['failed']!=0 or evidence['tests']['passed']<len(P0_CHECKS) or
            not evidence['tests']['artifact'] or not evidence['broker_evidence'] or
            any(evidence['p0_checks'].get(k)!='PASS' for k in P0_CHECKS) or
            any(evidence['broker_checks'].get(k)!='PASS' for k in BROKER_CHECKS)):
            raise SafetyError('LIVE_ACTIVATION_EVIDENCE_INVALID')
        return evidence
    except (OSError,TypeError,ValueError,KeyError) as exc:
        raise SafetyError('LIVE_ACTIVATION_EVIDENCE_INVALID') from exc
