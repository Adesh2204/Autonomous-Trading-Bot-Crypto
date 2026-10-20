"""Local address derivation and signer lease check; no signatures or HTTP."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.practice_preflight import verify_private_identity, check_local_nonce_ownership
from exchange.paper_operations import active_source_hash
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--team-address', required=True)
    p.add_argument('--api-wallet-address', required=True)
    p.add_argument('--nonce-database', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('preserve previous signer evidence; choose a new output')
    report = dict(execution_mode='PAPER', allow_live_orders=False, signature_created=False,
                  exchange_actions_submitted=0, active_source_hash=active_source_hash(ROOT))
    try:
        report['safety_lock'] = require_paper_migration()
        report['strategy_freeze'] = verify_strategy_freeze()
        report['identity'] = verify_private_identity(ROOT, args.api_wallet_address, args.team_address)
        report['nonce_ownership'] = check_local_nonce_ownership(
            args.nonce_database, args.api_wallet_address, args.team_address, root=ROOT)
        report['status'] = 'LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED'
    except Exception as exc:
        # Only our constant error codes are exported; no parser/key traceback.
        report['status'] = 'FAILED'
        report['error'] = str(exc) if isinstance(exc, ExchangeError) else 'PREFLIGHT_INTERNAL_ERROR'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], output=str(args.output.resolve()),
                          signature_created=False, exchange_actions_submitted=0)))
    return 0 if report['status'] != 'FAILED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
