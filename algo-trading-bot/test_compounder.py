"""Compounder tests: indicators, Indian tax engine, sizing, backtest accounting, paper runner.

No network: market data is a fake object; nothing is signed or sent anywhere."""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from compounder.backtest import Bars, metrics, run
from compounder.brokers import OrderRefused, PaperBroker
from compounder.costs import HYPERLIQUID, TaxLedger, TaxPolicy, VenueCosts, indian_fy
from compounder.indicators import prior_max, prior_min, wilder_atr
from compounder.market_data import AssetContext, AssetSpec, decimal_px, walk_book
from compounder.runner import DAY_MS, Runner, RunnerConfig
from compounder.sizing import RiskParams, round_down, size_order
from compounder.strategy import CANDIDATES, TrendParams, channel_exit, compute_signals, entry_side

FREE = VenueCosts("free", 0.0, 0.0, slip_bps_liquid=0, slip_bps_major=0, slip_bps_other=0, stop_extra_bps=0,
                  min_notional=0.0)


# ---------------------------------------------------------------- indicators
def test_prior_channels_exclude_current_bar():
    x = np.array([1, 5, 2, 3, 9, 4], dtype=float)
    assert np.isnan(prior_max(x, 3)[2])
    assert prior_max(x, 3)[3] == 5           # max of bars 0..2
    assert prior_max(x, 3)[5] == 9           # max of bars 2..4
    assert prior_min(x, 3)[4] == 2           # min of bars 1..3


def test_wilder_atr_constant_range():
    h = np.full(40, 11.0)
    lo = np.full(40, 9.0)
    c = np.full(40, 10.0)
    atr = wilder_atr(h, lo, c, 20)
    assert np.isnan(atr[18]) and atr[19] == pytest.approx(2.0) and atr[-1] == pytest.approx(2.0)


def test_incremental_window_matches_full_history():
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 900)))
    h, lo = c * 1.02, c * 0.98
    p = TrendParams("t", "1d", 55, 20, 20, 2.0, False)
    full = compute_signals(h, lo, c, p)
    tail = compute_signals(h[-300:], lo[-300:], c[-300:], p)  # what the live runner sees
    assert tail.upper[-1] == full.upper[-1] and tail.exit_lo[-1] == full.exit_lo[-1]
    assert tail.atr[-1] == pytest.approx(full.atr[-1], rel=1e-6)


def test_entry_and_exit_rules():
    p = TrendParams("t", "1d", 3, 2, 3, 2.0, True)
    h = np.array([10, 10, 10, 10, 10.0])
    lo = np.array([9, 9, 9, 9, 9.0])
    c = np.array([9.5, 9.5, 9.5, 9.5, 9.5])
    sig = compute_signals(h, lo, c, p)
    assert entry_side(sig, 4, 10.5, p) == 1
    assert entry_side(sig, 4, 8.5, p) == -1
    assert entry_side(sig, 4, 9.5, p) == 0
    assert entry_side(sig, 4, 8.5, replace(p, allow_short=False)) == 0
    assert channel_exit(1, sig, 4, 8.9) and not channel_exit(1, sig, 4, 9.1)
    assert channel_exit(-1, sig, 4, 10.1)


# ---------------------------------------------------------------- tax
def test_indian_financial_year():
    assert indian_fy(1774915200000) == 2025   # 2026-03-31
    assert indian_fy(1775001600000) == 2026   # 2026-04-01


def test_vda_tax_is_per_trade_and_losses_do_not_offset():
    t = TaxLedger(TaxPolicy("VDA_PER_TRADE"))
    assert t.on_trade_closed(1775001600000, 100.0) == pytest.approx(31.2)
    assert t.on_trade_closed(1775001600000, -100.0) == 0.0
    assert t.reserve == pytest.approx(31.2)   # net zero P&L still owes 31.2


def test_business_mode_nets_within_year_and_carries_losses():
    t = TaxLedger(TaxPolicy("BUSINESS_NET_ANNUAL"))
    fy25 = 1767225600000  # 2026-01-01 (FY 2025)
    fy26 = 1775001600000  # 2026-04-01 (FY 2026)
    t.on_trade_closed(fy25, 100.0)
    assert t.reserve == pytest.approx(31.2)
    t.on_trade_closed(fy25, -150.0)           # same year: loss nets the gain, reserve released
    assert t.reserve == pytest.approx(0.0)
    t.on_trade_closed(fy26, 80.0)              # 50 carried loss offsets next year's gain
    assert t.reserve == pytest.approx(0.312 * 30.0)


def test_pending_tax_on_open_winners():
    t = TaxLedger(TaxPolicy("VDA_PER_TRADE"))
    assert t.pending_on(0, [50.0, -20.0]) == pytest.approx(15.6)
    assert TaxLedger(TaxPolicy("NONE")).pending_on(0, [50.0]) == 0.0


# ---------------------------------------------------------------- sizing
def test_risk_sizing_and_caps():
    risk = RiskParams(0.01, 1.0, 3.0, 5.0)
    q = size_order(1000.0, 100.0, 90.0, 0.0, risk, 10.0)
    assert q == pytest.approx(1.0)                         # $10 risk / $10 per unit
    q = size_order(1000.0, 100.0, 99.5, 0.0, risk, 10.0)    # tight stop -> capped at 1x equity
    assert q == pytest.approx(10.0)
    q = size_order(1000.0, 100.0, 99.5, 2950.0, risk, 10.0)  # gross room only $50
    assert q == pytest.approx(0.5)
    assert size_order(1000.0, 100.0, 90.0, 0.0, risk, 200.0) == 0.0   # below venue minimum
    assert size_order(-5.0, 100.0, 90.0, 0.0, risk, 10.0) == 0.0


def test_round_down_never_rounds_up():
    assert str(round_down(0.123456789, 5)) == "0.12345"
    assert str(round_down(0.99999, 0)) == "0"


def test_price_rule_and_book_walk():
    assert str(decimal_px(58912.345, 5)) == "58912.0"
    assert str(decimal_px(0.0543219, 0)) == "0.054322"
    assert walk_book([(10.0, 1.0), (11.0, 1.0)], 1.5) == pytest.approx(31 / 3)
    assert walk_book([(10.0, 1.0)], 2.0) is None


