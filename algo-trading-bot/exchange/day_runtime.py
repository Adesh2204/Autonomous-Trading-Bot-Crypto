"""Day session: the overnight scalper, both directions, with rank protection.

Same committed limits as the overnight run (2 markets, 1 position, <= $1,000
per entry, <= 2 entries per hour, 1x, 10% top-of-book) except that SHORT is
permitted. Adds: a LOCK on the competition return, a -0.30% loss halt, a
leaderboard-based resume rule, and a per-entry exchange verification that
halts (after flattening) if the position, the stop or the take-profit is wrong.
"""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import json
import urllib.request

from .base_exchange import decimal
from .overnight_runtime import OvernightRuntime, MIN_MS

LEADERBOARD = 'https://d23m2l9bjnbgul.cloudfront.net/public/leaderboard.json'
TEAM_NAME = 'Team Anchorium'


def fetch_leaderboard():
    with urllib.request.urlopen(LEADERBOARD, timeout=15) as r:
        return json.load(r)


def live_q(return_pct, days):
    """Official Q if today's return were the only non-zero daily return of `days`."""
    import statistics
    from strategies.momentum_scalper import official_q
    r = float(return_pct) / 100
    returns = [0.0] * (days - 1) + [r]
    sigma = statistics.stdev(returns) * days ** 0.5 if days > 1 else 0.0
    return official_q(D(str(r)), D(str(sigma)))


