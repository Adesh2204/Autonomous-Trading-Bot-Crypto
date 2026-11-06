"""Continuous scalper: official-score targets, LOCK / loss-cap pauses to the next sample, period roll, report."""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

import exchange.day_runtime as dr
from exchange.continuous_runtime import (DAY_MS, ROLL_DELAY_MS, ContinuousRuntime, compute_targets, last_sample_ms,
                                         needed_today_pct, seed_history, series_q, up)
from strategies.momentum_scalper import DayGuard
from test_day_session import Exchange, short_decision

SAMPLE = int(datetime(2026, 10, 25, 12, tzinfo=timezone.utc).timestamp() * 1000)


def board(q5=0.10945, q6=0.10607, generated='2026-10-25T12:09:00.000Z', me_return=-4.9e-07):
    teams = [dict(name='A', rank=4, q=0.11472, score=0.09), dict(name='Algo Hedge', rank=5, q=q5, score=0.087),
             dict(name='Blackswans', rank=6, q=q6, score=0.085), dict(name='B', rank=7, q=0.1059, score=0.084),
             dict(name='Team Anchorium', rank=10, q=0.09999, score=0.08, **{'return': me_return})]
    return {'from': '2026-10-19T12:00:00Z', 'generated_at': generated, 'teams': teams}


def test_last_sample_is_the_latest_12_utc():
    assert last_sample_ms(SAMPLE) == SAMPLE
    assert last_sample_ms(SAMPLE - 1) == SAMPLE - DAY_MS
    assert last_sample_ms(SAMPLE + DAY_MS - 1) == SAMPLE


def test_a_one_day_gain_counts_fully_in_sigma_and_reproduces_the_published_targets():
    from strategies.momentum_scalper import official_q
    assert abs(float(series_q([0.0] * 4 + [0.001])) - float(official_q(D('0.001'), D('0.001')))) < 1e-12
    history = [0.0] * 4                                   # five daily returns after the next sample
    assert up(needed_today_pct(history, D('0.10945265106317394'))) == D('0.0651')       # thresholds round up
    assert up(needed_today_pct(history, D('0.1060696038256501'))) == D('0.0413')


def test_targets_lock_above_rank_five_and_never_below_one_round_trip():
    t = compute_targets(board(), [0.0] * 4)
    assert D(t['r6_pct']) < D(t['r5_pct']) < D(t['lock_pct']) and D(t['lock_pct']) >= D(t['r5_pct']) + D('0.0028')
    ahead = compute_targets(board(q5=0.05, q6=0.04), [0.0] * 4)        # already above #5 at zero return
    assert D(ahead['r5_pct']) == 0 and D(ahead['lock_pct']) == D('0.0028')


def test_history_is_seeded_from_the_published_return():
    assert seed_history(board(generated='2026-10-24T13:00:00.000Z')) == [-4.9e-07, 0.0, 0.0, 0.0, 0.0]


class Cont(Exchange, ContinuousRuntime):
    def equity(self, positions=None):
        return self._equity


def runtime(tmp_path, monkeypatch, *, now=SAMPLE + 2 * 3600000, b=None):
    monkeypatch.setattr(dr, 'fetch_leaderboard', lambda: b or board())
    r = Cont(tmp_path)
    r.now = now
    r._equity = D(100000)
    r.targets = dict(r6_pct='0.0413', r5_pct='0.0651', lock_pct='0.0808', prior_return_pct='0', days=6)
    r.report_path = tmp_path
    r.board = r.board_ms = None
    r.guard = DayGuard(lock=D('0.0808'), loss_cap=D('-0.30'))
    r.state['period'] = r.period = dict(sample_ms=SAMPLE, start_ms=SAMPLE + 300000, start_equity='100000',
                                        history=[0.0] * 5, next_roll_ms=SAMPLE + DAY_MS + ROLL_DELAY_MS,
                                        retarget_after_ms=None, reported_sample_ms=SAMPLE, loss_paused=False, closed=[])
    r.flattened = []
    r.flatten_all = lambda reason: r.flattened.append(reason)
    return r


def test_lock_flattens_and_pauses_until_after_the_next_sample_then_resumes(tmp_path, monkeypatch):
    r = runtime(tmp_path, monkeypatch)
    r._equity = D('100081')                                             # +0.081% this period >= LOCK 0.0808%
    r._apply_verdict(r.guard.check(r.guard_return(r.equity())))
    assert r.flattened == ['LOCK_REACHED'] and r.guard.paused(r.now)
    assert r.guard.paused(SAMPLE + DAY_MS + ROLL_DELAY_MS - 1)
    r.decide()
    assert r.requests == []                                             # no entry while locked
    r.now = SAMPLE + DAY_MS + ROLL_DELAY_MS
    assert r.roll_if_due() and not r.guard.paused(r.now) and not r.guard.locked
    assert r.period['history'][-1] == pytest.approx(0.00081) and r.period['start_equity'] == '100081'
    assert r.guard_return(r.equity()) == 0


