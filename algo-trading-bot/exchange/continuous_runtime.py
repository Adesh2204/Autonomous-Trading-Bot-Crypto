"""Continuous scalper to the end of the scored window, one scoring period at a time.

Same committed limits as the day session (BTC/EWY, LONG and SHORT, one position,
<= $1,000 per entry, <= 2 entries per hour, 1x, 10% top-of-book, 0.4% risk).
The competition samples equity daily at 12:00 UTC (+240 s), so each period runs
from one sample to the next:

  * LOCK: when this period's return reaches the return that would rank us #5 on
    the official score (with a buffer), flatten and pause until after the next sample.
  * Loss cap: this period's return <= -0.30% flattens and pauses until after the
    next sample.
  * After each sample the period rolls: its return joins our daily-return history,
    the pause and half-size clear, and targets are recomputed from the new board.
  * A one-screen report is written at 12:15 UTC (17:45 IST).

Permanent halts (three consecutive order errors, a failed entry verification, a
long stream disconnect) stay permanent: they flatten and need a human.
"""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import json
import statistics

from .day_runtime import DayRuntime, TEAM_NAME, fetch_leaderboard
from .overnight_runtime import MIN_MS

DAY_MS = 24 * 60 * MIN_MS
SAMPLE_OFFSET_MS = 12 * 60 * MIN_MS          # 12:00 UTC
ROLL_DELAY_MS = 5 * MIN_MS                   # the sample is taken up to 240 s after 12:00
REPORT_DELAY_MS = 15 * MIN_MS                # 12:15 UTC = 17:45 IST
ROUND_TRIP_PCT = D('0.0028')                 # one round trip at the $1,000 cap, in % of equity
WATCHED_ISSUES = ('HALT', 'ORDER_ERROR', 'CYCLE_ERROR', 'CYCLE_EXCEPTION', 'FLATTEN_ERROR', 'STREAM_ERROR',
                  'ENTRY_VERIFICATION_FAILED', 'EXIT_RETRY_AFTER_STALE_SNAPSHOT', 'FRESH_READ_BUDGET_SHORT',
                  'LOCK_REACHED_FLATTEN_AND_PAUSE', 'LOSS_CAP_FLATTEN_AND_PAUSE', 'LEADERBOARD_UNAVAILABLE')


def last_sample_ms(now_ms):
    """The most recent 12:00 UTC at or before now."""
    sample = now_ms // DAY_MS * DAY_MS + SAMPLE_OFFSET_MS
    return sample if sample <= now_ms else sample - DAY_MS


def series_q(returns):
    """Official Q from daily returns (fractions): R compounded, sigma = sample stdev * sqrt(n)."""
    from strategies.momentum_scalper import official_q
    total = 1.0
    for r in returns:
        total *= 1 + r
    sigma = statistics.stdev(returns) * len(returns) ** 0.5 if len(returns) > 1 else 0.0
    return official_q(D(str(total - 1)), D(str(sigma)))


def needed_today_pct(history, q_target):
    """Smallest return today (%) whose resulting Q beats q_target; 0 if Q already beats it at 0."""
    if series_q(history + [0.0]) > q_target:
        return D(0)
    lo, hi = 0.0, 0.05
    if series_q(history + [hi]) <= q_target:
        return D('5')
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if series_q(history + [mid]) > q_target else (mid, hi)
    return D(str(hi * 100))


def up(value):
    from decimal import ROUND_UP
    return value.quantize(D('0.0001'), rounding=ROUND_UP)


