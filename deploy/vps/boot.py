"""VPS entrypoint (Phase 5): reconcile with the exchange on every boot, then start only if told to.

Fail-closed order:
  1. Read-only exchange reconcile report (pas positions, open orders, fills since the last report),
     written to runtime/vps/boot_report.json. No key is read for this step.
  2. Trading starts ONLY when ANCHORIUM_RUN=continuous is set in the env file AND
     runtime/continuous/stop.flag is absent AND the boot read succeeded. Otherwise the process idles
     and re-reports every hour (so `restart: unless-stopped` never turns into a trading loop).
  3. scripts/run_continuous.py supervise then runs its own startup reconciliation (account recovery,
     position adoption, exchange-fill reconcile) before any order, as on the Mac.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
OUT = ROOT / 'runtime' / 'vps'
STOP = ROOT / 'runtime' / 'continuous' / 'stop.flag'


def boot_report():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM
    from exchange.venue_profiles import venue_profile
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    positions = {s: str(p.quantity) for s, p in account.get_positions().items() if p.quantity}
    orders = [dict(coin=o['coin'], oid=o['oid'], side=o['side'], sz=o['sz'], trigger=o.get('isTrigger'),
                   reduce_only=o.get('reduceOnly')) for o in account.get_frontend_open_orders()]
    since = int(time.time() * 1000) - 24 * 3600 * 1000
    fills = [dict(coin=f.symbol, ms=f.timestamp_ms, tid=f.trade_id, side=f.side, sz=str(f.quantity), px=str(f.price),
                  fee=str(f.fee), closed_pnl=str(f.closed_pnl)) for f in account.get_fills(start_ms=since)]
    return dict(utc=datetime.now(timezone.utc).isoformat(), team=TEAM, positions=positions, orders=orders,
                fills_24h=fills, flat=not positions and not orders)


def write(report):
    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    (OUT / 'boot_report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report.get(k) for k in ('utc', 'flat', 'positions', 'error', 'decision')}), flush=True)


def main():
    while True:
        try:
            report = boot_report()
        except Exception as exc:                       # no exchange truth -> never start trading
            report = dict(utc=datetime.now(timezone.utc).isoformat(), error=f'{type(exc).__name__}:{exc}')
        run = os.environ.get('ANCHORIUM_RUN', '').strip().lower()
        if 'error' in report:
            report['decision'] = 'IDLE_BOOT_READ_FAILED'
        elif run != 'continuous':
            report['decision'] = 'IDLE_TRADING_NOT_ENABLED'
        elif STOP.exists():
            report['decision'] = 'IDLE_STOP_FLAG_PRESENT'
        else:
            report['decision'] = 'START_CONTINUOUS_SUPERVISOR'
        write(report)
        if report['decision'] == 'START_CONTINUOUS_SUPERVISOR':
            code = subprocess.call([sys.executable, str(ROOT / 'scripts' / 'run_continuous.py'), 'supervise'], cwd=str(ROOT))
            write(dict(utc=datetime.now(timezone.utc).isoformat(), decision='SUPERVISOR_EXITED', code=code))
        time.sleep(3600)


if __name__ == '__main__':
    main()
