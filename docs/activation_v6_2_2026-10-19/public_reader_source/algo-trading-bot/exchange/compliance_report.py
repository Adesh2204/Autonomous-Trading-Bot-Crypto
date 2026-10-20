"""Secret-free compliance exports, with explicit evidence limits."""
from collections import Counter
import json
from pathlib import Path

from .execution_journal import canonical, safe_data


def compliance_summary(journal, *, mode, position_guard=None):
    rows=list(journal.db.execute('SELECT seq,kind,timestamp_ms,data FROM events ORDER BY seq'))
    decisions=[json.loads(r['data']) for r in rows if r['kind']=='COMPLIANCE_DECISION']
    permits=[json.loads(r['data']) for r in rows if r['kind']=='COMPLIANCE_ACTION_AUTHORIZED']
    snapshots=[json.loads(r['data']) for r in rows if r['kind']=='GLOBAL_POSITION_RECONCILED']
    codes=Counter(d['code'] for d in decisions if d['outcome']=='BLOCK')
    maximum=max((d['actual_position_count'] for d in snapshots),default=None)
    unexplained=sum(d.get('order_classification') is None for d in permits)
    evidence_complete=bool(decisions and snapshots and position_guard and
        position_guard.state.value not in {'UNKNOWN','RECOVERING'} and maximum is not None and maximum<=1 and
        not unexplained and mode!='OFFLINE_SIGNED_FIXTURE' and
        all(d.get('execution_mode')=='LIVE_TESTNET' for d in decisions) and
        all(d.get('execution_mode')=='LIVE_TESTNET' for d in permits))
    return dict(execution_mode=mode,source='LOCAL_DURABLE_COMPLIANCE_EVIDENCE',
        orders_evaluated=len(decisions),strategy_orders_evaluated=sum(
            d.get('order_classification') in {'STRATEGY_ENTRY','STRATEGY_EXIT'} for d in decisions),
        orders_allowed=sum(d['outcome']=='PASS' for d in decisions),
        orders_blocked=sum(d['outcome']=='BLOCK' for d in decisions),
        self_cross_blocks=codes['SELF_CROSS_RISK'],duplicate_blocks=codes['DUPLICATE_ORDER']+codes['DUPLICATE_ORDER_BLOCKED'],
        abnormal_price_blocks=codes['ABNORMAL_PRICE'],unknown_order_blocks=codes['UNEXPLAINED_ORDER']+codes['UNKNOWN_PROTECTION_ORDER'],
        position_limit_blocks=codes['POSITION_LIMIT'],block_codes=dict(codes),
        maximum_simultaneous_positions_observed=maximum,max_global_positions_enforced=1,
        autonomous_usdpr_external_transfers=0,
        external_wallet_transfers_observed=None,
        unexplained_order_permits=unexplained,authorized_order_actions=len(permits),
        compliance_state='PASS' if evidence_complete else 'REVIEW_REQUIRED',
        committee_verdict='NOT_ASSESSED',account_verified=False if mode=='OFFLINE_SIGNED_FIXTURE' else None,
        limits=['This is local bot evidence, not organizer certification.',
            'Manual activity, other computers/accounts and cross-team intent are not observable here.',
            'Allowed means preflight permission; it does not establish an exchange fill or trading profit.',
            'Synthetic fixtures cannot establish funded-account readiness.'])


def export_compliance(directory,journal,*,mode,position_guard=None):
    path=Path(directory)
    path.mkdir(parents=True,exist_ok=True)
    records=[]
    for row in journal.db.execute("SELECT * FROM events WHERE kind LIKE 'COMPLIANCE_%' OR kind LIKE 'GLOBAL_POSITION_%' ORDER BY seq"):
        records.append(dict(json.loads(row['data']),kind=row['kind'],timestamp_ms=row['timestamp_ms'],
                            journal_seq=row['seq'],execution_mode=mode))
    (path/'compliance_events.jsonl').write_text(''.join(canonical(safe_data(r))+'\n' for r in records))
    summary=compliance_summary(journal,mode=mode,position_guard=position_guard)
    (path/'compliance_summary.json').write_text(json.dumps(safe_data(summary),indent=2)+'\n')
    (path/'compliance_summary.txt').write_text('TEAM ANCHORIUM — COMPLIANCE SUMMARY\n'+
        '\n'.join(f'{k}: {v}' for k,v in summary.items() if k not in {'limits','block_codes'})+'\n'+
        '\n'.join(summary['limits'])+'\n')
    return summary