# ---------------------------------------------------------------- backtest accounting
def _trend_bars(symbol="BTC", n=400, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * 1.01
    lo = np.minimum(o, c) * 0.99
    t = np.arange(n, dtype=np.int64) * DAY_MS + 1_700_000_000_000 // DAY_MS * DAY_MS
    ft = t + 8 * 3_600_000
    fr = np.full(n, 0.0001)
    return Bars(symbol, t, o, h, lo, c, ft, fr)


def test_backtest_money_identity():
    bars = [_trend_bars("BTC", seed=3), _trend_bars("ETH", seed=4)]
    p = TrendParams("t", "1d", 20, 10, 20, 2.0, True)
    res = run(bars, p, HYPERLIQUID, RiskParams(0.01, 1.0, 3.0, 5.0), tax_policy=TaxPolicy("VDA_PER_TRADE"))
    m = metrics(res)
    assert m["trades"] > 10
    # final cash = start + sum of trade nets (fees, slippage-in-price and funding all inside net)
    assert res.equity[-1] == pytest.approx(res.start_equity + sum(t.net for t in res.trades), rel=1e-9)
    assert res.after_tax[-1] == pytest.approx(res.equity[-1] - res.tax.reserve, rel=1e-9)
    assert res.tax.reserve == pytest.approx(0.312 * sum(t.net for t in res.trades if t.net > 0), rel=1e-9)


def test_tax_mode_none_beats_vda_and_free_costs_beat_real_costs():
    bars = [_trend_bars("BTC", seed=5)]
    p = TrendParams("t", "1d", 20, 10, 20, 2.0, False)
    risk = RiskParams(0.01, 1.0, 3.0, 5.0)
    none = metrics(run(bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy("NONE")))
    vda = metrics(run(bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy("VDA_PER_TRADE")))
    free = metrics(run(bars, p, FREE, risk, tax_policy=TaxPolicy("NONE")))
    assert none["return_after_tax"] >= vda["return_after_tax"]
    assert free["return_after_tax"] >= none["return_after_tax"] - 1e-12


def test_candidates_are_the_pre_registered_set():
    assert [c.name for c in CANDIDATES] == ["D20_10_LS", "D20_10_L", "D55_20_LS", "D55_20_L",
                                            "H4_20_10_LS", "H4_20_10_L"]


# ---------------------------------------------------------------- paper runner (fake market)
class FakeMarket:
    def __init__(self, closes, start_ms):
        self.closes = list(closes)
        self.start = start_ms
        self.now_ms = start_ms + len(self.closes) * DAY_MS + 60_000
        self.mark = self.closes[-1]
        self.funding_rate = 0.0

    def clock(self):
        return self.now_ms / 1000

    def specs(self):
        return {"BTC": AssetSpec("BTC", 5, 40)}

    def contexts(self):
        return {"BTC": AssetContext("BTC", self.mark, self.mark, self.mark, self.funding_rate, None, None)}

    def book(self, coin):
        return [(self.mark * 0.9999, 100.0)], [(self.mark * 1.0001, 100.0)], self.now_ms

    def candles(self, coin, interval, bars):
        rows = []
        for i, c in enumerate(self.closes):
            t = self.start + i * DAY_MS
            if t + DAY_MS <= self.now_ms:
                rows.append({"t": t, "o": c, "h": c * 1.01, "l": c * 0.99, "c": c})
        return rows[-bars:]

    def funding_history(self, coin, start_ms, end_ms):
        hours = range((start_ms // 3_600_000 + 1) * 3_600_000, end_ms + 1, 3_600_000)
        return [(h, self.funding_rate) for h in hours]


def _runner(tmp_path: Path, market: FakeMarket, **over) -> Runner:
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t", "1d", 5, 3, 5, 2.0, False),
                       risk=RiskParams(0.01, 1.0, 3.0, 5.0), costs=HYPERLIQUID, tax_policy=TaxPolicy("VDA_PER_TRADE"),
                       start_equity=1000.0, mandate_hash="test", bar_settle_ms=0, **over)
    return Runner(cfg, market, PaperBroker(market, HYPERLIQUID, clock=market.clock), clock=market.clock,
                  sleep=lambda s: None)


def test_runner_enters_on_breakout_and_compounds_after_tax(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    r = _runner(tmp_path, m)
    r.step()
    assert not r.state.positions                       # bar already completed at start is not traded
    m.closes.append(110.0)                              # breakout bar completes
    m.now_ms += DAY_MS
    m.mark = 110.0
    r.step()
    pos = r.state.positions["BTC"]
    assert pos["side"] == 1 and pos["stop"] < 110.0
    risk_dollars = pos["qty"] * (pos["entry_price"] - pos["stop"])
    assert risk_dollars == pytest.approx(10.0, rel=0.02)   # 1% of $1000 after-tax equity
    # price runs up, then the channel exit closes the trade at a profit
    for c in (120.0, 130.0, 140.0, 100.0):
        m.closes.append(c)
        m.now_ms += DAY_MS
        m.mark = c if c != 100.0 else 135.0
        r.step()
    assert not r.state.positions
    trades = r.journal.trades()
    assert len(trades) == 1 and trades[0]["net_usd"] > 0
    gross = trades[0]["net_usd"] + trades[0]["fees_usd"] - trades[0]["funding_usd"]
    assert trades[0]["tax_reserved_usd"] == pytest.approx(0.312 * gross)   # fees not deductible
    st = r.status()
    assert st["after_tax_equity_usd"] == pytest.approx(1000 + trades[0]["after_tax_usd"], abs=1e-3)


def test_runner_paper_stop_and_restart_resumes(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    r = _runner(tmp_path, m)
    r.step()
    m.closes.append(110.0)
    m.now_ms += DAY_MS
    m.mark = 110.0
    r.step()
    stop = r.state.positions["BTC"]["stop"]
    r2 = _runner(tmp_path, m)                           # restart: state is reloaded, not re-initialised
    assert "BTC" in r2.state.positions
    m.mark = stop * 0.99                                # mark crosses the stop -> paper stop fills
    m.now_ms += 20_000
    r2.step()
    assert not r2.state.positions
    t = r2.journal.trades()[0]
    assert t["reason"] == "STOP" and t["net_usd"] < 0 and t["tax_reserved_usd"] == 0.0


def test_runner_refuses_state_of_another_mandate(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    _runner(tmp_path, m)
    with pytest.raises(RuntimeError, match="ANOTHER_MANDATE"):
        cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t"), risk=RiskParams(),
                           costs=HYPERLIQUID, tax_policy=TaxPolicy(), start_equity=1.0, mandate_hash="other")
        Runner(cfg, m, PaperBroker(m, HYPERLIQUID), clock=m.clock)


def test_operator_files_block_entries_and_flatten(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    r = _runner(tmp_path, m)
    r.step()
    (tmp_path / "NO_ENTRIES").write_text("x")
    m.closes.append(110.0)
    m.now_ms += DAY_MS
    m.mark = 110.0
    r.step()
    assert not r.state.positions
    (tmp_path / "NO_ENTRIES").unlink()
    m.closes.append(120.0)
    m.now_ms += DAY_MS
    m.mark = 120.0
    r.step()
    assert "BTC" in r.state.positions
    (tmp_path / "FLATTEN").write_text("x")
    r.step()
    assert not r.state.positions and not (tmp_path / "FLATTEN").exists()


def test_paper_broker_refuses_thin_book():
    class Thin(FakeMarket):
        def book(self, coin):
            return [(99.0, 0.01)], [(101.0, 0.01)], 0
    m = Thin([100.0] * 3, 0)
    with pytest.raises(OrderRefused, match="THIN_BOOK"):
        PaperBroker(m, HYPERLIQUID).market("BTC", 1, 5.0, reduce_only=False, reason="t")


# ---------------------------------------------------------------- live broker (offline fakes only)
from compounder.hl_live import HyperliquidLiveBroker, LiveGate, LiveLocked, activation_phrase, cloid_for  # noqa: E402

ADDR = "0x" + "ab" * 20


def _gate(tmp_path, *, mandate=None, typed=None, key_mode=0o600, key_inside=False):
    m = mandate or {"mode": "LIVE", "live_orders_allowed": True, "account_address": ADDR}
    receipt = tmp_path / "receipt.json"
    receipt.write_text(__import__("json").dumps({"mandate_hash": "h", "typed": typed or activation_phrase(ADDR)}))
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    key = (repo if key_inside else tmp_path) / "agent.key"
    key.write_text("0x" + "11" * 32)
    key.chmod(key_mode)
    return LiveGate(m, "h", receipt, key, repo)


def test_live_gate_accepts_only_complete_activation(tmp_path):
    _gate(tmp_path).verify()
    with pytest.raises(LiveLocked, match="MANDATE_NOT_LIVE"):
        _gate(tmp_path, mandate={"mode": "PAPER", "live_orders_allowed": False, "account_address": ADDR}).verify()
    with pytest.raises(LiveLocked, match="ACCOUNT_ADDRESS"):
        _gate(tmp_path, mandate={"mode": "LIVE", "live_orders_allowed": True, "account_address": "0x" + "0" * 40}).verify()
    with pytest.raises(LiveLocked, match="RECEIPT_DOES_NOT_MATCH"):
        _gate(tmp_path, typed="yes").verify()
    with pytest.raises(LiveLocked, match="PERMISSIONS"):
        _gate(tmp_path, key_mode=0o644).verify()
    with pytest.raises(LiveLocked, match="INSIDE_REPOSITORY"):
        _gate(tmp_path, key_inside=True).verify()


def test_cloid_is_deterministic_per_bar_and_action():
    a = cloid_for("h", "BTC", 1, "ENTRY_ENTRY")
    assert a == cloid_for("h", "BTC", 1, "ENTRY_ENTRY") and len(a) == 34
    assert a != cloid_for("h", "BTC", 2, "ENTRY_ENTRY") and a != cloid_for("h", "ETH", 1, "ENTRY_ENTRY")


class FakeExchange:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def order(self, coin, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        self.calls.append(dict(coin=coin, is_buy=is_buy, sz=sz, limit_px=limit_px, order_type=order_type,
                               reduce_only=reduce_only, cloid=cloid))
        return self.reply

    def cancel(self, coin, oid):
        self.calls.append(dict(cancel=coin, oid=oid))
        return {"status": "ok"}


class FakeInfo:
    def __init__(self, positions=None, orders=None, agents=None, value="500"):
        self.pos = positions or {}
        self.orders = orders or []
        self.agents = agents if agents is not None else [{"address": "0xAgent"}]
        self.value = value

    def user_state(self, account):
        return {"marginSummary": {"accountValue": self.value},
                "assetPositions": [{"position": {"coin": c, "szi": str(s)}} for c, s in self.pos.items()]}

    def open_orders(self, account):
        return self.orders

    def extra_agents(self, account):
        return self.agents

    def user_fills_by_time(self, account, start):
        return [{"oid": 77, "fee": "0.05", "coin": "BTC", "side": "B", "sz": "0.002", "px": "60000", "time": start}]


def _live(reply, info=None):
    m = FakeMarket([60000.0] * 3, 0)
    return HyperliquidLiveBroker(exchange=FakeExchange(reply), info=info or FakeInfo(), md=m, costs=HYPERLIQUID,
                                 account=ADDR, mandate_hash="h", size_decimals={"BTC": 5}, clock=lambda: 1.0)


def test_live_entry_is_ioc_inside_band_and_books_actual_fill():
    ok = {"status": "ok", "response": {"data": {"statuses": [{"filled": {"totalSz": "0.002", "avgPx": "60010", "oid": 77}}]}}}
    b = _live(ok)
    b.bar_hint = 123
    f = b.market("BTC", 1, 0.002, reduce_only=False, reason="ENTRY")
    call = b.ex.calls[0]
    assert call["order_type"] == {"limit": {"tif": "Ioc"}} and call["is_buy"] and not call["reduce_only"]
    assert call["limit_px"] <= 60006.0 * 1.005 + 1           # at most 0.5% through the touch
    assert f.qty == 0.002 and f.price == 60010.0 and f.fee == 0.05


def test_live_rejections_raise_and_stop_is_reduce_only_trigger():
    err = {"status": "ok", "response": {"data": {"statuses": [{"error": "Insufficient margin"}]}}}
    with pytest.raises(OrderRefused, match="ORDER_ERROR"):
        _live(err).market("BTC", 1, 0.002, reduce_only=False, reason="ENTRY")
    rest = {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": 991}}]}}}
    b = _live(rest)
    assert b.place_stop("BTC", 1, 0.002, 55000.0) == "991"
    call = b.ex.calls[0]
    assert call["reduce_only"] and not call["is_buy"]
    assert call["order_type"]["trigger"] == {"triggerPx": 55000.0, "isMarket": True, "tpsl": "sl"}


def test_live_preflight_refuses_unknown_state():
    b = _live({}, FakeInfo())
    assert b.preflight("0xagent", ("BTC",), {}, set())["account_value"] == 500.0
    with pytest.raises(LiveLocked, match="AGENT_NOT_APPROVED"):
        _live({}, FakeInfo(agents=[])).preflight("0xagent", ("BTC",), {}, set())
    with pytest.raises(LiveLocked, match="NOT_FUNDED"):
        _live({}, FakeInfo(value="3")).preflight("0xagent", ("BTC",), {}, set())
    with pytest.raises(LiveLocked, match="UNOWNED_OR_MISMATCHED_POSITION"):
        _live({}, FakeInfo(positions={"ETH": 1.0})).preflight("0xagent", ("BTC",), {}, set())
    with pytest.raises(LiveLocked, match="UNOWNED_OPEN_ORDER"):
        _live({}, FakeInfo(orders=[{"coin": "BTC", "oid": 5}])).preflight("0xagent", ("BTC",), {}, set())


# ---------------------------------------------------------------- small accounts and Indian venues
from compounder.india_venues import CoinDCXPublic, DeltaIndiaPublic, funding_times  # noqa: E402

SMALL = RiskParams(0.02, 3.0, 5.0, 10.0, min_size_max_risk=0.20, max_open_risk=0.40)


def test_min_size_override_takes_venue_minimum_only_within_risk_cap():
    # XRP-like: $6 minimum, 0.1 step, stop 13% away -> 6.6 coins, about 8.5% of Rs 1,000 at risk
    q = size_order(9.51, 0.9224, 0.80, 0.0, SMALL, 6.0, qty_step=0.1)
    assert q == pytest.approx(6.6) and q * (0.9224 - 0.80) <= 0.20 * 9.51
    # BTC-like: $60 minimum would put >100% of the account at risk -> refused
    assert size_order(9.51, 59338.0, 53400.0, 0.0, SMALL, 60.0, qty_step=0.001) == 0.0
    # override off (the $1,000 profiles): below-minimum is simply skipped
    assert size_order(9.51, 0.9224, 0.80, 0.0, RiskParams(0.02, 3.0, 5.0, 10.0), 6.0, qty_step=0.1) == 0.0


def test_open_risk_cap_and_per_coin_leverage():
    # 37% of equity already at risk: 40% cap leaves too little for a minimum order
    assert size_order(9.51, 0.9224, 0.80, 0.0, SMALL, 6.0, qty_step=0.1, open_risk=3.5) == 0.0
    # $1 of free margin at the coin's 5x cap = $5 of notional < $6 minimum -> refused
    assert size_order(9.51, 68.0, 60.0, 0.0, SMALL, 6.0, qty_step=0.01, free_margin=1.0, coin_leverage=5) == 0.0


def test_per_coin_margin_matches_uniform_margin_when_leverage_is_uniform():
    risk = RiskParams(0.05, 10.0, 10.0, 5.0)
    old = size_order(1000.0, 100.0, 99.0, 500.0, risk, 10.0)
    new = size_order(1000.0, 100.0, 99.0, 500.0, risk, 10.0, free_margin=1000.0 - 500.0 / 5, coin_leverage=5)
    assert old == pytest.approx(new) == pytest.approx(45.0)


class _Resp:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload


class _Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for key, payload in self.routes.items():
            if key in url:
                return _Resp(payload(params) if callable(payload) else payload)
        raise AssertionError(url)


def test_coindcx_adapter_parses_public_data_and_settled_funding():
    clock = {"t": 1_795_593_600.0}  # exactly a 08:00 UTC settlement
    routes = {
        "futures/data/instrument": {"instrument": {"status": "active", "quantity_increment": 0.1,
                                                   "max_leverage_long": 10.0, "min_notional": 6.0,
                                                   "price_increment": 0.0001}},
        "current_prices/futures/rt": lambda p: {"prices": {"B-XRP_USDT": {"mp": 0.92, "ls": 0.921,
                                                                          "fr": 0.0001 if clock["t"] > 1_795_593_700 else 0.0003}}},
        "orderbook/B-XRP_USDT-futures": {"ts": 1, "bids": {"0.919": "5", "0.92": "10"}, "asks": {"0.923": "4", "0.921": "8"}},
        "candlesticks": {"s": "ok", "data": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "time": 1795564800000},
                                             {"open": 1, "high": 2, "low": 0.5, "close": 1.2, "time": 1795478400000}]},
    }
    md = CoinDCXPublic(("XRP",), session=_Session(routes), clock=lambda: clock["t"])
    spec = md.specs()["XRP"]
    assert (spec.qty_step, spec.min_notional, spec.max_leverage, spec.size_decimals) == (0.1, 6.0, 10, 1)
    bids, asks, _ = md.book("XRP")
    assert bids[0] == (0.92, 10.0) and asks[0] == (0.921, 8.0)
    rows = md.candles("XRP", "1d", 300)            # 25 Nov bar still open at 08:00 -> dropped
    assert [r["t"] for r in rows] == [1795478400000]
    md.contexts()                                   # before settlement: fr 0.0003 (previous period)
    clock["t"] += 120
    md.contexts()                                   # after settlement: fr 0.0001 (just settled)
    assert md.funding_history("XRP", 1_795_593_600_000 - 1, 1_795_593_600_000) == [(1_795_593_600_000, 0.0001)]


def test_delta_adapter_converts_contracts_percent_funding_and_seconds():
    clock = {"t": 1_795_593_000.0}  # 10 minutes before a settlement
    routes = {
        "/v2/products/XRPUSD": {"result": {"contract_type": "perpetual_futures", "state": "live",
                                           "contract_value": "1", "initial_margin": "1"}},
        "/v2/products/DOGEUSD": {"result": {"contract_type": "perpetual_futures", "state": "live",
                                            "contract_value": "100", "initial_margin": "1"}},
        "/v2/tickers": {"result": [{"symbol": "DOGEUSD", "mark_price": "0.0545", "funding_rate": "0.01",
                                    "quotes": {"best_bid": "0.0544", "best_ask": "0.0546"}}]},
        "/v2/l2orderbook/DOGEUSD": {"result": {"buy": [{"price": "0.0544", "size": 3}],
                                               "sell": [{"price": "0.0546", "size": 2}]}},
        "/v2/history/candles": {"result": [{"time": 1795478400, "open": 1, "high": 2, "low": 0.5, "close": 1.0},
                                           {"time": 1795392000, "open": 1, "high": 2, "low": 0.5, "close": 1.1}]},
    }
    md = DeltaIndiaPublic(("XRP", "DOGE"), session=_Session(routes), clock=lambda: clock["t"])
    specs = md.specs()
    assert specs["DOGE"].qty_step == 100.0 and specs["XRP"].qty_step == 1.0 and specs["XRP"].max_leverage == 100
    bids, asks, _ = md.book("DOGE")
    assert bids == [(0.0544, 300.0)] and asks == [(0.0546, 200.0)]       # contracts -> coins
    assert [r["t"] for r in md.candles("DOGE", "1d", 10)] == [1795392000000, 1795478400000]
    ctx = md.contexts()["DOGE"]
    assert ctx.funding_hourly == pytest.approx(0.0001 / 8)                 # 0.01% per 8 h
    assert md.funding_history("DOGE", 1_795_593_000_000, 1_795_593_600_000) == [(1_795_593_600_000, 0.0001)]


def test_funding_times_are_8h_settlements():
    assert funding_times(0, 86_400_000) == [28_800_000, 57_600_000, 86_400_000]
    assert funding_times(28_800_000, 28_800_000) == []


class SmallMarket(FakeMarket):
    def specs(self):
        return {"BTC": AssetSpec("BTC", 1, 10, qty_step=0.1, min_notional=6.0)}


def test_runner_small_account_trades_venue_minimum_with_capped_risk(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = SmallMarket([1.0] * 10, start)
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t", "1d", 5, 3, 5, 2.0, True),
                       risk=SMALL, costs=COINDCX_FUTURES_FOR_TEST, tax_policy=TaxPolicy("VDA_PER_TRADE"),
                       start_equity=9.51, mandate_hash="small", bar_settle_ms=0)
    r = Runner(cfg, m, PaperBroker(m, COINDCX_FUTURES_FOR_TEST, clock=m.clock), clock=m.clock, sleep=lambda s: None)
    r.step()
    m.closes.append(1.1)
    m.now_ms += DAY_MS
    m.mark = 1.1
    r.step()
    pos = r.state.positions["BTC"]
    assert pos["qty"] * pos["entry_price"] >= 6.0                       # venue minimum reached
    assert pos["qty"] * (pos["entry_price"] - pos["stop"]) <= 0.20 * 9.51  # stop risk within 20%


from compounder.costs import COINDCX_FUTURES as COINDCX_FUTURES_FOR_TEST  # noqa: E402


def test_sizing_accepts_numpy_scalars():
    q = size_order(np.float64(9.51), np.float64(0.9224), 0.80, 0.0, SMALL, 6.0, qty_step=0.1)
    assert q == pytest.approx(6.6)
    assert str(round_down(np.float64(0.123456), 3)) == "0.123"


# ---------------------------------------------------------------- CoinDCX live (offline fakes only)
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402
import json as _json  # noqa: E402

import requests as _requests  # noqa: E402

from compounder.coindcx_live import (CoinDCXLiveBroker, CoinDCXLiveGate, CoinDCXPrivate,  # noqa: E402
                                     LiveLocked as DcxLocked, activation_phrase as dcx_phrase)
from compounder.costs import COINDCX_FUTURES  # noqa: E402
from compounder.runner import IntradayRunner  # noqa: E402
from compounder.intraday import IntradayParams  # noqa: E402


class _RecSession:
    def __init__(self):
        self.sent = []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.sent.append((method, url, data, headers))
        return _Resp([{"ok": True}])


def test_coindcx_signing_matches_docs_and_hides_secret():
    sess = _RecSession()
    api = CoinDCXPrivate("KEY", "SECRET", session=sess, clock=lambda: 1_700_000_000.0, sleep=lambda s: None)
    api.positions("INR")
    method, url, data, headers = sess.sent[0]
    body = {"page": "1", "size": "100", "margin_currency_short_name": ["INR"], "timestamp": 1_700_000_000_000}
    expected = _json.dumps(body, separators=(",", ":"))
    assert method == "POST" and url.endswith("/exchange/v1/derivatives/futures/positions") and data == expected
    assert headers["X-AUTH-APIKEY"] == "KEY"
    assert headers["X-AUTH-SIGNATURE"] == _hmac.new(b"SECRET", expected.encode(), _hashlib.sha256).hexdigest()
    assert "SECRET" not in repr(api)


class FakeDCX:
    """In-memory CoinDCX: a market order opens/closes the position at a fixed price."""
    def __init__(self, price=0.0545, lose_reply=False, fill=True, liq=0.0):
        self.price, self.lose_reply, self.fill, self.liq = price, lose_reply, fill, liq
        self.pos = {}       # pair -> qty
        self.calls = []
        self.stops = {}

    def _row(self, pair):
        q = self.pos.get(pair, 0.0)
        return {"id": f"pos-{pair}", "pair": pair, "active_pos": q, "avg_price": self.price if q else 0.0,
                "mark_price": self.price, "liquidation_price": self.liq if q else 0.0,
                "inactive_pos_buy": 0.0, "inactive_pos_sell": 0.0}

    def positions(self, ccy):
        return [self._row(p) for p in set(self.pos) | {"B-DOGE_USDT"}]

    def update_leverage(self, pair, lev, ccy):
        self.calls.append(("lev", pair, lev))

    def create_market_order(self, pair, side, qty, lev, ccy):
        self.calls.append(("order", pair, side, qty, lev))
        if self.fill:
            self.pos[pair] = self.pos.get(pair, 0.0) + (qty if side == "buy" else -qty)
        if self.lose_reply:
            raise _requests.ConnectionError("reply lost")
        return [{"id": "o1", "status": "initial"}]

    def create_stop_loss(self, position_id, stop_price):
        self.calls.append(("stop", position_id, stop_price))
        self.stops[position_id] = stop_price
        return {"stop_loss": {"id": "s1", "status": "untriggered"}, "take_profit": {"success": False}}

    def exit_position(self, position_id):
        self.calls.append(("exit", position_id))
        self.pos[position_id.replace("pos-", "")] = 0.0

    def cancel_all_for_position(self, position_id):
        self.calls.append(("cancel_all", position_id))

    def cancel_order(self, oid):
        self.calls.append(("cancel", oid))

    def trades(self, pair, a, b, ccy):
        return [{"price": self.price, "quantity": 110.0, "side": "sell", "timestamp": 9e15, "fee_amount": 0.004}]

    def wallets(self):
        return [{"currency_short_name": "INR", "balance": "1000"}]

    def conversion_price(self):
        return 106.0

    def orders(self, status, side, ccy):
        return []


class _DcxBook(FakeMarket):
    def book(self, coin):
        return [(0.0544, 1e6)], [(0.0546, 1e6)], 0


def _dcx(api):
    m = _DcxBook([0.0545] * 3, 0)
    specs = {"DOGE": AssetSpec("DOGE", 0, 10, qty_step=1.0, min_notional=6.0, price_step=0.00001)}
    return CoinDCXLiveBroker(api=api, md=m, costs=COINDCX_FUTURES, specs=specs, fill_timeout_s=0.0, poll_s=0.0,
                             clock=lambda: 1.0, sleep=lambda s: None)


def test_coindcx_entry_sets_leverage_rounds_qty_and_books_fill():
    api = FakeDCX()
    b = _dcx(api)
    f = b.market("DOGE", 1, 110.7, reduce_only=False, reason="ENTRY", leverage=4)
    assert ("lev", "B-DOGE_USDT", 4) in api.calls
    assert ("order", "B-DOGE_USDT", "buy", 110.0, 4) in api.calls      # rounded DOWN to the 1-coin step
    assert f.qty == 110.0 and f.price == 0.0545 and f.side == 1
    with pytest.raises(OrderRefused, match="NOT_FLAT"):
        b.market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=4)


def test_coindcx_lost_reply_is_adopted_or_refused_never_resent():
    b = _dcx(FakeDCX(lose_reply=True, fill=True))
    assert b.market("DOGE", -1, 110, reduce_only=False, reason="ENTRY", leverage=3).qty == 110.0
    api = FakeDCX(lose_reply=True, fill=False)
    with pytest.raises(OrderRefused, match="ENTRY_NOT_PLACED"):
        _dcx(api).market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=3)
    assert sum(1 for c in api.calls if c[0] == "order") == 1          # exactly one order sent


def test_coindcx_stop_rounds_toward_entry_and_exit_flattens():
    api = FakeDCX()
    b = _dcx(api)
    b.market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=4)
    assert b.place_stop("DOGE", 1, 110, 0.0480012) == "s1"
    assert ("stop", "pos-B-DOGE_USDT", "0.04801") in api.calls        # long stop rounded UP to the tick
    f = b.market("DOGE", -1, 110, reduce_only=True, reason="CHANNEL")
    assert ("exit", "pos-B-DOGE_USDT") in api.calls and api.pos["B-DOGE_USDT"] == 0.0
    assert f.side == -1 and f.qty == 110.0
    assert b.account_value() == pytest.approx(1000 / 106.0)


def test_coindcx_liquidation_check():
    b = _dcx(FakeDCX(liq=0.0490))
    b.market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=10)
    assert not b.liquidation_ok("DOGE", 1, 0.0480)     # liquidation would come before the stop
    assert b.liquidation_ok("DOGE", 1, 0.0500)


def test_coindcx_gate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    key = tmp_path / "dcx.json"
    key.write_text(_json.dumps({"key": "k", "secret": "s"}))
    key.chmod(0o600)
    receipt = tmp_path / "r.json"
    m = {"mode": "LIVE", "live_orders_allowed": True, "venue": "coindcx_futures"}
    receipt.write_text(_json.dumps({"mandate_hash": "abcdef12", "typed": dcx_phrase("abcdef12")}))
    CoinDCXLiveGate(m, "abcdef12", receipt, key, repo).verify()
    with pytest.raises(DcxLocked, match="NOT_COINDCX"):
        CoinDCXLiveGate({**m, "venue": "hyperliquid"}, "abcdef12", receipt, key, repo).verify()
    with pytest.raises(DcxLocked, match="DOES_NOT_MATCH"):
        CoinDCXLiveGate(m, "zzzzzz99", receipt, key, repo).verify()
    key.chmod(0o644)
    with pytest.raises(DcxLocked, match="0600"):
        CoinDCXLiveGate(m, "abcdef12", receipt, key, repo).verify()


class _LiveFake:
    """Broker stub for runner reconcile tests."""
    mode = "LIVE"

    def __init__(self, positions):
        self._pos = positions
        self.closed = []

    def positions(self):
        return dict(self._pos)

    def account_value(self):
        return 9.43

    def market(self, coin, side, qty, *, reduce_only, reason, leverage=None):
        from compounder.brokers import Fill
        self.closed.append((coin, side, qty, reason))
        self._pos.pop(coin, None)
        return Fill(coin, side, qty, 1.0, 0.0, 1.0, 0, reason)

    def stop_triggered(self, coin, pos_side, stop, contexts):
        return coin not in self._pos

    def funding(self, coin, a, b):
        return []

    def cancel_stop(self, coin, oid):
        return None


def test_runner_live_reconcile_closes_unknown_position_and_halts(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t", "1d", 5, 3, 5, 2.0, True),
                       risk=SMALL, costs=COINDCX_FUTURES, tax_policy=TaxPolicy(), start_equity=9.43,
                       mandate_hash="live", bar_settle_ms=0)
    broker = _LiveFake({"BTC": 0.5})
    r = Runner(cfg, m, broker, clock=m.clock, sleep=lambda s: None)
    r.step()
    assert broker.closed and broker.closed[0][3] == "UNKNOWN_POSITION_CLOSE"
    assert r.state.halted == "LIVE_UNKNOWN_POSITION" and r.entries_blocked() == "LIVE_UNKNOWN_POSITION"


class HourlyMarket(FakeMarket):
    """Hourly candles: 25 flat days (price 100, the regime builds), then a breakout day."""
    def __init__(self, start):
        self.start = start
        self.rows = []
        for d in range(25):
            for hr in range(24):
                c = 100.0 + d * 0.5           # rising daily closes -> UP regime
                self.rows.append({"t": start + (d * 24 + hr) * 3_600_000, "o": c, "h": c + 0.2, "l": c - 0.2, "c": c})
        self.now_ms = self.rows[-1]["t"] + 3_600_000 + 60_000
        self.mark = self.rows[-1]["c"]
        self.funding_rate = 0.0

    def specs(self):
        return {"BTC": AssetSpec("BTC", 3, 20, qty_step=0.001, min_notional=6.0)}

    def add(self, c, hi=None, lo=None):
        t = self.rows[-1]["t"] + 3_600_000
        self.rows.append({"t": t, "o": c, "h": hi or c + 0.2, "l": lo or c - 0.2, "c": c})
        self.now_ms = t + 3_600_000 + 60_000
        self.mark = c

    def candles(self, coin, interval, bars):
        return [r for r in self.rows if r["t"] + 3_600_000 <= self.now_ms][-bars:]


def test_intraday_runner_trades_with_direction_and_is_flat_at_day_end(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = HourlyMarket(start)
    p = IntradayParams("t", "DON", entry_n=24, exit_n=12, atr_n=24, stop_atr=2.0, regime_sma=20)
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=p, risk=RiskParams(0.01, 1.0, 3.0, 5.0),
                       costs=COINDCX_FUTURES, tax_policy=TaxPolicy(), start_equity=1000.0, mandate_hash="i",
                       bar_settle_ms=0)
    r = IntradayRunner(cfg, m, PaperBroker(m, COINDCX_FUTURES, clock=m.clock), clock=m.clock, sleep=lambda s: None)
    r.step()
    for k in range(6):                       # new day: hours 00..05 drift, then a breakout at 06:00
        m.add(112.0)
        r.step()
    m.add(114.0, hi=114.1, lo=113.0)
    r.step()
    assert r.state.positions["BTC"]["side"] == 1
    while (m.rows[-1]["t"] % DAY_MS) // 3_600_000 != 23:
        m.add(114.5)
        r.step()
    assert not r.state.positions                       # flat after the 23:00 bar
    assert r.journal.trades()[-1]["reason"] == "END_OF_DAY"


def test_vda_taxable_base_ignores_fees_and_taxes_funding_received():
    t = TaxLedger(TaxPolicy("VDA_PER_TRADE"))
    assert t.on_trade_closed(1775001600000, 9.0, taxable=10.0) == pytest.approx(3.12)
    assert TaxLedger(TaxPolicy("BUSINESS_NET_ANNUAL")).on_trade_closed(1775001600000, 9.0, taxable=10.0) == \
        pytest.approx(0.312 * 9.0)


# ---------------------------------------------------------------- profit locks and coin ranking (research add-ons)
from compounder.strategy import momentum_score, rotation_sides, top_by_volume, trail_stop  # noqa: E402


def test_trail_stop_follows_best_price_and_never_loosens():
    assert trail_stop(1, 90.0, 120.0, 5.0, 2.0) == 110.0      # long: best 120 - 2 x 5
    assert trail_stop(1, 112.0, 120.0, 5.0, 2.0) == 112.0     # never lowered
    assert trail_stop(-1, 110.0, 80.0, 5.0, 2.0) == 90.0      # short: best 80 + 2 x 5
    assert trail_stop(-1, 85.0, 80.0, 5.0, 2.0) == 85.0
    assert trail_stop(1, 90.0, 120.0, 5.0, 0.0) == 90.0       # off


def test_momentum_ranking_and_volume_universe():
    up = np.linspace(100, 150, 120) * (1 + 0.01 * np.sin(np.arange(120)))
    down = np.linspace(100, 60, 120) * (1 + 0.01 * np.cos(np.arange(120)))
    assert momentum_score(up, 119, 90) > 0 > momentum_score(down, 119, 90)
    assert np.isnan(momentum_score(up, 50, 90))
    sides = rotation_sides({"A": 2.0, "B": 1.0, "C": -0.5, "D": -3.0, "E": float("nan")}, 1)
    assert sides == {"A": {1}, "B": set(), "C": set(), "D": {-1}, "E": set()}
    assert top_by_volume({"A": 5.0, "B": 9.0, "C": float("nan"), "D": 1.0}, 2) == {"A", "B"}


def _rally_then_crash():
    up = list(np.linspace(100, 200, 120))
    down = list(np.linspace(200, 120, 40))
    c = np.array([100.0] * 80 + up + down)
    o = np.concatenate([[c[0]], c[:-1]])
    t = np.arange(len(c), dtype=np.int64) * DAY_MS + 1_700_000_000_000 // DAY_MS * DAY_MS
    return Bars("BTC", t, o, np.maximum(o, c) * 1.005, np.minimum(o, c) * 0.995, c)


def test_trailing_stop_exits_earlier_in_a_reversal():
    import dataclasses as _dc
    b = [_rally_then_crash()]
    base = TrendParams("b", "1d", 55, 20, 20, 2.0, False)
    plain = run(b, base, FREE, RiskParams(0.01, 1.0, 3.0, 5.0), tax_policy=TaxPolicy("NONE"))
    trail = run(b, _dc.replace(base, trail_atr=2.0), FREE, RiskParams(0.01, 1.0, 3.0, 5.0),
                tax_policy=TaxPolicy("NONE"))
    first_plain = plain.trades[0]
    first_trail = trail.trades[0]
    assert first_trail.exit_time <= first_plain.exit_time
    assert first_trail.peak_profit > 0 and first_trail.gross / first_trail.peak_profit >= \
        first_plain.gross / first_plain.peak_profit


def test_equity_guard_closes_and_pauses():
    b = [_rally_then_crash()]
    base = TrendParams("b", "1d", 55, 20, 20, 2.0, False)
    res = run(b, base, FREE, RiskParams(0.05, 3.0, 3.0, 5.0), tax_policy=TaxPolicy("NONE"), guard_dd=0.05,
              guard_pause_days=30)
    assert any(t.reason == "EQUITY_GUARD" for t in res.trades)


# ---------------------------------------------------------------- live safety fixes (25 Nov, before the first real trade)
from compounder.coindcx_live import CoinDCXError  # noqa: E402
from compounder.market_data import DataError  # noqa: E402
from compounder.runner import STOP_FILL_WAIT_MS  # noqa: E402


def test_coindcx_wallet_total_counts_locked_margin():
    """CoinDCX docs: "Total wallet balance = balance + locked_balance"; an open isolated position's
    margin sits in locked_balance, so balance alone would look like a loss of that margin."""
    class Locked(FakeDCX):
        def wallets(self):
            return [{"currency_short_name": "INR", "balance": "666.0", "locked_balance": "334.0",
                     "cross_order_margin": "0.0", "cross_user_margin": "0.0"}]
    b = _dcx(Locked())
    b.market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=2)   # mark == avg: no open P&L
    assert b.wallet_total() == pytest.approx(1000.0)
    assert b.account_value() == pytest.approx(1000 / 106.0)
    assert issubclass(CoinDCXError, DataError)          # the runner logs exchange errors instead of stopping


