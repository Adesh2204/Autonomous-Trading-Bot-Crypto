"""Bounded public-account/book inspection; no key access, signature or exchange write."""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json, sqlite3, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from venue_config import require_paper_migration
from exchange.exit_recovery import Environment, ENTRY_MS, QUANTITY, profit_floor
from exchange.execution_journal import fingerprint
from exchange.paper_operations import atomic_json
from exchange.qualification_protection import require_settled_exit_orders
from exchange.qualification_watcher import sweep


def main():
    require_paper_migration()
    output = Path(sys.argv[1])
    if output.exists(): raise RuntimeError('PRESERVE_PRIOR_PUBLIC_SNAPSHOT')
    env = None
    report = dict(started_ms=time.time_ns()//1000000, source='ACTUAL_TESTNET_PAR_INFO',
        signatures_created=0, exchange_writes=0, key_access=False)
    try:
        env = Environment(ROOT)
        original = env.journal.intents()
        certificates = [tuple(r) for r in env.journal.db.execute('SELECT * FROM nontransmission_resolutions')]
        ctx, entry = env.context()
        require_settled_exit_orders(SimpleNamespace(journal=env.journal, account=env.account, client=env.client))
        fee = env.provider.conservative_fee(ctx)
        funding = sum((f.cashflow for f in env.recovery.state.funding.values()
            if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS), D(0))
        be, floor = profit_floor(ctx.spec, QUANTITY, entry.quantity*entry.price, entry.fee, fee, funding)
        book = env.provider.books['par:BTC']
        limit = ctx.spec.normalize_price(max(floor,ctx.quote.bid*D('.999')), 'SELL')
        report.update(status='AUTHORITATIVE_OPEN_LONG_VERIFIED', observed_ms=env.client.clock_ms(),
            source_hash=env.source, policy_hash=env.policy_hash,
            context=asdict(ctx), account=env.recovery.state.report(), entry=asdict(entry),
            book=asdict(book), bid=str(ctx.quote.bid), ask=str(ctx.quote.ask),
            conservative_exit_fee=str(fee), deployer_fee_scale=env.provider.current_fee_scale,
            funding=str(funding), break_even=str(be), minimum_sell=str(floor), planned_limit=str(limit),
            depth=sweep(book.bids,QUANTITY,limit,'SELL'),
            estimated_net_at_bid=str(QUANTITY*ctx.quote.bid*(1-fee)-entry.quantity*entry.price-entry.fee+funding),
            estimated_net_at_limit=str(QUANTITY*limit*(1-fee)-entry.quantity*entry.price-entry.fee+funding),
            exit_barrier_passed=True, raw_intents_unchanged=env.journal.intents()==original,
            certificates_unchanged=[tuple(r) for r in env.journal.db.execute('SELECT * FROM nontransmission_resolutions')]==certificates,
            raw_intents_fingerprint=fingerprint(original), certificate_fingerprint=fingerprint(certificates),
            checkpoint_error=env.recovery.checkpoint_error,
            journal_integrity=env.journal.db.execute('PRAGMA integrity_check').fetchone()[0],
            reconciliation=asdict(env.recovery.last_report), protection_verified=False)
        with sqlite3.connect((ROOT/'runtime/testnet/anchorium-bot-1/nonces.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            report['nonce_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
        if not report['raw_intents_unchanged'] or not report['certificates_unchanged']:
            raise RuntimeError('HISTORICAL_JOURNAL_CHANGED_DURING_READ')
    except Exception as exc:
        report.update(status='READ_ONLY_CHECK_HALTED',error_type=type(exc).__name__)
        from exchange.base_exchange import ExchangeError
        if isinstance(exc, ExchangeError): report['error']=str(exc)
        raise
    finally:
        report['finished_ms']=time.time_ns()//1000000
        atomic_json(output,report)
        if env: env.close()
    print(json.dumps({k:report[k] for k in ('status','observed_ms','bid','ask','funding','break_even',
        'minimum_sell','estimated_net_at_bid','estimated_net_at_limit','exit_barrier_passed',
        'raw_intents_unchanged','certificates_unchanged','journal_integrity','nonce_integrity')},indent=2))


if __name__=='__main__': main()
