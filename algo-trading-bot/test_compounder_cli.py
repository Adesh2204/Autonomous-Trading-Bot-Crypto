"""Offline tests of the compounder CLI helpers (temp folders and fake HTTP only; nothing live)."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_compounder_cli", ROOT / "scripts" / "run_compounder.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_make_coindcx_mandate_writes_live_copy_of_the_practice_plan(tmp_path, monkeypatch):
    for name in ("mandate_paper_coindcx_rs1000_daily.json", "mandate_paper_coindcx_rs1000_intraday.json"):
        shutil.copy(rc.DOCS / name, tmp_path / name)
    monkeypatch.setattr(rc, "DOCS", tmp_path)
    import requests
    monkeypatch.setattr(requests, "get", lambda url, timeout=None: _Resp(
        [{"symbol": "USDTINR", "conversion_price": 106.0}]))
    rc.cmd_make_dcx_mandate("daily", 1000.0)
    live = json.loads((tmp_path / "mandate_live_coindcx_daily.json").read_text())
    paper = json.loads((tmp_path / "mandate_paper_coindcx_rs1000_daily.json").read_text())
    assert live["mode"] == "LIVE" and live["live_orders_allowed"] is True and live["venue"] == "coindcx_futures"
    assert live["start_equity_inr"] == 1000.0 and live["start_equity_usd"] == pytest.approx(1000 / 106, abs=1e-4)
    assert live["strategy"] == paper["strategy"] and live["risk"] == paper["risk"]       # same plan as practice
    assert "LIVE" in live["label"] and "PRACTICE" not in live["label"]
    rc.cmd_make_dcx_mandate("intraday", 1000.0)
    assert json.loads((tmp_path / "mandate_live_coindcx_intraday.json").read_text())["strategy"]["kind"] == "DON"


def test_practice_mandates_build_the_right_runner():
    from compounder.intraday import IntradayParams
    for name, intraday in (("mandate_paper_coindcx_rs1000_daily.json", False),
                           ("mandate_paper_coindcx_rs1000_intraday.json", True),
                           ("mandate_paper.json", False)):
        mandate, digest = rc.load_mandate(rc.DOCS / name)
        cfg = rc.build_config(mandate, digest)
        assert isinstance(cfg.params, IntradayParams) is intraday
        assert (rc.runner_class(cfg) is rc.IntradayRunner) is intraday


def test_live_commands_refuse_without_key_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DCX_KEY_PATH", tmp_path / "missing.json")
    mandate, digest = rc.load_mandate(rc.DOCS / "mandate_paper_coindcx_rs1000_daily.json")
    from compounder.coindcx_live import LiveLocked
    with pytest.raises(LiveLocked, match="API_KEY_FILE_MISSING"):
        rc._dcx_parts(mandate)


def _fake_dcx():
    """A fake CoinDCX account with the documented wallet rule (margin moves into locked_balance)."""
    import time as _time
    from test_compounder import FakeDCX, _DcxBook
    from compounder.coindcx_live import CoinDCXLiveBroker
    from compounder.costs import COINDCX_FUTURES
    from compounder.market_data import AssetContext, AssetSpec

    class Exchange(FakeDCX):
        def wallets(self):
            margin = sum(abs(q) * self.price * 106.0 / 2 for q in self.pos.values())
            return [{"currency_short_name": "INR", "balance": str(1000.0 - margin), "locked_balance": str(margin),
                     "cross_order_margin": "0.0", "cross_user_margin": "0.0"}]

        def trades(self, pair, a, b, ccy):
            return [{"price": self.price, "quantity": 116.0, "side": s, "timestamp": _time.time() * 1000,
                     "fee_amount": 0.004} for s in ("buy", "sell")]

    class Md(_DcxBook):
        PUB = "https://public.example"

        def _get(self, url):
            return {"ts": int(_time.time() * 1000)}

        def contexts(self):
            return {"DOGE": AssetContext("DOGE", 0.0545, 0.0545, 0.0545, 0.0, None, None)}

    api = Exchange()
    md = Md([0.0545] * 3, 0)
    broker = CoinDCXLiveBroker(api=api, md=md, costs=COINDCX_FUTURES, poll_s=0.0, fill_timeout_s=0.0,
                               specs={"DOGE": AssetSpec("DOGE", 0, 10, qty_step=1.0, min_notional=6.0,
                                                        price_step=0.00001)})
    return md, broker, api


def _typed(prompt=""):
    """What the human types: the test-order words, then the activation phrase shown on screen."""
    if "PLACE ONE TEST ORDER" in prompt:
        return "PLACE ONE TEST ORDER"
    return prompt.split("Type exactly: ")[1].split("\n")[0]


def test_smoke_test_runs_end_to_end_on_a_fake_exchange(monkeypatch, capsys):
    """Rehearsal of live-smoke-test with CoinDCX's wallet rule (margin moves into locked_balance)."""
    import sys as _sys
    md, broker, api = _fake_dcx()
    monkeypatch.setattr(rc, "_dcx_parts", lambda mandate: (md, broker))
    monkeypatch.setattr(rc, "_live_bot_running", lambda: None)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", _typed)
    mandate, _ = rc.load_mandate(rc.DOCS / "mandate_paper_coindcx_rs1000_daily.json")
    assert rc.cmd_dcx_smoke_test(mandate) is True
    out = capsys.readouterr().out
    assert "SMOKE TEST OK" in out, out
    assert "BUY 116 DOGE" in out and api.pos["B-DOGE_USDT"] == 0.0
    assert ("stop", "pos-B-DOGE_USDT", "0.05178") in api.calls          # 5% below the fill, rounded up