def test_coindcx_fill_lookup_covers_ist_dates_and_falls_back_when_refused():
    class Dated(FakeDCX):
        def __init__(self, refuse_after=None):
            super().__init__()
            self.refuse_after, self.windows = refuse_after, []

        def trades(self, pair, a, b, ccy):
            self.windows.append((a, b))
            if self.refuse_after and b > self.refuse_after:
                raise CoinDCXError("HTTP_400:to_date in the future")
            return super().trades(pair, a, b, ccy)

    def broker(api, clock_s):
        return CoinDCXLiveBroker(api=api, md=_DcxBook([0.0545] * 3, 0), costs=COINDCX_FUTURES,
                                 specs={"DOGE": AssetSpec("DOGE", 0, 10, qty_step=1.0)}, clock=lambda: clock_s,
                                 sleep=lambda s: None)
    api = Dated()
    assert broker(api, 72_000.0)._fills_since("DOGE", "sell", 0)          # 20:00 UTC = 01:30 IST next day
    assert api.windows == [("1969-12-31", "1970-01-03")]                   # a day early .. day after today in India
    api = Dated(refuse_after="1970-01-02")
    assert broker(api, 72_000.0)._fills_since("DOGE", "sell", 0)
    assert api.windows == [("1969-12-31", "1970-01-03"), ("1969-12-31", "1970-01-02")]