def compute_targets(board, history):
    """Today's-return thresholds for #6, #5 and the LOCK on the official score."""
    ranked = {t['rank']: t for t in board['teams'] if t.get('rank')}
    q5, q6 = D(str(ranked[5]['q'])), D(str(ranked[6]['q']))
    r6, r5 = needed_today_pct(history, q6), needed_today_pct(history, q5)
    r5_up = needed_today_pct(history, q5 * D('1.02'))
    # LOCK: beat #5 after one more round trip of costs, and beat a #5 whose Q improves
    # by 2% at the same sample; never below one round trip.
    lock = max(r5 + ROUND_TRIP_PCT, r5_up, ROUND_TRIP_PCT)
    me = next((t for t in board['teams'] if t['name'] == TEAM_NAME), {})
    return dict(generated_at=board['generated_at'], r6_pct=str(up(r6)), r5_pct=str(up(r5)), lock_pct=str(up(lock)),
                published_rank=me.get('rank'), published_return_pct=str(D(str(me.get('return', 0))) * 100),
                ranks={str(k): dict(name=ranked[k]['name'], q=f"{ranked[k]['q']:.5f}") for k in (4, 5, 6, 7) if k in ranked})


def seed_history(board):
    """Our completed daily returns so far: the published R on the first day, zeros after it."""
    start = int(datetime.fromisoformat(board['from'].replace('Z', '+00:00')).timestamp() * 1000)
    generated = int(datetime.fromisoformat(board['generated_at'][:19] + '+00:00').timestamp() * 1000)
    days = max(1, (last_sample_ms(generated) - start) // DAY_MS)
    me = next(t for t in board['teams'] if t['name'] == TEAM_NAME)
    return [float(me['return'])] + [0.0] * (days - 1)


class ContinuousRuntime(DayRuntime):
    def __init__(self, *, history, **kwargs):
        super().__init__(**kwargs)
        now = self.clock_ms()
        period = self.state.get('period')
        if period is None:
            sample = last_sample_ms(now)
            period = dict(sample_ms=sample, start_ms=now, start_equity=str(self.start_equity),
                          history=list(history), next_roll_ms=sample + DAY_MS + ROLL_DELAY_MS,
                          retarget_after_ms=None, reported_sample_ms=sample if now >= sample + REPORT_DELAY_MS else None,
                          loss_paused=False, closed=[])
            self.state['period'] = period
            self._save()
        self.period = period
        self.targets.update(self.state.get('targets') or {})     # targets recomputed before a restart
        self.guard.lock = D(self.targets['lock_pct'])

    # ---------- returns ----------
    def today_pct(self, equity):
        return (equity / D(self.period['start_equity']) - 1) * 100

    def pnl_pct(self, equity):
        """Competition return estimate: completed daily returns compounded with this period's."""
        total = D(1)
        for r in self.period['history']:
            total *= 1 + D(str(r))
        return (total * equity / D(self.period['start_equity']) - 1) * 100

    def guard_return(self, equity):
        return self.today_pct(equity)

    @property
    def prior_return_pct(self):
        return self.pnl_pct(D(self.period['start_equity']))

    @prior_return_pct.setter
    def prior_return_pct(self, value):
        pass                                          # derived from the period history

    def estimate(self, return_pct):
        """Live Q and rank if the sample were now; `return_pct` is the competition return estimate."""
        from strategies.momentum_scalper import estimated_rank
        q = series_q(self.period['history'] + [self._today_from_total(return_pct)])
        board = self.leaderboard()
        if not board:
            return q, None, None
        others = [D(str(t['q'])) for t in board['teams'] if t.get('rank') and t['name'] != TEAM_NAME]
        me = next((t for t in board['teams'] if t['name'] == TEAM_NAME), {})
        return q, estimated_rank(q, others), me.get('rank')

    def _today_from_total(self, total_pct):
        prior = D(1)
        for r in self.period['history']:
            prior *= 1 + D(str(r))
        return float((1 + D(total_pct) / 100) / prior - 1)

    # ---------- LOCK and loss cap: pause until after the next sample ----------
    def _apply_verdict(self, verdict):
        if not verdict or self.state['halted']:
            return
        kind, reason = verdict
        if kind == 'LOCK':
            self.guard.paused_until_ms = max(self.guard.paused_until_ms, self.period['next_roll_ms'])
            self._event('LOCK_REACHED_FLATTEN_AND_PAUSE', lock_pct=self.targets['lock_pct'],
                        until_ms=self.period['next_roll_ms'])
            self.flatten_all('LOCK_REACHED')
        elif kind == 'HALT' and not self.period['loss_paused']:
            self.period['loss_paused'] = True
            self.guard.paused_until_ms = max(self.guard.paused_until_ms, self.period['next_roll_ms'])
            self._event('LOSS_CAP_FLATTEN_AND_PAUSE', loss_cap_pct=str(self.guard.loss_cap),
                        until_ms=self.period['next_roll_ms'])
            self.flatten_all('LOSS_CAP_0_30_PCT_PERIOD')
        self._save()

    def decide(self):
        if self.guard.paused(self.clock_ms()):
            return                                     # LOCK / loss cap / loss streak: logged when it began
        from .overnight_runtime import OvernightRuntime
        return OvernightRuntime.decide(self)

    # ---------- period roll, retarget and the 17:45 IST report ----------
    def roll_if_due(self):
        now = self.clock_ms()
        p = self.period
        if now < p['next_roll_ms']:
            return False
        equity = self.equity()
        closed = float(equity / D(p['start_equity']) - 1)
        sample = last_sample_ms(now)
        record = dict(sample_ms=p['sample_ms'], start_ms=p['start_ms'], end_ms=now, start_equity=p['start_equity'],
                      end_equity=str(equity), return_pct=f'{closed * 100:.6f}',
                      trades=[t for t in self.state['trades'] if p['start_ms'] <= t.get('exit_ms', 0) < now],
                      locked=self.guard.locked, loss_paused=p['loss_paused'])
        p['closed'] = (p['closed'] + [record])[-30:]
        p['history'].append(closed)
        p.update(sample_ms=sample, start_ms=now, start_equity=str(equity), next_roll_ms=sample + DAY_MS + ROLL_DELAY_MS,
                 retarget_after_ms=sample + 240000, loss_paused=False)
        g = self.guard
        g.locked, g.resumed_half, g.half_size, g.losing_streak = False, False, False, 0
        g.paused_until_ms = 0
        self._save()
        self._event('PERIOD_ROLLED', closed_return_pct=record['return_pct'], equity=equity,
                    days=len(p['history']), trades=len(record['trades']))
        return True

    def retarget_if_due(self, force=False):
        p = self.period
        if p['retarget_after_ms'] is None and not force:
            return False
        board = self.leaderboard(force=True)
        if not board:
            return False
        generated = int(datetime.fromisoformat(board['generated_at'][:19] + '+00:00').timestamp() * 1000)
        if not force and generated < p['retarget_after_ms']:
            return False                               # the board has not published the new sample yet
        t = compute_targets(board, p['history'])
        self.targets.update(t)
        self.guard.lock = D(t['lock_pct'])
        p['retarget_after_ms'] = None
        self.state['targets'] = self.targets
        self._save()
        self._event('TARGETS_UPDATED', **{k: t[k] for k in ('generated_at', 'r6_pct', 'r5_pct', 'lock_pct',
                                                             'published_rank', 'published_return_pct')})
        return True

    def report_if_due(self):
        now = self.clock_ms()
        sample = last_sample_ms(now)
        if now < sample + REPORT_DELAY_MS or self.period['reported_sample_ms'] == sample:
            return None
        self.period['reported_sample_ms'] = sample
        self._save()
        return self._write_report()

    def heartbeat(self, force=False):
        try:
            self.roll_if_due()
            if self.period['retarget_after_ms'] is not None:
                if self.clock_ms() - (self.board_ms or 0) >= 5 * MIN_MS:
                    self.retarget_if_due()
            self.report_if_due()
        except Exception as exc:
            self._event('PERIOD_MAINTENANCE_ERROR', error=f'{type(exc).__name__}:{exc}')
        return super().heartbeat(force)

    def _write_report(self):
        from .continuous_report import write_period_report
        sample = last_sample_ms(self.clock_ms())
        day = datetime.fromtimestamp(sample / 1000, timezone.utc).strftime('%Y-%m-%d')
        return write_period_report(self, Path(self.report_path) / f'report_{day}.md')