def test_go_live_writes_the_loss_limit_tests_activates_and_starts_in_background(tmp_path, monkeypatch, capsys):
    import subprocess
    import sys as _sys
    import requests
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("mandate_paper_coindcx_rs1000_daily.json", "mandate_paper_coindcx_rs1000_intraday.json"):
        shutil.copy(rc.DOCS / name, docs / name)
    md, broker, api = _fake_dcx()
    monkeypatch.setattr(rc, "DOCS", docs)
    monkeypatch.setattr(rc, "ROOT", tmp_path)
    monkeypatch.setattr(rc, "LIVE_LOCK", tmp_path / "coindcx-live.lock")
    monkeypatch.setattr(rc, "run_dir_for", lambda m, d: tmp_path / "run" / f"{m['mode'].lower()}-{d[:10]}")
    monkeypatch.setattr(rc, "_dcx_parts", lambda mandate: (md, broker))
    monkeypatch.setattr(requests, "get", lambda url, timeout=None: _Resp([{"symbol": "USDTINR",
                                                                             "conversion_price": 106.0}]))
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", _typed)
    started = []

    class FakePopen:     # the bot process: writes its first heartbeat like the real runner
        def __init__(self, cmd, **kw):
            started.append((cmd, kw))
            self.pid = 4242
            m, d = rc.load_mandate(Path(cmd[cmd.index("--mandate") + 1]))
            run = rc.run_dir_for(m, d)
            run.mkdir(parents=True, exist_ok=True)
            (run / "status.json").write_text(json.dumps({"after_tax_equity_inr": 998.2,
                                                         "next_decision_utc": "2026-11-25T15:00+00:00"}))

        def poll(self):
            return None
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    rc.cmd_dcx_go_live("intraday", 1000.0, 100.0)
    out = capsys.readouterr().out
    path = docs / "mandate_live_coindcx_intraday.json"
    live, digest = rc.load_mandate(path)
    assert live["mode"] == "LIVE" and live["strategy"]["kind"] == "DON"
    assert live["breakers"]["max_total_loss_inr"] == 100.0 and "max loss Rs 100" in live["label"]
    assert live["risk"]["risk_fraction"] == 0.02 and live["risk"]["min_size_max_risk"] == 0.025   # <= Rs 25 a trade
    receipt = json.loads((rc.run_dir_for(live, digest) / "activation_receipt.json").read_text())
    from compounder.coindcx_live import activation_phrase
    assert receipt["mandate_hash"] == digest and receipt["typed"] == activation_phrase(digest)
    cmd, kw = started[0]
    assert cmd[-4].endswith("run_compounder.py") and cmd[-3:] == ["live", "--mandate", str(path)]
    assert kw["start_new_session"] is True and kw["stdin"] is subprocess.DEVNULL
    assert "SMOKE TEST OK" in out and "falls to Rs 900" in out
    assert "LIVE BOT RUNNING (process 4242)" in out and "Next decision: 20:30 IST" in out
    assert "run_compounder.py watch" in out   # the human is shown how to see the trades live
    cfg = rc.build_config(live, digest)
    assert cfg.max_total_loss_inr == 100.0 and cfg.start_equity_inr == 1000.0