def test_coindcx_exit_never_fails_once_the_position_is_flat():
    class NoHistory(FakeDCX):
        def trades(self, pair, a, b, ccy):
            raise CoinDCXError("HTTP_500:busy")
    api = NoHistory()
    b = _dcx(api)
    b.market("DOGE", 1, 110, reduce_only=False, reason="ENTRY", leverage=2)
    f = b.market("DOGE", -1, 110, reduce_only=True, reason="CHANNEL")
    assert api.pos["B-DOGE_USDT"] == 0.0 and f.qty == 110 and f.price == pytest.approx(0.0545)


class _LiveSim:
    """A tiny exchange for LIVE runner tests: market orders fill at the fake market's mark."""
    mode = "LIVE"

    def __init__(self, market):
        self.m, self.pos, self.calls = market, {}, []
        self.fail_exits = self.fail_stops = self.boom = 0
        self.fills_ready, self.stop_px, self.hidden = True, 0.0, set()
        self.equity = 1000.0

    def usd_inr(self):
        return 100.0

    def positions(self):
        if self.boom:
            self.boom -= 1
            raise KeyError("active_pos")
        return {c: q for c, q in self.pos.items() if c not in self.hidden}

    def account_value(self):
        return self.equity

    def market(self, coin, side, qty, *, reduce_only, reason, leverage=None):
        from compounder.brokers import Fill
        self.calls.append(("exit" if reduce_only else "entry", coin, reason))
        if reduce_only:
            if self.fail_exits:
                self.fail_exits -= 1
                raise CoinDCXError("HTTP_503:busy")
            self.pos.pop(coin, None)
        else:
            self.pos[coin] = side * qty
        return Fill(coin, side, qty, self.m.mark, 0.0, self.m.mark, int(self.m.now_ms), reason)

    def place_stop(self, coin, pos_side, qty, trigger):
        self.calls.append(("stop", coin))
        if self.fail_stops:
            self.fail_stops -= 1
            raise OrderRefused("STOP_NOT_ACCEPTED")
        return "s1"

    def cancel_stop(self, coin, oid):
        self.calls.append(("cancel", coin, oid))

    def stop_triggered(self, coin, pos_side, stop, contexts):
        return coin not in self.positions()

    def exit_fill_after_stop(self, coin, pos_side, qty, since_ms):
        from compounder.brokers import Fill
        if not self.fills_ready:
            raise DataError("STOP_FILL_NOT_INDEXED")
        return Fill(coin, -pos_side, qty, self.stop_px, 0.0, self.stop_px, int(self.m.now_ms), "STOP")

    def funding(self, coin, a, b):
        return []