def test_period_loss_cap_flattens_once_and_pauses_to_the_next_sample(tmp_path, monkeypatch):
    r = runtime(tmp_path, monkeypatch)
    r._equity = D('99700')                                              # -0.30% this period
    for _ in range(3):
        r._apply_verdict(r.guard.check(r.guard_return(r.equity())))
    assert r.flattened == ['LOSS_CAP_0_30_PCT_PERIOD'] and r.state['halted'] is None
    assert r.guard.paused(r.now) and r.period['loss_paused']
    r.now = SAMPLE + DAY_MS + ROLL_DELAY_MS
    r.roll_if_due()
    assert not r.guard.paused(r.now) and not r.period['loss_paused']


def test_competition_return_compounds_completed_days_with_this_period(tmp_path, monkeypatch):
    r = runtime(tmp_path, monkeypatch)
    r.period['history'] = [0.001, 0.0]
    r._equity = D('100100')
    assert r.pnl_pct(r.equity()).quantize(D('0.000001')) == D('0.200100')
    assert r.prior_return_pct.quantize(D('0.0001')) == D('0.1000')


def test_retarget_waits_for_the_board_to_publish_the_new_sample(tmp_path, monkeypatch):
    stale = board(generated='2026-10-26T11:59:00.000Z')
    r = runtime(tmp_path, monkeypatch, b=stale)
    r.now = SAMPLE + DAY_MS + ROLL_DELAY_MS
    r.roll_if_due()
    assert not r.retarget_if_due() and r.period['retarget_after_ms'] is not None
    monkeypatch.setattr(dr, 'fetch_leaderboard', lambda: board(q5=0.11, generated='2026-10-26T12:09:00.000Z'))
    assert r.retarget_if_due() and r.period['retarget_after_ms'] is None
    assert r.guard.lock == D(r.targets['lock_pct']) and r.state['targets']['generated_at'].startswith('2026-10-26T12:09')


def test_daily_report_at_1745_ist_has_return_rank_trades_and_issues(tmp_path, monkeypatch):
    r = runtime(tmp_path, monkeypatch)
    r.state['trades'] = [dict(symbol='pas:BTC', side='SHORT', net='0.05', exit_ms=SAMPLE + 7200000)]
    r._event('ORDER_ERROR', where='entry:pas:BTC', error='ExchangeError:X', consecutive=1)
    r.now = SAMPLE + DAY_MS + ROLL_DELAY_MS
    r._equity = D('100010')
    r.roll_if_due()
    assert r.report_if_due() is None                                   # 12:05 UTC: too early
    r.now = SAMPLE + DAY_MS + 15 * 60000
    path = r.report_if_due()
    text = path.read_text()
    assert path.name == 'report_2026-10-26.md' and r.report_if_due() is None
    assert 'Return: published R' in text and 'Rank: published #10' in text
    assert 'Trades last period: 1 (long 0 / short 1) | wins/losses 1/0' in text and 'ORDER_ERROR' in text


def test_three_consecutive_order_errors_still_halt_permanently(tmp_path, monkeypatch):
    from exchange.base_exchange import ExchangeError
    r = runtime(tmp_path, monkeypatch)
    r.halt = lambda reason: r.state.__setitem__('halted', dict(reason=reason))
    for _ in range(3):
        r._note_order_error(ExchangeError('STALE_PRICE_CONTEXT'), 'entry:pas:BTC')
    assert r.state['halted']['reason'] == 'CONSECUTIVE_ORDER_ERRORS'


def test_entries_resume_after_the_roll(tmp_path, monkeypatch):
    from exchange.overnight_runtime import OvernightRuntime
    r = runtime(tmp_path, monkeypatch)
    r.guard.locked = True
    r.now = SAMPLE + DAY_MS + ROLL_DELAY_MS
    r.roll_if_due()
    OvernightRuntime.enter(r, 'pas:EWY', short_decision(), half=False)
    assert len(r.requests) == 2                                         # entry + take-profit


def test_real_constructor_persists_the_period_and_new_targets_across_a_restart(tmp_path):
    from types import SimpleNamespace
    from test_momentum_scalper import mandate
    m = mandate(directions=('LONG', 'SHORT'), loss_cap_pct='-0.30').require()
    now = [SAMPLE + 3600000]

    def make():
        return ContinuousRuntime(mandate=m, executor=SimpleNamespace(journal=SimpleNamespace(event=lambda *a, **k: None)),
                                 protection=None, recovery=None, account=None, client=SimpleNamespace(clock_ms=lambda: now[0]),
                                 market=None, stream=None, auth=None, legs={}, state_dir=tmp_path,
                                 clock_ms=lambda: now[0], history=[0.0] * 5, report_path=tmp_path,
                                 targets=dict(r6_pct='0.0413', r5_pct='0.0651', lock_pct='0.0808',
                                              prior_return_pct='0', days=6))
    r = make()
    assert r.period['sample_ms'] == SAMPLE and r.period['next_roll_ms'] == SAMPLE + DAY_MS + ROLL_DELAY_MS
    assert r.prior_return_pct == 0 and r.guard.lock == D('0.0808')
    r.state['targets'] = dict(r.targets, lock_pct='0.0500')
    r.period['history'].append(0.0002)
    r._save()
    now[0] += 60000
    again = make()                                                      # supervisor restart
    assert again.period['history'][-1] == 0.0002 and again.guard.lock == D('0.0500')