def test_go_live_and_smoke_test_refuse_while_a_live_bot_runs(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(rc, "_live_bot_running", lambda: {"pid": 1, "mandate": "abc"})
    with pytest.raises(SystemExit, match="refused"):
        rc.cmd_dcx_go_live("intraday", 1000.0, 100.0)
    mandate, _ = rc.load_mandate(rc.DOCS / "mandate_paper_coindcx_rs1000_daily.json")
    with pytest.raises(SystemExit, match="refused"):
        rc.cmd_dcx_smoke_test(mandate)


def test_live_lock_detects_only_a_running_live_bot(tmp_path, monkeypatch):
    import subprocess
    import types
    lock = tmp_path / "coindcx-live.lock"
    monkeypatch.setattr(rc, "LIVE_LOCK", lock)
    assert rc._live_bot_running() is None
    lock.write_text(json.dumps({"pid": 4242, "mandate": "abc"}))
    seen = {"cmd": "/x/python scripts/run_compounder.py live --mandate docs/m.json"}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=seen["cmd"]))
    assert rc._live_bot_running()["pid"] == 4242
    seen["cmd"] = "/x/python scripts/run_compounder.py live-preflight --mandate docs/m.json"
    assert rc._live_bot_running() is None
    seen["cmd"] = ""                                       # the process is gone: stale lock
    assert rc._live_bot_running() is None


def test_make_mandate_rejects_a_loss_limit_outside_the_money(tmp_path, monkeypatch):
    import requests
    for name in ("mandate_paper_coindcx_rs1000_daily.json", "mandate_paper_coindcx_rs1000_intraday.json"):
        shutil.copy(rc.DOCS / name, tmp_path / name)
    monkeypatch.setattr(rc, "DOCS", tmp_path)
    monkeypatch.setattr(requests, "get", lambda url, timeout=None: _Resp([{"symbol": "USDTINR",
                                                                             "conversion_price": 106.0}]))
    with pytest.raises(SystemExit, match="max-loss-inr"):
        rc.cmd_make_dcx_mandate("intraday", 1000.0, 1000.0)


# ---------------------------------------------------------------- go-live messages, start-up, watch (25 Nov 2026)
def _smoke_env(monkeypatch, parts):
    import sys as _sys
    monkeypatch.setattr(rc, "_dcx_parts", parts)
    monkeypatch.setattr(rc, "_live_bot_running", lambda: None)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", _typed)
    return rc.load_mandate(rc.DOCS / "mandate_paper_coindcx_rs1000_intraday.json")[0]


def test_smoke_test_network_stall_or_ctrl_c_says_nothing_was_sent(monkeypatch, capsys):
    import requests

    def stalled(mandate):
        raise requests.ConnectionError("TLS handshake stalled")
    mandate = _smoke_env(monkeypatch, stalled)
    with pytest.raises(SystemExit, match="Nothing was sent to CoinDCX and no order was placed. Wait a minute"):
        rc.cmd_dcx_smoke_test(mandate)
    assert "read-only, nothing is sent" in capsys.readouterr().out   # shown before the first call

    def interrupted(mandate):
        raise KeyboardInterrupt
    mandate = _smoke_env(monkeypatch, interrupted)
    with pytest.raises(SystemExit, match=r"Ctrl\+C during the read-only check\. Nothing was sent"):
        rc.cmd_dcx_smoke_test(mandate)


def test_smoke_test_stopped_after_the_order_closes_it_and_says_what_is_open(monkeypatch):
    from compounder.brokers import OrderRefused
    md, broker, api = _fake_dcx()

    def refuse(*a, **k):
        raise OrderRefused("STOP_NOT_ACCEPTED:DOGE")
    monkeypatch.setattr(broker, "place_stop", refuse)
    mandate = _smoke_env(monkeypatch, lambda m: (md, broker))
    with pytest.raises(SystemExit) as ex:
        rc.cmd_dcx_smoke_test(mandate)
    msg = str(ex.value)
    assert "STOP_NOT_ACCEPTED" in msg and "Checked on CoinDCX: no DOGE position is open" in msg
    assert api.pos["B-DOGE_USDT"] == 0.0          # the test position was closed

    def lost(*a, **k):                            # the close fails too: the human is told to close it
        raise OrderRefused("EXIT_NOT_CONFIRMED:DOGE")
    md, broker, api = _fake_dcx()
    monkeypatch.setattr(broker, "place_stop", refuse)
    monkeypatch.setattr(broker, "_exit", lost)
    mandate = _smoke_env(monkeypatch, lambda m: (md, broker))
    with pytest.raises(SystemExit, match="STILL OPEN on CoinDCX: close it in the CoinDCX app"):
        rc.cmd_dcx_smoke_test(mandate)