def _live_entered(tmp_path, **sim_over):
    """A LIVE runner that has just entered BTC long on a breakout (stop id s1 on the exchange)."""
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    sim = _LiveSim(m)
    for k, v in sim_over.items():
        setattr(sim, k, v)
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t", "1d", 5, 3, 5, 2.0, False),
                       risk=RiskParams(0.01, 1.0, 3.0, 5.0), costs=HYPERLIQUID, tax_policy=TaxPolicy("VDA_PER_TRADE"),
                       start_equity=1000.0, mandate_hash="live-test", bar_settle_ms=0)
    r = Runner(cfg, m, sim, clock=m.clock, sleep=lambda s: None)
    r.step()
    m.closes.append(110.0)
    m.now_ms += DAY_MS
    m.mark = 110.0
    r.step()
    return r, m, sim


def _events(r):
    return [_json.loads(x) for x in (r.cfg.run_dir / "events.jsonl").read_text().splitlines()]


def test_live_failed_exit_keeps_the_stop_and_is_retried_next_loop(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    assert r.state.positions["BTC"]["stop_order_id"] == "s1"
    for c in (120.0, 130.0, 140.0):
        m.closes.append(c)
        m.now_ms += DAY_MS
        m.mark = c
        r.step()
    sim.fail_exits = 1
    m.closes.append(100.0)                       # channel exit bar; the exchange is busy
    m.now_ms += DAY_MS
    m.mark = 101.0
    r.step()
    assert "BTC" in r.state.positions and r.state.extra["exit_retry"] == {"BTC": "CHANNEL"}
    assert not any(c[0] == "cancel" for c in sim.calls)          # the exchange stop was NOT cancelled
    m.now_ms += 20_000
    r.step()                                     # retried on the next loop, not a day later
    assert not r.state.positions and r.state.extra["exit_retry"] == {}
    assert r.journal.trades()[-1]["reason"] == "CHANNEL"
    last_exit = max(i for i, c in enumerate(sim.calls) if c[0] == "exit")
    assert sim.calls[last_exit + 1] == ("cancel", "BTC", "s1")   # stop cancelled only after the close


def test_live_stop_fill_lag_does_not_block_and_books_real_fill(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    sim.pos.pop("BTC")                           # the exchange stop filled
    sim.fills_ready, sim.stop_px = False, 103.0
    m.now_ms += 20_000
    r.step()                                     # no exception; still waiting for the fills
    assert "BTC" in r.state.positions and "BTC" in r.state.extra["stop_fill_pending"]
    assert (r.cfg.run_dir / "status.json").exists()
    sim.fills_ready = True
    m.now_ms += 20_000
    r.step()
    t = r.journal.trades()[-1]
    assert not r.state.positions and t["reason"] == "STOP" and t["exit_price"] == 103.0
    assert r.state.extra["stop_fill_pending"] == {}


def test_live_stop_fill_missing_for_30_minutes_is_estimated(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    stop = r.state.positions["BTC"]["stop"]
    sim.pos.pop("BTC")
    sim.fills_ready = False
    m.now_ms += 20_000
    r.step()
    assert "BTC" in r.state.positions
    m.now_ms += STOP_FILL_WAIT_MS
    r.step()
    t = r.journal.trades()[-1]
    assert not r.state.positions and t["reason"] == "STOP_ESTIMATED"
    assert t["exit_price"] == pytest.approx(stop * (1 - HYPERLIQUID.slip("BTC", stop=True)))


def test_live_position_read_glitch_does_not_book_a_stop(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    sim.hidden = {"BTC"}
    sim.fills_ready = False
    m.now_ms += 20_000
    r.step()
    assert "BTC" in r.state.extra["stop_fill_pending"]
    sim.hidden = set()
    m.now_ms += 20_000
    r.step()
    assert "BTC" in r.state.positions and r.state.extra["stop_fill_pending"] == {}


def test_live_position_without_exchange_stop_is_closed(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    r.state.positions["BTC"]["stop_order_id"] = None   # e.g. stopped between the fill and the stop
    m.now_ms += 20_000
    r.step()
    assert not r.state.positions and r.journal.trades()[-1]["reason"] == "NO_EXCHANGE_STOP"


def test_live_failed_flatten_after_stop_failure_is_retried(tmp_path):
    r, m, sim = _live_entered(tmp_path, fail_stops=1, fail_exits=1)
    assert "BTC" in r.state.positions and r.state.extra["exit_retry"] == {"BTC": "NO_STOP_FLATTEN"}
    m.now_ms += 20_000
    r.step()
    assert not r.state.positions and r.journal.trades()[-1]["reason"] == "NO_STOP_FLATTEN"


def test_run_forever_logs_unexpected_errors_and_keeps_running(tmp_path):
    r, m, sim = _live_entered(tmp_path)
    sim.boom = 1
    naps = []

    def nap(s):
        naps.append(s)
        m.now_ms += 20_000
        if len(naps) == 2:
            (tmp_path / "STOP").write_text("x")
    r.sleep = nap
    r.run_forever()                               # a KeyError in one loop must not end the bot
    errors = [e for e in _events(r) if e["kind"] == "STEP_ERROR"]
    assert len(errors) == 1 and "KeyError" in errors[0]["error"] and len(naps) == 2
    assert "BTC" in r.state.positions



# ---------------------------------------------------------------- the user's hard total-loss limit (Rs 100)
def _floor_runner(tmp_path, max_loss_inr, equity_usd=10.0, start_inr=1000.0):
    """LIVE runner on Rs 1,000 (= $10 at Rs 100/USD here) with a total-loss limit; a BTC breakout bar
    completes on the second step (CoinDCX costs: $6 minimum order)."""
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = FakeMarket([100.0] * 10, start)
    sim = _LiveSim(m)
    sim.equity = equity_usd
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=TrendParams("t", "1d", 5, 3, 5, 2.0, False),
                       risk=SMALL, costs=COINDCX_FUTURES, tax_policy=TaxPolicy("VDA_PER_TRADE"),
                       start_equity=start_inr / 100.0, start_equity_inr=start_inr, max_total_loss_inr=max_loss_inr,
                       mandate_hash="floor",
                       bar_settle_ms=0)
    r = Runner(cfg, m, sim, clock=m.clock, sleep=lambda s: None)
    r.step()
    m.closes.append(110.0)
    m.now_ms += DAY_MS
    m.mark = 110.0
    r.step()
    return r, m, sim


def test_loss_limit_allows_a_trade_whose_stop_fits_and_skips_one_that_does_not(tmp_path):
    r, m, sim = _floor_runner(tmp_path / "a", 100.0)      # floor Rs 900: $1.00 of room, 85% usable
    pos = r.state.positions["BTC"]
    worst = pos["qty"] * (pos["entry_price"] - pos["stop"])
    assert pos["qty"] * pos["entry_price"] >= 6.0 and worst < 0.85
    r, m, sim = _floor_runner(tmp_path / "b", 40.0)       # floor Rs 960: the $6 minimum would risk too much
    assert not r.state.positions
    assert any(e["kind"] == "ENTRY_SKIPPED_LOSS_LIMIT" for e in _events(r))


def test_loss_limit_shrinks_a_bigger_trade_to_fit(tmp_path):
    # Rs 10,000 account: the normal 2% risk is ~$2.0 at the stop
    r, m, sim = _floor_runner(tmp_path / "free", None, equity_usd=100.0, start_inr=10_000.0)
    free = r.state.positions["BTC"]["qty"]
    assert free * (r.state.positions["BTC"]["entry_price"] - r.state.positions["BTC"]["stop"]) == \
        pytest.approx(2.0, rel=0.05)
    # same account with a Rs 150 limit: $1.50 of room, 85% usable -> the trade is cut to fit
    r, m, sim = _floor_runner(tmp_path / "cut", 150.0, equity_usd=100.0, start_inr=10_000.0)
    pos = r.state.positions["BTC"]
    worst = pos["qty"] * (pos["entry_price"] - pos["stop"])
    assert pos["qty"] < free and worst <= 0.85 * 1.5 and pos["qty"] * pos["entry_price"] >= 6.0


def test_loss_limit_closes_everything_and_stays_stopped(tmp_path):
    r, m, sim = _floor_runner(tmp_path, 100.0)
    assert "BTC" in r.state.positions
    sim.equity = 8.95                                      # Rs 895: below the Rs 900 floor
    m.now_ms += 20_000
    r.step()
    assert not r.state.positions and r.state.halted == "LOSS_LIMIT"
    assert r.journal.trades()[-1]["reason"] == "LOSS_LIMIT"
    r.state.halted = None                                  # even a reset cannot trade below the floor
    m.closes.append(120.0)
    m.now_ms += DAY_MS
    m.mark = 120.0
    r.step()
    assert not r.state.positions and r.state.halted == "LOSS_LIMIT"
    assert r.status()["loss_floor_inr"] == 900.0


def test_intraday_rules_trade_live_with_stop_and_end_of_day_exit(tmp_path):
    start = 1_790_000_000_000 // DAY_MS * DAY_MS
    m = HourlyMarket(start)
    sim = _LiveSim(m)
    p = IntradayParams("t", "DON", entry_n=24, exit_n=12, atr_n=24, stop_atr=2.0, regime_sma=20)
    cfg = RunnerConfig(run_dir=tmp_path, universe=("BTC",), params=p, risk=RiskParams(0.01, 1.0, 3.0, 5.0),
                       costs=COINDCX_FUTURES, tax_policy=TaxPolicy(), start_equity=1000.0,
                       start_equity_inr=100_000.0, max_total_loss_inr=100.0, mandate_hash="i-live",
                       bar_settle_ms=0)
    r = IntradayRunner(cfg, m, sim, clock=m.clock, sleep=lambda s: None)
    r.step()
    for k in range(6):
        m.add(112.0)
        r.step()
    m.add(114.0, hi=114.1, lo=113.0)
    r.step()
    pos = r.state.positions["BTC"]
    assert pos["side"] == 1 and pos["stop_order_id"] == "s1" and sim.pos["BTC"] > 0
    assert pos["qty"] * (pos["entry_price"] - pos["stop"]) < 0.85     # Rs 100 limit = $1 of room
    while (m.rows[-1]["t"] % DAY_MS) // 3_600_000 != 23:
        m.add(114.5)
        r.step()
    assert not r.state.positions and not sim.pos
    assert r.journal.trades()[-1]["reason"] == "END_OF_DAY"
    last_exit = max(i for i, c in enumerate(sim.calls) if c[0] == "exit")
    assert sim.calls[last_exit + 1] == ("cancel", "BTC", "s1")


# ---------------------------------------------------------------- CoinDCX network resilience (25 Nov 2026)
from compounder.coindcx_live import READ_ATTEMPTS, CoinDCXError  # noqa: E402


class _FlakySession:
    """Fails the first ``fail`` calls (a network error, or an HTTP status), then answers 200."""
    def __init__(self, fail, how):
        self.fail, self.how, self.calls = fail, how, []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append((method, url, data))
        if len(self.calls) <= self.fail:
            if self.how == "network":
                raise _requests.ConnectionError("TLS handshake stalled")
            r = _Resp({"message": "busy"})
            r.status_code, r.text = self.how, "busy"
            return r
        return _Resp([{"currency_short_name": "INR", "balance": "1000"}])


def _dcx_api(sess, clock=lambda: 1_700_000_000.0):
    return CoinDCXPrivate("KEY", "SECRET", session=sess, clock=clock, sleep=lambda s: None)


def test_coindcx_reads_retry_a_network_stall_then_give_up():
    sess = _FlakySession(2, "network")
    assert _dcx_api(sess).wallets()[0]["balance"] == "1000" and len(sess.calls) == 3
    sess = _FlakySession(9, "network")
    with pytest.raises(_requests.ConnectionError):
        _dcx_api(sess).positions("INR")
    assert len(sess.calls) == READ_ATTEMPTS == 3


def test_coindcx_read_retries_are_signed_afresh():
    ticks = iter(range(1_700_000_000, 1_700_000_010))
    sess = _FlakySession(1, "network")
    _dcx_api(sess, clock=lambda: float(next(ticks))).positions("INR")
    first, second = (_json.loads(c[2])["timestamp"] for c in sess.calls)
    assert second > first          # a new timestamp (and so a new signature) on the retry


def test_coindcx_reads_retry_server_errors_but_not_refusals():
    sess = _FlakySession(1, 503)
    assert _dcx_api(sess).orders("open", "buy", "INR") and len(sess.calls) == 2
    sess = _FlakySession(1, 401)
    with pytest.raises(CoinDCXError, match="HTTP_401") as ex:
        _dcx_api(sess).wallets()
    assert ex.value.status == 401 and len(sess.calls) == 1


def test_coindcx_orders_stops_and_exits_are_sent_only_once():
    for send in (lambda api: api.create_market_order("B-DOGE_USDT", "buy", 116.0, 2, "INR"),
                 lambda api: api.create_stop_loss("pos-1", "0.05"),
                 lambda api: api.exit_position("pos-1"),
                 lambda api: api.update_leverage("B-DOGE_USDT", 2, "INR")):
        sess = _FlakySession(1, "network")
        with pytest.raises(_requests.ConnectionError):
            send(_dcx_api(sess))
        assert len(sess.calls) == 1
