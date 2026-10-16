"""One bounded public-address accounting/flatness audit, with no signing path."""
from pathlib import Path
from dataclasses import asdict
import os,sys,json
os.environ['ANCHORIUM_PUBLIC_ONLY']='true'
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.exit_recovery import ExitRecovery
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.testnet_certification import TEAM,API
from exchange.paper_operations import atomic_json
from venue_config import require_paper_migration

def main():
    require_paper_migration();out=Path(__file__).resolve().parent/'final_account';out.mkdir(exist_ok=False)
    journal=ExecutionJournal(out/'public.sqlite',session_id='public:final-engineering-audit',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal,signer_address=API);rates.read_budget_wait_seconds=65
    client=HyperliquidClient(ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl'),rate_limits=rates)
    r=dict(exchange_writes=0,signatures_created=0,readbacks=[])
    try:
        client.startup();account=HyperliquidAccount(client,TEAM);recovery=ExitRecovery(account,journal,initial_start_ms=0)
        for _ in range(2):
            report=recovery.recover()
            positions=account.get_positions();orders=account.get_frontend_open_orders()
            r['readbacks'].append(dict(source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',observed_ms=client.clock_ms(),
                positions=[asdict(p) for p in positions.values()],orders=orders,ready=report.ready))
        r.update(account=recovery.state.report(),sqlite_integrity=journal.db.execute('PRAGMA integrity_check').fetchone()[0])
    finally:
        atomic_json(out/'audit.json',r);client.close();journal.close()
    print(json.dumps(dict(status='PUBLIC_ACCOUNT_AUDIT_COMPLETE',readbacks=r['readbacks'])))

if __name__=='__main__':main()
