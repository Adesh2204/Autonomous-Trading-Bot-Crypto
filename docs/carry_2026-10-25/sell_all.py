"""Sell the whole carry basket to flat, at the user's order, and stop when every leg is flat.

4 Nov 2026 17:20 IST (user, strict: "sell everything fast ... lock in this profit immediately"; then "yes, close all"
after being told a sweep through the thin books is not allowed and would cost most of the profit): the carry runtime is
started with the CURRENT mandate and release (nothing in the source hash changes) and, right after its startup
reconciliation and before its first cycle, takes its existing halt-and-flatten path (halt(..., flatten=True)): entries
stop and every held leg is unwound EMERGENCY with reduce-only IOC children at the touch, at most 25% of the depth within
5 bps, one child at a time, never a sweep. Nothing is bought. The halt is sticky in carry_state.json, so a restart of this
script (or of run_carry.py start) keeps unwinding. Stops it once every leg is CLOSED; stop.flag stops it any time.
"""
from pathlib import Path
import importlib.util, json, logging, os, signal, subprocess, sys, threading

ROOT = Path(__file__).resolve().parents[2]
REASON = 'USER_ORDERED_SELL_ALL'


def main():
    found = subprocess.run(['pgrep', '-f', 'run_carry.py (start|supervise)|sell_all.py'], capture_output=True,
                           text=True).stdout.split()
    python = lambda pid: 'python' in subprocess.run(['ps', '-o', 'comm=', '-p', pid], capture_output=True,
                                                    text=True).stdout.lower()
    others = {pid for pid in found if pid != str(os.getpid()) and python(pid)}
    if others:
        raise SystemExit(f'Another carry runtime is running ({sorted(others)}); refusing.')
    spec = importlib.util.spec_from_file_location('run_carry', ROOT / 'scripts' / 'run_carry.py')
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    from exchange.carry_basket import build_carry_basket_runtime
    rc.setup_logging(rc.STATE, 'carry.log')
    log = logging.getLogger('carry-sell-all')
    (rc.STATE / 'sell_all.json').write_text(json.dumps(dict(ordered_utc='2026-11-04T11:50:00+00:00', reason=REASON)))
    runtime = build_carry_basket_runtime(rc.ROOT, rc.MANDATE, rc.RELEASE, state_dir=rc.STATE)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    startup, cycle = runtime.startup, runtime.cycle

    def sell_all_startup():
        startup()
        runtime.halt(REASON, flatten=True)

    def cycle_until_flat():
        cycle()
        legs = runtime.state['legs']
        if all(l['mode'] == 'CLOSED' for l in legs.values()) and not runtime.positions():
            log.info('SELL_ALL_COMPLETE every leg is flat: %s', {s: l['closed_reason'] for s, l in legs.items()})
            stop.set()

    runtime.startup, runtime.cycle = sell_all_startup, cycle_until_flat
    sys.exit(0 if runtime.run(stop) is not False else 4)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
    main()