class DayRuntime(OvernightRuntime):
    def __init__(self, *, targets, report_path, **kwargs):
        super().__init__(**kwargs)
        from strategies.momentum_scalper import DayGuard
        self.targets = targets
        self.report_path = Path(report_path)
        g = self.state.get('day_guard', {})
        self.guard = DayGuard(lock=decimal(targets['lock_pct']), loss_cap=decimal(self.m.loss_cap_pct),
                              locked=g.get('locked', False), resumed_half=g.get('resumed_half', False),
                              losing_streak=g.get('losing_streak', 0), paused_until_ms=g.get('paused_until_ms', 0),
                              half_size=g.get('half_size', False))
        self.prior_return_pct = decimal(targets['prior_return_pct'])
        self.board = None
        self.board_ms = None

    # ---------- state ----------
    def _save(self):
        from .paper_operations import atomic_json
        g = self.guard
        self.state['day_guard'] = dict(locked=g.locked, resumed_half=g.resumed_half, losing_streak=g.losing_streak,
                                       paused_until_ms=g.paused_until_ms, half_size=g.half_size)
        atomic_json(self.state_dir / 'overnight_state.json', self.state)

    # ---------- competition return and rank ----------
    def pnl_pct(self, equity):
        """Competition return: published prior R plus today's equity change (both in %)."""
        return self.prior_return_pct + (equity / self.start_equity - 1) * 100

    def leaderboard(self, force=False):
        now = self.clock_ms()
        if force or self.board is None or now - self.board_ms >= 30 * MIN_MS:
            try:
                self.board = fetch_leaderboard()
                self.board_ms = now
            except Exception as exc:
                self._event('LEADERBOARD_UNAVAILABLE', error=type(exc).__name__)
        return self.board

    def estimate(self, return_pct):
        from strategies.momentum_scalper import estimated_rank
        board = self.leaderboard()
        q = live_q(return_pct, self.targets['days'])
        if not board:
            return q, None, None
        others = [D(str(t['q'])) for t in board['teams'] if t.get('rank') and t['name'] != TEAM_NAME]
        me = next((t for t in board['teams'] if t['name'] == TEAM_NAME), {})
        return q, estimated_rank(q, others), me.get('rank')

    def _apply_verdict(self, verdict):
        if not verdict or self.state['halted']:
            return
        kind, reason = verdict
        if kind == 'HALT':
            self.halt(reason)
        elif kind == 'LOCK':
            self._event('LOCK_REACHED_FLATTEN_AND_PAUSE', lock_pct=self.targets['lock_pct'])
            self.flatten_all('LOCK_REACHED')
            self._save()

    def decide(self):
        now = self.clock_ms()
        if self.guard.locked and (self.state.get('lock_checked_ms') is None or
                                  now - self.state['lock_checked_ms'] >= 30 * MIN_MS):
            self.state['lock_checked_ms'] = now
            q, est, published = self.estimate(self.pnl_pct(self.equity()))
            self.leaderboard(force=True)
            resumed = self.guard.resume_if_below(est)
            self._event('LOCK_RECHECK', estimated_q=q, estimated_rank=est, published_rank=published, resumed=resumed)
            self._save()
        return super().decide()

    # ---------- per-entry exchange verification ----------
    def enter(self, symbol, decision, *, half):
        error = None
        try:
            result = super().enter(symbol, decision, half=half)
        except Exception as exc:
            error, result = exc, None
        if self.positions().get(symbol) is not None:
            self.verify_entry(symbol, first=not self.state.get('first_trade_verified'), error=error)
        if error is not None:
            raise error
        return result

    def verify_entry(self, symbol, *, first, error=None):
        trade = self.state.get('trade') or {}
        started = trade.get('entry_ms') or self.clock_ms()
        position = self.positions().get(symbol)
        orders = [o for o in self.account.get_frontend_open_orders() if o['coin'] == symbol]
        problems = []
        if position is None:
            problems.append('POSITION_MISSING')
        else:
            side = 'LONG' if position.quantity > 0 else 'SHORT'
            close_side = 'A' if position.quantity > 0 else 'B'
            size = abs(position.quantity)
            if side != trade.get('side'):
                problems.append(f'POSITION_SIDE {side} != planned {trade.get("side")}')
            if size != abs(decimal(trade.get('quantity', '0'))):
                problems.append(f'POSITION_SIZE {size} != recorded {trade.get("quantity")}')
            stops = [o for o in orders if o.get('isTrigger') is True and o.get('reduceOnly') is True
                     and o.get('side') == close_side and decimal(o['sz']) == size]
            tps = [o for o in orders if not o.get('isTrigger') and o.get('reduceOnly') is True
                   and o.get('side') == close_side and decimal(o['sz']) == size]
            if len(stops) != 1:
                problems.append(f'EXCHANGE_STOP_COUNT {len(stops)} (expected 1)')
            if len(tps) != 1:
                problems.append(f'EXCHANGE_TAKE_PROFIT_COUNT {len(tps)} (expected 1)')
        elapsed_s = (self.clock_ms() - started) / 1000
        record = dict(symbol=symbol, first=first, elapsed_s=elapsed_s, problems=problems,
                      entry_error=f'{type(error).__name__}:{error}' if error else None,
                      position=dict(size=str(position.quantity), entry=str(position.entry_price)) if position else None,
                      orders=[dict(oid=o.get('oid'), trigger=o.get('isTrigger'), side=o.get('side'), sz=o.get('sz'),
                                   trigger_px=o.get('triggerPx'), limit_px=o.get('limitPx')) for o in orders])
        if problems:
            self._event('ENTRY_VERIFICATION_FAILED', **record)
            self.halt('ENTRY_VERIFICATION_FAILED:' + ';'.join(problems))
            return False
        self._event('ENTRY_VERIFIED', **record)
        if first:
            self.state['first_trade_verified'] = dict(ms=self.clock_ms(), symbol=symbol, elapsed_s=elapsed_s)
            self._save()
        return True

    # ---------- reporting ----------
    def heartbeat(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_heartbeat < 15 * MIN_MS:
            return
        super().heartbeat(force=True)
        positions = self.positions()
        ret = self.pnl_pct(self.equity(positions))
        q, est, published = self.estimate(ret)
        record = dict(utc=datetime.now(timezone.utc).isoformat(), return_pct=f'{ret:.5f}',
                      today_pct=f'{ret - self.prior_return_pct:.5f}', live_q=f'{q:.5f}', estimated_rank=est,
                      published_rank=published, trades=len(self.state['trades']),
                      position=[dict(symbol=s, side='LONG' if p.quantity > 0 else 'SHORT', size=str(abs(p.quantity)),
                                     entry=str(p.entry_price), upnl=str(p.unrealized_pnl)) for s, p in positions.items()],
                      lock=dict(target_pct=self.targets['lock_pct'], locked=self.guard.locked,
                                resumed_half=self.guard.resumed_half),
                      halted=self.state['halted'], stream_healthy=self.stream.healthy)
        with (self.state_dir / 'day_heartbeat.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        self._event('DAY_HEARTBEAT', **record)

    def _write_report(self):
        from .day_report import write_day_report
        return write_day_report(self, self.report_path)