def test_usdt_inr_rate_is_retried_then_explained(monkeypatch):
    import requests
    import time
    calls = []

    def flaky(url, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("stalled")
        return _Resp([{"symbol": "USDTINR", "conversion_price": 106.0}])
    monkeypatch.setattr(requests, "get", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert rc._usdt_inr_conversion() == 106.0 and len(calls) == 2

    def down(url, timeout=None):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", down)
    with pytest.raises(SystemExit, match="Nothing was sent"):
        rc._usdt_inr_conversion()


def test_live_bot_start_survives_a_network_blip(tmp_path, monkeypatch, capsys):
    import requests
    import time
    from compounder.coindcx_live import CoinDCXLiveGate, LiveLocked
    md, broker, api = _fake_dcx()
    tries, ran = [], []

    def parts(mandate):
        tries.append(1)
        if len(tries) == 1:
            raise requests.ConnectionError("TLS handshake stalled")
        return md, broker

    class FakeRunner:
        def __init__(self, cfg, md_, broker_):
            ran.append(broker_ is broker)

        def run_forever(self):
            ran.append("ran")
    monkeypatch.setattr(CoinDCXLiveGate, "verify", lambda self: None)
    monkeypatch.setattr(rc, "_dcx_parts", parts)
    monkeypatch.setattr(rc, "_live_bot_running", lambda: None)
    monkeypatch.setattr(rc, "LIVE_LOCK", tmp_path / "coindcx-live.lock")
    monkeypatch.setattr(rc, "run_dir_for", lambda m, d: tmp_path / "run")
    monkeypatch.setattr(rc, "runner_class", lambda cfg: FakeRunner)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    mandate, digest = rc.load_mandate(rc.DOCS / "mandate_paper_coindcx_rs1000_intraday.json")
    rc.cmd_dcx_live(mandate, digest)
    assert len(tries) == 2 and ran == [True, "ran"]
    assert "trying again in 15 s" in capsys.readouterr().out

    def unknown_position(mandate):               # a real account problem is never retried
        raise LiveLocked("UNOWNED_OR_MISMATCHED_POSITION:DOGE:116")
    monkeypatch.setattr(rc, "_dcx_parts", unknown_position)
    with pytest.raises(LiveLocked):
        rc.cmd_dcx_live(mandate, digest)


def _write_watch_files(run, *, age_s=20):
    import datetime as _dt
    import time
    run.mkdir(parents=True, exist_ok=True)
    now = time.time()
    (run / "status.json").write_text(json.dumps({
        "updated_utc": _dt.datetime.fromtimestamp(now - age_s, _dt.timezone.utc).isoformat(timespec="seconds"),
        "next_decision_utc": "2026-11-25T18:00+00:00", "usd_inr": 106.0, "after_tax_equity_inr": 1004.2,
        "start_equity_inr": 1000.0, "loss_floor_inr": 900.0, "halted": None, "entries_paused_until_utc": None,
        "positions": {"TRX": {"side": "SHORT", "qty": 46.0, "entry": 0.30291, "mark": 0.3025, "stop": 0.3051,
                              "notional_usd": 13.9, "unrealized_usd": 0.01886, "funding_usd": 0.0}}}))
    t = int(now * 1000)
    events = [
        {"ts_ms": t - 9000, "kind": "ENTRY_INTENT", "coin": "TRX", "side": -1},
        {"ts_ms": t - 8000, "kind": "OPENED", "coin": "TRX", "side": -1, "qty": 46.0, "price": 0.30291,
         "stop": 0.3051, "leverage": 10, "fee": 0.007, "slippage": 0.0},
        {"ts_ms": t - 7000, "kind": "ENTRY_TOO_SMALL", "coin": "BTC", "side": -1},
        {"ts_ms": t - 6000, "kind": "BAR_PROCESSED", "signals": ["BTC", "TRX"], "positions": ["TRX"]},
        {"ts_ms": t - 5000, "kind": "FUNDING", "coin": "TRX", "amount_usd": 0.0004},
        {"ts_ms": t - 5000, "kind": "FUNDING", "coin": "SOL", "amount_usd": -0.0001},
    ]
    with open(run / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        f.write('{"ts_ms": 1, "kind": "HALF_WRIT')           # a line the bot is still writing
    closed = {"coin": "SOL", "side": "SHORT", "qty": 0.1, "entry_time": t - 7_200_000, "exit_time": t - 3_600_000,
              "entry_price": 67.77, "exit_price": 66.9, "net_usd": 0.075, "after_tax_usd": 0.0516,
              "reason": "CHANNEL"}
    (run / "trades.jsonl").write_text(json.dumps(closed) + "\n")


def test_watch_view_shows_money_trades_and_activity_in_plain_words(tmp_path):
    import time
    live = json.loads((rc.DOCS / "mandate_paper_coindcx_rs1000_intraday.json").read_text())
    live.update(mode="LIVE", label="CoinDCX | Rs 1,000 | INTRADAY | LIVE | max loss Rs 100")
    run = tmp_path / "run"
    _write_watch_files(run)
    text = rc.render_watch(run, live, time.time())
    for want in ("LIVE - REAL MONEY", "RUNNING (last report", "Next hourly check: 23:30 IST",
                 "new trades until 01:30 IST, everything closed by 05:30 IST",
                 "MONEY   Rs 1,004.20 now   (started with Rs 1,000: +Rs 4.20, +0.42%)",
                 "FLOOR   Rs 900", "(Rs 104.20 above it now)", "OPEN TRADES (1)", "AT STOP",
                 "-Rs 10.68",                                         # 46 x (0.3051 - 0.30291) x Rs 106
                 "CLOSED TRADES: 1 (1 won), total +Rs 7.95 after fees, +Rs 5.47 after tax", "trend turned",
                 "OPENED SHORT TRX: 46 at 0.30291, stop-loss 0.3051 placed on CoinDCX (10x)",
                 "Hourly check: signals on BTC, TRX; open now: TRX",
                 "Skipped BTC: CoinDCX's smallest order is too big",
                 "Funding paid/received on 2 open trade(s): +Rs 0.03"):
        assert want in text, (want, text)
    assert "ENTRY_INTENT" not in text and "HALF_WRIT" not in text

    _write_watch_files(run, age_s=600)
    assert "NOT RESPONDING: last report 10 min ago" in rc.render_watch(run, live, time.time())
    practice = rc.render_watch(run, json.loads((rc.DOCS / "mandate_paper_coindcx_rs1000_intraday.json").read_text()),
                               time.time())
    assert "PRACTICE - no real money" in practice and "(simulated)" in practice and "on CoinDCX (" not in practice


def test_watch_follows_the_running_live_bot(tmp_path, monkeypatch, capsys):
    import requests
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("mandate_paper_coindcx_rs1000_daily.json", "mandate_paper_coindcx_rs1000_intraday.json"):
        shutil.copy(rc.DOCS / name, docs / name)
    monkeypatch.setattr(rc, "DOCS", docs)
    monkeypatch.setattr(rc, "LIVE_LOCK", tmp_path / "coindcx-live.lock")
    monkeypatch.setattr(rc, "run_dir_for", lambda m, d: tmp_path / "run" / f"{m['mode'].lower()}-{d[:10]}")
    monkeypatch.setattr(requests, "get", lambda url, timeout=None: _Resp([{"symbol": "USDTINR",
                                                                             "conversion_price": 106.0}]))
    with pytest.raises(SystemExit, match="No live bot has reported yet"):
        rc._watch_target(None)
    rc.cmd_make_dcx_mandate("daily", 1000.0)
    rc.cmd_make_dcx_mandate("intraday", 1000.0, 100.0)
    m, d = rc.load_mandate(docs / "mandate_live_coindcx_intraday.json")
    (tmp_path / "coindcx-live.lock").write_text(json.dumps({"pid": 1, "mandate": d[:10]}))
    mandate, run = rc._watch_target(None)
    assert run == rc.run_dir_for(m, d) and mandate["strategy"]["kind"] == "DON"
    _write_watch_files(run)
    capsys.readouterr()
    rc.cmd_watch(None, 5.0, once=True)
    assert "OPENED SHORT TRX" in capsys.readouterr().out
