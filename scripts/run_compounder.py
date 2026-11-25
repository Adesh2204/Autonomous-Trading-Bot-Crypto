#!/usr/bin/env python3
"""Compounder CLI: 24/7 trend bot with after-cost, after-tax compounding.

  run_compounder.py board                     one table with every practice bot
  run_compounder.py watch   [--mandate FILE]   live view of the live bot's trades (read-only; Ctrl+C closes it)
  run_compounder.py paper   [--mandate FILE]   run the PAPER bot forever (Ctrl+C or `stop` to end)
  run_compounder.py status  [--mandate FILE]   print the heartbeat, open positions and trade totals
  run_compounder.py trades  [--mandate FILE]   print the closed-trade register (USD and INR)
  run_compounder.py stop | no-entries | resume-entries | flatten | reset-halt  [--mandate FILE]

LIVE (real money, Hyperliquid mainnet; every step is done by the human, in this order):
  run_compounder.py store-agent-key                      hidden prompt; saves the API-wallet key 0600
  run_compounder.py make-live-mandate --account 0x... --equity USD [--from-mandate FILE]
  run_compounder.py activate-live --mandate FILE         human types the activation phrase
  run_compounder.py live-preflight --mandate FILE        read-only account checks, no orders
  run_compounder.py live --mandate FILE                  sets cross leverage once, then trades

PAPER mode places no orders anywhere: fills are simulated against Hyperliquid's live public order
book. LIVE refuses to start unless the mandate, the typed activation receipt, the key file and the
exchange checks all agree (see docs/compounder_2026-11-25/SETUP_AND_OPERATIONS.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo-trading-bot"))

from compounder.brokers import PaperBroker  # noqa: E402
from compounder.costs import COINDCX_FUTURES, DELTA_INDIA, HYPERLIQUID, TaxPolicy  # noqa: E402
from compounder.india_venues import CoinDCXPublic, DeltaIndiaPublic  # noqa: E402
from compounder.market_data import HyperliquidPublic  # noqa: E402
from compounder.intraday import IntradayParams  # noqa: E402
from compounder.runner import IntradayRunner, Runner, RunnerConfig  # noqa: E402
from compounder.sizing import RiskParams  # noqa: E402
from compounder.strategy import TrendParams  # noqa: E402

DEFAULT_MANDATE = ROOT / "docs" / "compounder_2026-11-25" / "mandate_paper.json"
KEY_PATH = Path.home() / ".anchorium" / "compounder_agent.key"
DCX_KEY_PATH = Path.home() / ".anchorium" / "coindcx_api.json"
SMALL_RESULTS = ROOT / "research" / "compounder_2026-11-25" / "small_account_results.json"
INTRADAY_RESULTS = ROOT / "research" / "compounder_2026-11-25" / "intraday_results.json"
DOCS = ROOT / "docs" / "compounder_2026-11-25"
LIVE_LOCK = ROOT / "runtime" / "compounder" / "coindcx-live.lock"   # one live bot per CoinDCX account
RESULTS = ROOT / "research" / "compounder_2026-11-25" / "results.json"
VENUES = {"hyperliquid": HYPERLIQUID, "coindcx_futures": COINDCX_FUTURES, "delta_india": DELTA_INDIA}
DATA = {"hyperliquid": lambda universe: HyperliquidPublic(),
        "coindcx_futures": lambda universe: CoinDCXPublic(universe),
        "delta_india": lambda universe: DeltaIndiaPublic(universe)}
VENUE_NAMES = {"hyperliquid": "Hyperliquid", "coindcx_futures": "CoinDCX", "delta_india": "Delta India"}


def load_mandate(path: Path) -> tuple[dict, str]:
    raw = json.loads(path.read_text())
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return raw, digest


def run_dir_for(mandate: dict, digest: str) -> Path:
    return ROOT / "runtime" / "compounder" / f"{mandate['mode'].lower()}-{digest[:10]}"


def build_config(mandate: dict, digest: str) -> RunnerConfig:
    s = mandate["strategy"]
    tax = mandate["tax"]
    return RunnerConfig(
        run_dir=run_dir_for(mandate, digest),
        universe=tuple(mandate["universe"]),
        params=strategy_params(s),
        risk=RiskParams(**mandate["risk"]),
        costs=VENUES[mandate["venue"]],
        tax_policy=TaxPolicy(mode=tax["mode"], rate=tax.get("rate", 0.30), cess=tax.get("cess", 0.04),
                             business_rate=tax.get("business_rate", 0.30)),
        start_equity=float(mandate["start_equity_usd"]),
        mandate_hash=digest,
        daily_loss_pause=mandate["breakers"]["daily_loss_pause"],
        drawdown_halt=mandate["breakers"]["drawdown_halt"],
        label=mandate.get("label") or default_label(mandate),
        start_equity_inr=mandate.get("start_equity_inr"),
        max_total_loss_inr=mandate["breakers"].get("max_total_loss_inr"),
        **({"inr_quote_url": "https://api.coindcx.com/api/v1/derivatives/futures/data/conversions"}
           if mandate.get("margin_ccy") == "INR" else {}),
    )


def strategy_params(s: dict):
    if s.get("kind") in ("ORB", "DON"):
        return IntradayParams(**{k: v for k, v in s.items()})
    return TrendParams(s["name"], s["timeframe"], s["entry_n"], s["exit_n"], s["atr_n"], s["stop_atr"],
                       s["allow_short"])


def runner_class(cfg: RunnerConfig):
    return IntradayRunner if isinstance(cfg.params, IntradayParams) else Runner


def default_label(mandate: dict) -> str:
    rules = "long+short" if mandate["strategy"].get("allow_short", True) else "long only"
    if mandate["strategy"].get("kind"):
        rules = "INTRADAY " + rules
    money = (f"Rs {mandate['start_equity_inr']:,.0f}" if mandate.get("start_equity_inr")
             else f"${mandate['start_equity_usd']:,.0f}")
    return f"{VENUE_NAMES.get(mandate['venue'], mandate['venue'])} | {rules} | {money}"


def cmd_paper(mandate: dict, digest: str) -> None:
    if mandate["mode"] != "PAPER" or mandate.get("live_orders_allowed"):
        raise SystemExit("this command runs PAPER mandates only")
    cfg = build_config(mandate, digest)
    md = DATA[mandate["venue"]](cfg.universe)
    runner = runner_class(cfg)(cfg, md, PaperBroker(md, cfg.costs))
    print(f"PAPER compounder running ({cfg.label}). Run dir: {cfg.run_dir}", flush=True)
    print("Nothing is sent to any exchange. `run_compounder.py stop` ends the loop.", flush=True)
    runner.run_forever()


def cmd_status(mandate: dict, digest: str) -> None:
    d = run_dir_for(mandate, digest)
    path = d / "status.json"
    if not path.exists():
        raise SystemExit(f"no status yet in {d}")
    st = json.loads(path.read_text())
    print(json.dumps(st, indent=1))


def cmd_trades(mandate: dict, digest: str) -> None:
    d = run_dir_for(mandate, digest) / "trades.jsonl"
    rows = [json.loads(x) for x in d.read_text().splitlines()] if d.exists() else []
    if not rows:
        print("no closed trades yet")
        return
    tot = {"net_usd": 0.0, "tax_reserved_usd": 0.0, "after_tax_usd": 0.0, "fees_usd": 0.0, "funding_usd": 0.0}
    for r in rows:
        for k in tot:
            tot[k] += r[k]
        print(f"{r['coin']:5} {r['side']:5} net ${r['net_usd']:+.2f} tax ${r['tax_reserved_usd']:.2f} "
              f"after-tax ${r['after_tax_usd']:+.2f} ({r['reason']})"
              + (f"  INR {r['net_inr']:+.0f}" if r.get("net_inr") is not None else ""))
    print("TOTAL", {k: round(v, 2) for k, v in tot.items()}, "trades", len(rows))


def touch(mandate: dict, digest: str, name: str, *, remove: tuple = ()) -> None:
    d = run_dir_for(mandate, digest)
    d.mkdir(parents=True, exist_ok=True)
    for r in remove:
        (d / r).unlink(missing_ok=True)
    if name:
        (d / name).write_text("set by operator\n")
    print("ok:", name or "removed " + ",".join(remove), "in", d)


def cmd_reset_halt(mandate: dict, digest: str) -> None:
    d = run_dir_for(mandate, digest)
    from compounder.ledger import Journal
    j = Journal(d)
    st = j.load()
    if st is None:
        raise SystemExit("no state")
    st.halted = None
    st.peak_after_tax = 0.0
    j.save(st)
    j.event("HALT_RESET_BY_OPERATOR")
    print("halt cleared; restart the runner for it to take effect")


def cmd_store_agent_key() -> None:
    import getpass
    if not sys.stdin.isatty():
        raise SystemExit("store-agent-key must be run by a human in a terminal")
    from eth_account import Account
    raw = getpass.getpass("Paste the API wallet private key (input hidden): ").strip()
    address = Account.from_key(raw).address
    KEY_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw + "\n")
    os.chmod(KEY_PATH, 0o600)
    print(f"saved to {KEY_PATH} (0600). API wallet address: {address}")
    print("Check this address is listed under More > API on app.hyperliquid.xyz for YOUR account.")


def cmd_make_live_mandate(src: Path, account: str, equity: float) -> None:
    mandate = json.loads(src.read_text())
    if not (account.startswith("0x") and len(account) == 42):
        raise SystemExit("account must be your 0x... wallet address (42 characters)")
    mandate.update(mode="LIVE", live_orders_allowed=True, account_address=account, start_equity_usd=equity,
                   research_verdict=json.loads(RESULTS.read_text())["verdict"] + " (see research results)")
    out = ROOT / "docs" / "compounder_2026-11-25" / "mandate_live.json"
    out.write_text(json.dumps(mandate, indent=2) + "\n")
    _, digest = load_mandate(out)
    print(f"wrote {out} (hash {digest[:10]}). Next: activate-live --mandate {out}")


def cmd_activate_live(mandate: dict, digest: str) -> None:
    from compounder.hl_live import activation_phrase
    if not sys.stdin.isatty():
        raise SystemExit("activate-live must be typed by a human in a terminal")
    if mandate.get("mode") != "LIVE":
        raise SystemExit("not a LIVE mandate")
    res = json.loads(RESULTS.read_text())
    sel = res["out_of_sample"][res["selected"]]
    print("REAL MONEY ACTIVATION")
    print(f"  account {mandate['account_address']}  equity ${mandate['start_equity_usd']}")
    print(f"  strategy {mandate['strategy']['name']}  risk/trade {mandate['risk']['risk_fraction']:.2%}"
          f"  leverage setting {mandate['risk']['leverage_setting']}x cross")
    print(f"  research verdict: {res['verdict']}  (gate: {res['gate']})")
    print(f"  2024-2026 on Hyperliquid, after Indian VDA tax: {sel['hl_venue']['return_after_tax']:+.1%}"
          f", worst drawdown {sel['hl_venue']['max_dd_after_tax']:.0%}")
    print("  No profit is guaranteed. You can lose the whole account.")
    phrase = activation_phrase(mandate["account_address"])
    typed = input(f"Type exactly: {phrase}\n> ").strip()
    if typed != phrase:
        raise SystemExit("phrase did not match; nothing activated")
    d = ROOT / "runtime" / "compounder" / f"live-{digest[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "activation_receipt.json").write_text(json.dumps(
        {"mandate_hash": digest, "typed": typed, "utc": __import__("datetime").datetime.utcnow().isoformat()},
        indent=1))
    print(f"activated for mandate {digest[:10]}. Run live-preflight next.")


def _live_parts(mandate: dict, digest: str):
    from compounder.hl_live import LiveGate, build_live_broker
    if mandate.get("venue") != "hyperliquid":
        raise SystemExit("live trading is built for Hyperliquid only; CoinDCX/Delta India are practice-only for now")
    d = ROOT / "runtime" / "compounder" / f"live-{digest[:10]}"
    gate = LiveGate(mandate, digest, d / "activation_receipt.json", KEY_PATH, ROOT)
    cfg = build_config(mandate, digest)
    md = HyperliquidPublic()
    broker, agent = build_live_broker(gate, md, cfg.costs, cfg.universe)
    return cfg, md, broker, agent


def cmd_live_preflight(mandate: dict, digest: str) -> None:
    from compounder.ledger import Journal
    cfg, md, broker, agent = _live_parts(mandate, digest)
    st = Journal(cfg.run_dir).load()
    owned = {c: p["side"] * p["qty"] for c, p in (st.positions if st else {}).items()}
    stops = {int(p["stop_order_id"]) for p in (st.positions if st else {}).values() if p.get("stop_order_id")}
    print(json.dumps(broker.preflight(agent, cfg.universe, owned, stops), indent=1))
    print("preflight OK: agent approved, account funded, no unowned positions or orders")


def cmd_live(mandate: dict, digest: str) -> None:
    from compounder.ledger import Journal
    cfg, md, broker, agent = _live_parts(mandate, digest)
    st = Journal(cfg.run_dir).load()
    owned = {c: p["side"] * p["qty"] for c, p in (st.positions if st else {}).items()}
    stops = {int(p["stop_order_id"]) for p in (st.positions if st else {}).values() if p.get("stop_order_id")}
    broker.preflight(agent, cfg.universe, owned, stops)
    runner = Runner(cfg, md, broker)
    if st is None:
        lev = int(mandate["risk"]["leverage_setting"])
        for coin in cfg.universe:
            resp = broker.ex.update_leverage(lev, coin, is_cross=True)
            runner.journal.event("LEVERAGE_SET", coin=coin, leverage=lev, cross=True, response=str(resp)[:300])
    print(f"LIVE compounder running for {mandate['account_address']}. Run dir: {cfg.run_dir}", flush=True)
    runner.run_forever()


def cmd_board() -> None:
    """One table for every practice bot and the live CoinDCX bot: money now (after fees, slippage,
    funding and tax)."""
    import datetime as dt
    rows = []
    live = sorted(p for p in DOCS.glob("mandate_live*.json") if (run_dir_for(*load_mandate(p)) / "state.json").exists())
    for path in sorted(DOCS.glob("mandate_paper*.json")) + live:
        mandate, digest = load_mandate(path)
        d = run_dir_for(mandate, digest)
        st = json.loads((d / "status.json").read_text()) if (d / "status.json").exists() else {}
        age = None
        if st.get("updated_utc"):
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(st["updated_utc"])).total_seconds()
        start_usd = float(mandate["start_equity_usd"])
        now_usd = st.get("after_tax_equity_usd")
        inr = st.get("usd_inr")
        rows.append({
            "bot": mandate.get("label") or default_label(mandate),
            "now": (f"${now_usd:,.2f}" + (f" (Rs {now_usd * inr:,.0f})" if inr else "")) if now_usd is not None else "-",
            "return": f"{now_usd / start_usd - 1:+.2%}" if now_usd is not None else "-",
            "trades": str(st.get("closed_trades", "-")),
            "open": ", ".join(f"{c} {p['side']}" for c, p in (st.get("positions") or {}).items()) or "none",
            "state": ("RUNNING" if age is not None and age < 180 else "NOT RUNNING")
                     + (f", {st['halted']}" if st.get("halted") else ""),
            "file": path.name,
        })
    widths = {k: max(len(k), *(len(r[k]) for r in rows)) for k in ("bot", "now", "return", "trades", "open", "state")}
    print("  ".join(k.upper().ljust(w) for k, w in widths.items()))
    for r in rows:
        print("  ".join(r[k].ljust(w) for k, w in widths.items()))
    print("\nPRACTICE bots use no real money. A LIVE row is your real CoinDCX account. Money shown is after"
          " fees, slippage, funding and the 31.2% tax reserve.")


# ------------------------------------------------------------------ watch: a clean, read-only live view
WHY_CLOSED = {"CHANNEL": "trend turned", "END_OF_DAY": "end of day", "END_OF_DAY_LATE": "end of day",
              "STOP": "stop-loss hit", "STOP_WHILE_AWAY": "stop-loss hit", "LOSS_LIMIT": "loss limit reached",
              "NO_STOP_FLATTEN": "no stop-loss, closed for safety", "OPERATOR_FLATTEN": "closed by you"}


def _jsonl_tail(path: Path, max_bytes: int = 262_144) -> list[dict]:
    """The last rows of a .jsonl file the bot appends to; a half-written last line is skipped."""
    if not path.exists():
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        chunk = f.read().decode("utf-8", "replace")
    lines = chunk.splitlines()[1:] if size > max_bytes else chunk.splitlines()
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _event_text(e: dict, rs, live: bool = True) -> str | None:
    """One plain-English line per bot event (None: not worth showing)."""
    k = e.get("kind", "")
    coin = e.get("coin", "")
    side = "LONG" if e.get("side") in (1, "LONG") else "SHORT"
    if k == "OPENED":
        return (f"OPENED {side} {coin}: {e['qty']:g} at {e['price']:.6g}, stop-loss {e['stop']:.6g}"
                f"{' placed on CoinDCX' if live else ' (simulated)'} ({e.get('leverage', '?')}x)")
    if k == "CLOSED":
        return (f"CLOSED {e.get('side')} {coin} at {e['exit_price']:.6g}: {rs(e['net_usd'])} after fees"
                f" ({WHY_CLOSED.get(e.get('reason'), str(e.get('reason', '')).lower())})")
    if k == "BAR_PROCESSED":
        sig = e.get("signals") or []
        found = f"signals on {', '.join(sig)}" if sig else "no new signal"
        return f"Hourly check: {found}; open now: {', '.join(e.get('positions') or []) or 'none'}"
    if k == "ENTRY_TOO_SMALL":
        return f"Skipped {coin}: CoinDCX's smallest order is too big for the per-trade risk cap"
    if k == "ENTRY_SKIPPED_LOSS_LIMIT":
        return f"Skipped {coin}: it would risk more than the loss limit allows"
    if k == "ENTRY_SKIPPED":
        return f"Skipped {coin}: new trades paused ({e.get('reason')})"
    if k == "ENTRY_REFUSED":
        return f"{coin} entry not made: {str(e.get('error'))[:90]}"
    if k in ("STOP_TRIGGERED", "STOP_HIT_WHILE_AWAY"):
        return f"Stop-loss hit on {coin}"
    if k == "STOP_PLACEMENT_FAILED_FLATTENING":
        return f"{coin}: stop-loss not accepted, so the trade is being closed for safety"
    if k == "LOSS_LIMIT_REACHED":
        return "LOSS LIMIT REACHED: everything is closed and the bot stops for good"
    if k == "FUNDING":
        return f"Funding on {coin}: {rs(e.get('amount_usd', 0.0))}"
    if k == "STEP_ERROR":
        return f"Temporary problem, the bot keeps going: {str(e.get('error'))[:90]}"
    if k == "ERROR_PAUSE":
        return "Several errors in a row: no new trades for 1 hour (open trades keep their stop-loss)"
    if k == "DAILY_LOSS_PAUSE":
        return "Daily loss pause: no new trades until the next day"
    if k == "DRAWDOWN_HALT":
        return "Drawdown limit: the bot stopped opening trades"
    if k == "DATA_STALE":
        return f"Price data late for {coin}; it is checked again next hour"
    if k == "LOOP_START":
        return "Bot started"
    if k == "RESUMED":
        return "Bot restarted and picked up its saved state"
    if k == "LOOP_STOPPED_BY_OPERATOR":
        return "Bot stopped by you"
    if k in ("STARTED", "ENTRY_INTENT", "STOP_FILL_PENDING_CLEARED"):
        return None
    detail = e.get("error") or e.get("reason") or ""
    return f"{k.replace('_', ' ').capitalize()} {coin} {str(detail)[:80]}".strip()


def render_watch(run_dir: Path, mandate: dict, now_s: float) -> str:
    """The live view as text, built only from the bot's own files (status, events, trades)."""
    import datetime as _dt
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

    def clock(ms: float, fmt: str = "%H:%M") -> str:
        return _dt.datetime.fromtimestamp(ms / 1000, ist).strftime(fmt)

    path = run_dir / "status.json"
    st = json.loads(path.read_text()) if path.exists() else {}
    inr = st.get("usd_inr") or 0.0

    def rs(usd: float) -> str:
        return f"{'+' if usd >= 0 else '-'}Rs {abs(usd) * inr:,.2f}" if inr else f"{usd:+.4f} USD"

    live = mandate.get("mode") == "LIVE"
    out = [f"{'LIVE - REAL MONEY' if live else 'PRACTICE - no real money'}   "
           f"{mandate.get('label') or default_label(mandate)}",
           f"{clock(now_s * 1000, '%d %b %H:%M:%S')} IST"]
    if not st:
        out.append("\nThe bot has not reported yet (its first report comes within a minute of starting).")
        return "\n".join(out)
    age = now_s - _dt.datetime.fromisoformat(st["updated_utc"]).timestamp()
    if st.get("halted"):
        state = f"STOPPED FOR GOOD ({st['halted']})"
    elif age < 180:
        state = f"RUNNING (last report {age:.0f} s ago)"
    else:
        state = f"NOT RESPONDING: last report {age / 60:.0f} min ago (is the Mac asleep or offline?)"
    nxt = _dt.datetime.fromisoformat(st["next_decision_utc"]).timestamp() * 1000
    line = f"Bot: {state}   Next hourly check: {clock(nxt)} IST"
    if st.get("entries_paused_until_utc"):
        line += f"   New trades paused until {clock(_dt.datetime.fromisoformat(st['entries_paused_until_utc']).timestamp() * 1000)} IST"
    out.append(line)
    strat = mandate.get("strategy") or {}
    if strat.get("kind"):
        last = (strat.get("last_entry_hour", 20) * 60 + 330) % 1440
        out.append(f"Today's rules: new trades until {last // 60:02d}:{last % 60:02d} IST, everything closed by 05:30 IST."
                   + (" Every trade gets a stop-loss on CoinDCX." if live else " Stop-losses are simulated."))

    now_inr, start_inr = st.get("after_tax_equity_inr"), st.get("start_equity_inr")
    out.append("")
    if now_inr is not None and start_inr:
        diff = now_inr - start_inr
        out.append(f"MONEY   Rs {now_inr:,.2f} now   (started with Rs {start_inr:,.0f}:"
                   f" {'+' if diff >= 0 else '-'}Rs {abs(diff):,.2f}, {diff / start_inr:+.2%})")
        out.append("        after fees, funding and the 31.2% tax set aside on profits")
    floor = st.get("loss_floor_inr")
    if floor is not None and now_inr is not None:
        out.append(f"FLOOR   Rs {floor:,.0f}: at this level the bot closes everything and stops for good"
                   f" (Rs {now_inr - floor:,.2f} above it now)")

    pos = st.get("positions") or {}
    out.append("")
    out.append(f"OPEN TRADES ({len(pos)})" + ("" if pos else ": none right now"))
    if pos:
        out.append(f"  {'COIN':6}{'SIDE':7}{'QTY':>10}  {'ENTRY':>11}{'NOW':>11}{'STOP-LOSS':>11}  {'P&L NOW':>12}"
                   f"  {'AT STOP':>12}")
        for c, p in pos.items():
            sign = 1 if p["side"] == "LONG" else -1
            out.append(f"  {c:6}{p['side']:7}{p['qty']:>10g}  {p['entry']:>11.6g}{p['mark']:>11.6g}{p['stop']:>11.6g}"
                       f"  {rs(p.get('unrealized_usd', 0.0)):>12}  {rs(sign * p['qty'] * (p['stop'] - p['entry'])):>12}")
        out.append("  (P&L NOW: if closed at the current price; AT STOP: if the stop-loss is hit. Both before the closing fee"
                   " and tax)")

    trades = _jsonl_tail(run_dir / "trades.jsonl", 2_000_000)
    out.append("")
    if trades:
        wins = sum(1 for t in trades if t["net_usd"] > 0)
        total = sum(t["net_usd"] for t in trades)
        out.append(f"CLOSED TRADES: {len(trades)} ({wins} won), total {rs(total)} after fees, "
                   f"{rs(sum(t['after_tax_usd'] for t in trades))} after tax")
        out.append(f"  {'CLOSED':13}{'COIN':6}{'SIDE':7}{'QTY':>10}  {'ENTRY':>11}{'EXIT':>11}  {'RESULT':>12}  WHY")
        for t in reversed(trades[-8:]):
            out.append(f"  {clock(t['exit_time'], '%d %b %H:%M'):13}{t['coin']:6}{t['side']:7}{t['qty']:>10g}"
                       f"  {t['entry_price']:>11.6g}{t['exit_price']:>11.6g}  {rs(t['net_usd']):>12}"
                       f"  {WHY_CLOSED.get(t.get('reason'), str(t.get('reason', '')).lower())}")
    else:
        out.append("CLOSED TRADES: none yet")

    shown, funding = [], None
    for e in reversed(_jsonl_tail(run_dir / "events.jsonl")):
        when = f"  {clock(e.get('ts_ms', 0), '%d %b %H:%M:%S')}  "
        if e.get("kind") == "FUNDING":   # one line per 8-hourly funding round, not one per coin
            if funding and funding[0] == when:
                funding[1] += e.get("amount_usd", 0.0)
                funding[2] += 1
            else:
                funding = [when, e.get("amount_usd", 0.0), 1]
                shown.append(funding)
        else:
            text = _event_text(e, rs, live)
            if text:
                shown.append(when + text)
        if len(shown) == 13:
            break
    shown = [x if isinstance(x, str) else f"{x[0]}Funding paid/received on {x[2]} open trade(s): {rs(x[1])}"
             for x in shown[:12]]
    out.append("")
    out.append("LATEST ACTIVITY (newest first)")
    out.extend(shown or ["  nothing yet"])
    return "\n".join(out)


def _watch_target(mandate_path: Path | None) -> tuple[dict, Path]:
    """The bot to show: the given mandate, else the running live CoinDCX bot, else the live bot that
    reported most recently."""
    if mandate_path is not None:
        m, d = load_mandate(mandate_path)
        return m, run_dir_for(m, d)
    try:
        lock = str(json.loads(LIVE_LOCK.read_text()).get("mandate") or "")
    except (OSError, ValueError, AttributeError):
        lock = ""
    seen = []
    for p in sorted(DOCS.glob("mandate_live_coindcx_*.json")):
        m, d = load_mandate(p)
        rd = run_dir_for(m, d)
        if lock and d.startswith(lock):
            return m, rd
        if (rd / "status.json").exists():
            seen.append(((rd / "status.json").stat().st_mtime, m, rd))
    if seen:
        _, m, rd = max(seen, key=lambda s: s[0])
        return m, rd
    raise SystemExit("No live bot has reported yet: start it with go-live. To view a practice bot add"
                     " --mandate docs/compounder_2026-11-25/<its mandate file>.")


def cmd_watch(mandate_path: Path | None, every: float, once: bool) -> None:
    """Read-only: reads the bot's files every few seconds; sends nothing anywhere, needs no key."""
    import time as _time
    mandate, run_dir = _watch_target(mandate_path)
    try:
        while True:
            try:
                text = render_watch(run_dir, mandate, _time.time())
            except (OSError, ValueError, KeyError, TypeError) as exc:   # a file mid-write: next refresh
                text = f"(reading the bot's files failed for a moment: {exc}; trying again)"
            if once:
                print(text)
                return
            print("\033[2J\033[H" + text + f"\n\nUpdates every {every:g} s. Ctrl+C closes this view; the bot"
                  " keeps running.", flush=True)
            _time.sleep(every)
    except KeyboardInterrupt:
        print("\nView closed. The bot keeps running.")


# ------------------------------------------------------------------ CoinDCX live
def cmd_store_coindcx_key() -> None:
    import getpass
    if not sys.stdin.isatty():
        raise SystemExit("store-coindcx-key must be run by a human in a terminal")
    key = getpass.getpass("CoinDCX API key (input hidden): ").strip()
    secret = getpass.getpass("CoinDCX API secret (input hidden): ").strip()
    if not key or not secret:
        raise SystemExit("both key and secret are needed; nothing saved")
    DCX_KEY_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(DCX_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"key": key, "secret": secret}, f)
    os.chmod(DCX_KEY_PATH, 0o600)
    print(f"saved to {DCX_KEY_PATH} (only you can read it). Key ends with ...{key[-4:]}")


def _dcx_parts(mandate: dict):
    from compounder.coindcx_live import CoinDCXLiveBroker, check_key_file, load_api
    if mandate.get("venue") != "coindcx_futures":
        raise SystemExit("this mandate is not for CoinDCX")
    check_key_file(DCX_KEY_PATH, ROOT)
    md = CoinDCXPublic(tuple(mandate["universe"]))
    specs = md.specs()
    api = load_api(DCX_KEY_PATH)
    broker = CoinDCXLiveBroker(api=api, md=md, costs=COINDCX_FUTURES, specs=specs,
                               margin_ccy=mandate.get("margin_ccy", "INR"))
    return md, broker


def _usdt_inr_conversion(attempts: int = 3) -> float:
    """CoinDCX's USDT/INR conversion price for INR-margined futures (public, no key)."""
    import requests
    import time as _time
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            rows = requests.get("https://api.coindcx.com/api/v1/derivatives/futures/data/conversions",
                                timeout=10).json()
            return float(next(r for r in rows if r.get("symbol") == "USDTINR")["conversion_price"])
        except (requests.RequestException, ValueError, KeyError, TypeError, StopIteration) as exc:
            last = exc
            if attempt < attempts:
                _time.sleep(2 * attempt)
    raise SystemExit(_network_problem(last))


def cmd_make_dcx_mandate(strategy: str, equity_inr: float, max_loss_inr: float | None = None) -> Path:
    src = DOCS / ("mandate_paper_coindcx_rs1000_intraday.json" if strategy == "intraday"
                  else "mandate_paper_coindcx_rs1000_daily.json")
    mandate = json.loads(src.read_text())
    conv = _usdt_inr_conversion()
    mandate.update(mode="LIVE", live_orders_allowed=True, start_equity_inr=equity_inr,
                   start_equity_usd=round(equity_inr / float(conv), 4),
                   label=mandate["label"].replace("PRACTICE", "LIVE"))
    if max_loss_inr is not None:
        if not 0 < max_loss_inr < equity_inr:
            raise SystemExit("--max-loss-inr must be above 0 and below the starting money")
        mandate["breakers"]["max_total_loss_inr"] = float(max_loss_inr)
        mandate["label"] += f" | max loss Rs {max_loss_inr:,.0f}"
        # one trade may risk at most a quarter of the loss limit, so a single stop cannot use it up
        per_trade = round(max_loss_inr / equity_inr / 4, 4)
        r = mandate["risk"]
        r["risk_fraction"] = min(r["risk_fraction"], per_trade)
        if r.get("min_size_max_risk") is not None:
            r["min_size_max_risk"] = min(r["min_size_max_risk"], per_trade)
    out = DOCS / f"mandate_live_coindcx_{strategy}.json"
    out.write_text(json.dumps(mandate, indent=2) + "\n")
    _, digest = load_mandate(out)
    print(f"wrote {out} (Rs {equity_inr:,.0f} = ${mandate['start_equity_usd']} at Rs {conv}/USDT; hash {digest[:10]})")
    return out


def cmd_dcx_preflight(mandate: dict, digest: str) -> None:
    from compounder.ledger import Journal
    md, broker = _dcx_parts(mandate)
    st = Journal(run_dir_for(mandate, digest)).load()
    owned = {c: p["side"] * p["qty"] for c, p in (st.positions if st else {}).items()}
    out = broker.preflight(tuple(mandate["universe"]), owned)
    print(json.dumps(out, indent=1, default=str))
    print("PREFLIGHT OK (read-only): key works, clock in sync, futures wallet funded, nothing unexpected open.")


def _live_bot_running() -> dict | None:
    """The live CoinDCX bot recorded in LIVE_LOCK, if that process is still a run_compounder live bot."""
    import subprocess
    try:
        info = json.loads(LIVE_LOCK.read_text())
        pid = int(info["pid"])
    except (FileNotFoundError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return info   # cannot tell: assume it runs (never two live bots on one account)
    return info if ("run_compounder.py" in cmd and " live --mandate" in cmd) else None


def _refuse_if_live_bot_running(what: str) -> None:
    other = _live_bot_running()
    if other and int(other["pid"]) != os.getpid():
        raise SystemExit(f"{what} refused: the live CoinDCX bot is running (process {other['pid']}, mandate "
                         f"{other.get('mandate')}). Stop it first with: stop --mandate <its mandate file>")


NOTHING_SENT = "Nothing was sent to CoinDCX and no order was placed."


def _network_problem(exc: BaseException) -> str:
    return (f"Could not reach CoinDCX just now ({type(exc).__name__}: {str(exc)[:160]}). {NOTHING_SENT} "
            "Wait a minute, then run the same command again.")


def _smoke_stopped_message(broker, coin: str, exc: BaseException) -> str:
    """The test trade stopped after the human confirmed it: say what is left on CoinDCX (read back
    from the exchange when possible), so nothing is left open by surprise."""
    what = "Ctrl+C" if isinstance(exc, KeyboardInterrupt) else f"{type(exc).__name__}: {str(exc)[:200]}"
    try:
        held = broker.positions().get(coin)
        left = len(broker.open_orders())
    except Exception:  # noqa: BLE001 - the network may be the reason we are here
        state = (f"Could not check CoinDCX. Open the CoinDCX app > Futures > Positions and close any {coin} "
                 "position there, and cancel any open order.")
    else:
        state = (f"A {coin} test position ({held:g}) is STILL OPEN on CoinDCX: close it in the CoinDCX app > "
                 "Futures > Positions." if held else f"Checked on CoinDCX: no {coin} position is open.")
        if left:
            state += f" {left} open order(s) are left: cancel them in the CoinDCX app > Futures > Open orders."
    return f"\nThe test trade stopped early ({what}). {state} Send this output for review."


def cmd_dcx_smoke_test(mandate: dict) -> bool:
    """One minimum-size DOGE round trip with a stop-loss. It proves orders, stops and exits work and
    checks, on real CoinDCX replies, the two things the bot relies on: the wallet total while a
    position is open (balance + locked_balance) and that our fills appear in the trade history.
    Prints CoinDCX's raw replies for review; never the key or secret."""
    if not sys.stdin.isatty():
        raise SystemExit("live-smoke-test must be confirmed by a human in a terminal")
    _refuse_if_live_bot_running("live-smoke-test")   # its DOGE position would look unknown to the bot
    import math
    import requests
    from compounder.coindcx_live import LiveLocked
    from compounder.market_data import DataError
    print("Checking your CoinDCX account (read-only, nothing is sent; this can take up to a minute)...",
          flush=True)
    try:
        md, broker = _dcx_parts(mandate)
        pre = broker.preflight(tuple(mandate["universe"]), {})
        fx = broker.usd_inr()
        coin = "DOGE"
        spec = broker.specs[coin]
        ctx = md.contexts()[coin]
    except KeyboardInterrupt:
        raise SystemExit(f"\nStopped with Ctrl+C during the read-only check. {NOTHING_SENT}") from None
    except LiveLocked as exc:
        raise SystemExit(f"The CoinDCX account check did not pass: {exc}. {NOTHING_SENT}") from None
    except (requests.RequestException, DataError) as exc:
        raise SystemExit(_network_problem(exc)) from None
    qty = math.ceil((spec.min_notional * 1.05) / ctx.mark / spec.qty_step) * spec.qty_step
    print(f"Account Rs {pre['account_value_inr']}. Test: BUY {qty:g} {coin} (about ${qty * ctx.mark:.2f}) at 2x, "
          f"stop-loss 5% below, then close it at once. Expected cost: about Rs 1-3 in fees and spread.")
    if input("Type PLACE ONE TEST ORDER to continue: ").strip() != "PLACE ONE TEST ORDER":
        raise SystemExit("not confirmed; nothing sent")
    try:
        return _smoke_round_trip(broker, coin, qty, pre, fx)
    except (Exception, KeyboardInterrupt) as exc:   # never leave the human guessing what is open
        raise SystemExit(_smoke_stopped_message(broker, coin, exc)) from None


def _smoke_round_trip(broker, coin: str, qty: float, pre: dict, fx: float) -> bool:
    import time as _time

    def wallet() -> dict:
        rows = broker.api.wallets()
        return next((w for w in rows if isinstance(w, dict) and w.get("currency_short_name") == broker.ccy), {})

    problems = []
    print(f"Sending the test order (BUY {qty:g} {coin})...", flush=True)
    fill = broker.market(coin, 1, qty, reduce_only=False, reason="SMOKE_TEST", leverage=2)
    print(f"1. bought {fill.qty:g} {coin} at {fill.price}")
    try:
        stop = fill.price * 0.95
        sid = broker.place_stop(coin, 1, fill.qty, stop)
        liq_ok = broker.liquidation_ok(coin, 1, stop)
        print(f"2. stop-loss accepted (id {sid}); liquidation beyond stop: {liq_ok}")
        row = broker.position_row(coin) or {}
        keys = ("pair", "active_pos", "avg_price", "mark_price", "liquidation_price", "locked_margin",
                "leverage", "margin_type", "stop_loss_trigger", "margin_currency_short_name",
                "settlement_currency_avg_price")
        print("   position while open:", json.dumps({k: row.get(k) for k in keys}))
        w_open = wallet()
        during_inr = broker.account_value() * fx
        print("   wallet while open:", json.dumps({k: w_open.get(k) for k in
                                                   ("balance", "locked_balance", "cross_order_margin",
                                                    "cross_user_margin")}))
        print(f"   account value while open: Rs {during_inr:.2f} (balance + locked_balance + open P&L;"
              f" before the trade: Rs {pre['account_value_inr']})")
        if not liq_ok:
            problems.append("LIQUIDATION_NOT_BEYOND_STOP")
        if abs(during_inr - pre["account_value_inr"]) > 15:
            problems.append("ACCOUNT_VALUE_JUMPED_WHILE_OPEN")
    finally:
        out = broker.market(coin, -1, fill.qty, reduce_only=True, reason="SMOKE_TEST_EXIT")
        print(f"3. closed {out.qty:g} {coin} at {out.price}; open now: {broker.positions() or 'nothing'}")
    buys, sells = [], []
    for _ in range(6):   # the trade history can take a few seconds to show new fills
        buys = broker._fills_since(coin, "buy", fill.time_ms)
        sells = broker._fills_since(coin, "sell", fill.time_ms)
        if buys and sells:
            break
        _time.sleep(5)
    keys = ("side", "price", "quantity", "fee_amount", "timestamp", "settlement_currency_conversion_price")
    print("4. fills in CoinDCX trade history:", json.dumps({"buy": [{k: r.get(k) for k in keys} for r in buys],
                                                           "sell": [{k: r.get(k) for k in keys} for r in sells]}))
    after_inr = broker.account_value() * fx
    orders_left = broker.open_orders()
    w_after = wallet()
    print("5. wallet after:", json.dumps({k: w_after.get(k) for k in ("balance", "locked_balance")}),
          f"account value Rs {after_inr:.2f} (test cost Rs {pre['account_value_inr'] - after_inr:.2f});"
          f" open orders left: {len(orders_left)}")
    if not buys or not sells:
        problems.append("FILLS_NOT_FOUND_IN_TRADE_HISTORY")
    if broker.positions():
        problems.append("POSITION_STILL_OPEN")
    if orders_left:
        problems.append("ORDERS_STILL_OPEN")
    if abs(after_inr - pre["account_value_inr"]) > 15:
        problems.append("ACCOUNT_VALUE_CHANGED_MORE_THAN_RS_15")
    print("SMOKE TEST OK" if not problems else f"SMOKE TEST NEEDS A LOOK: {', '.join(problems)}")
    print("Send all of the output above for review (it contains no key or secret). "
          "Check the trade in the CoinDCX app too (Futures > Orders/Trade history).")
    return not problems


def cmd_dcx_activate(mandate: dict, digest: str, *, hint: bool = True) -> None:
    from compounder.coindcx_live import activation_phrase
    if not sys.stdin.isatty():
        raise SystemExit("activate-live must be typed by a human in a terminal")
    if mandate.get("mode") != "LIVE" or mandate.get("venue") != "coindcx_futures":
        raise SystemExit("not a LIVE CoinDCX mandate")
    intraday = bool(mandate["strategy"].get("kind"))
    if intraday:
        r = json.loads(INTRADAY_RESULTS.read_text())["rs1000"][mandate["strategy"]["name"]]
        test = f"Rs 1,000 became Rs {r['end_inr']} (2024 to Nov 2026, after costs and tax)"
    else:
        r = json.loads(SMALL_RESULTS.read_text())["coindcx"]["VDA_PER_TRADE"]
        test = (f"Rs 1,000 became Rs {r['end_inr']} (lowest Rs {r['lowest_inr']}, highest Rs {r['highest_inr']}; "
                "2024 to Nov 2026, after costs and tax)")
    print("REAL MONEY ACTIVATION - CoinDCX futures")
    print(f"  money: Rs {mandate['start_equity_inr']:,.0f}   strategy: {mandate['strategy']['name']}"
          f" ({'intraday' if intraday else 'daily'}, long and short)   leverage: up to {mandate['risk']['leverage_setting']:g}x")
    print(f"  tested result: {test}")
    floor = mandate["breakers"].get("max_total_loss_inr")
    if floor is not None:
        print(f"  loss limit: when your money (after tax) falls to Rs {mandate['start_equity_inr'] - floor:,.0f},"
              f" the bot closes every trade and stops for good. A sudden crash can slip a little past it.")
        print("  No profit is guaranteed.")
    else:
        print("  No profit is guaranteed. You can lose all of this money.")
    phrase = activation_phrase(digest)
    if input(f"Type exactly: {phrase}\n> ").strip() != phrase:
        raise SystemExit("phrase did not match; nothing activated")
    d = run_dir_for(mandate, digest)
    d.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    (d / "activation_receipt.json").write_text(json.dumps(
        {"mandate_hash": digest, "typed": phrase, "utc": _dt.datetime.now(_dt.timezone.utc).isoformat()}, indent=1))
    if hint:
        print(f"activated. Start it with: live --mandate {DOCS.name}/{Path(mandate.get('_file', 'mandate')).name}")
    else:
        print("activated.")


def cmd_dcx_go_live(strategy: str, equity_inr: float, max_loss_inr: float | None) -> None:
    """One command for the human: LIVE mandate (with the loss limit), one test trade, the typed
    activation, then the bot starts in the background and keeps running after Terminal is closed."""
    import shutil
    import subprocess
    import time as _time
    if not sys.stdin.isatty():
        raise SystemExit("go-live must be run by a human in a terminal")
    _refuse_if_live_bot_running("go-live")
    path = cmd_make_dcx_mandate(strategy, equity_inr, max_loss_inr)
    mandate, digest = load_mandate(path)
    mandate["_file"] = str(path)
    print("\n=== Step 1 of 3: one tiny test trade ===")
    if not cmd_dcx_smoke_test(mandate):
        raise SystemExit("Stopped before real trading: the test trade needs a look. Send the output above.")
    print("\n=== Step 2 of 3: switch on real trading ===")
    cmd_dcx_activate(mandate, digest, hint=False)
    print("\n=== Step 3 of 3: start the bot (runs 24/7, also after you close Terminal) ===")
    log = ROOT / "runtime" / "compounder" / "logs" / f"{path.stem}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), "live", "--mandate", str(path)]
    if shutil.which("caffeinate"):
        cmd = ["caffeinate", "-is"] + cmd   # keeps the Mac awake while plugged in
    with open(log, "ab") as out:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    status_path = run_dir_for(mandate, digest) / "status.json"
    for _ in range(60):
        if proc.poll() is not None:
            raise SystemExit(f"The bot stopped right after starting. Send the end of {log}")
        if status_path.exists():
            break
        _time.sleep(1)
    else:
        raise SystemExit(f"The bot started (process {proc.pid}) but has not reported yet. Send the end of {log}")
    st = json.loads(status_path.read_text())
    import datetime as _dt
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    nxt = _dt.datetime.fromisoformat(st["next_decision_utc"]).astimezone(ist).strftime("%H:%M IST")
    print(f"LIVE BOT RUNNING (process {proc.pid}). Money now: Rs {st.get('after_tax_equity_inr')}. "
          f"Next decision: {nxt}, then every hour.")
    print(f"Log: {log}")
    print("See your trades live (updates every few seconds; Ctrl+C closes only the view):")
    print("  .venv/bin/python scripts/run_compounder.py watch")


def cmd_dcx_live(mandate: dict, digest: str) -> None:
    from compounder.coindcx_live import CoinDCXLiveGate
    from compounder.ledger import Journal
    d = run_dir_for(mandate, digest)
    CoinDCXLiveGate(mandate, digest, d / "activation_receipt.json", DCX_KEY_PATH, ROOT).verify()
    _refuse_if_live_bot_running("live")
    LIVE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    LIVE_LOCK.write_text(json.dumps({"pid": os.getpid(), "mandate": digest[:10],
                                     "started_utc": _dt.datetime.now(_dt.timezone.utc).isoformat()}))
    import requests
    import time as _time
    from compounder.market_data import DataError
    st = Journal(d).load()
    owned = {c: p["side"] * p["qty"] for c, p in (st.positions if st else {}).items()}
    for attempt in range(1, 6):   # a network blip at start must not end the bot; LiveLocked still stops it
        try:
            md, broker = _dcx_parts(mandate)
            broker.preflight(tuple(mandate["universe"]), owned)
            break
        except (requests.RequestException, DataError) as exc:
            if attempt == 5:
                raise
            print(f"start-up check: CoinDCX not reachable ({type(exc).__name__}); trying again in 15 s",
                  flush=True)
            _time.sleep(15)
    cfg = build_config(mandate, digest)
    runner = runner_class(cfg)(cfg, md, broker)
    print(f"LIVE CoinDCX compounder running ({cfg.label}). Run dir: {cfg.run_dir}", flush=True)
    runner.run_forever()


def cmd_tax_report(mandate: dict, digest: str, fy: int | None) -> None:
    """Schedule VDA style register (INR) for one Indian financial year (April-March)."""
    import csv
    import datetime as _dt
    from compounder.costs import indian_fy
    d = run_dir_for(mandate, digest)
    rows = [json.loads(x) for x in (d / "trades.jsonl").read_text().splitlines()] if (d / "trades.jsonl").exists() else []
    if fy is None:
        now = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)
        fy = indian_fy(now)
    rows = [r for r in rows if indian_fy(int(r["exit_time"])) == fy]
    out = d / f"tax_register_FY{fy}-{str(fy + 1)[2:]}.csv"
    total = {"gain": 0.0, "tax": 0.0, "fees": 0.0, "funding": 0.0}
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["No", "Coin", "Side", "Date of acquisition (buy)", "Date of transfer (sell)",
                    "Cost of acquisition INR (buy value)", "Consideration received INR (sell value)",
                    "Income from VDA INR (sell - buy)", "Fees INR (not deductible)", "Funding INR",
                    "Tax 31.2% on positive income INR", "USD/INR used"])
        for n, r in enumerate(rows, 1):
            fx = r.get("usd_inr") or 0.0
            buy_px, sell_px = ((r["entry_price"], r["exit_price"]) if r["side"] == "LONG"
                               else (r["exit_price"], r["entry_price"]))
            buy_t, sell_t = ((r["entry_time"], r["exit_time"]) if r["side"] == "LONG"
                             else (r["exit_time"], r["entry_time"]))
            buy, sell = buy_px * r["qty"] * fx, sell_px * r["qty"] * fx
            gain = sell - buy
            tax = 0.312 * max(0.0, gain)
            day = lambda ms: _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).astimezone(
                _dt.timezone(_dt.timedelta(hours=5, minutes=30))).date().isoformat()
            w.writerow([n, r["coin"], r["side"], day(buy_t), day(sell_t), round(buy, 2), round(sell, 2),
                        round(gain, 2), round(r["fees_usd"] * fx, 2), round(r["funding_usd"] * fx, 2),
                        round(tax, 2), fx])
            total["gain"] += max(0.0, gain)
            total["tax"] += tax
            total["fees"] += r["fees_usd"] * fx
            total["funding"] += r["funding_usd"] * fx
    print(f"wrote {out}: {len(rows)} trades in FY {fy}-{str(fy + 1)[2:]}")
    print({k: round(v, 2) for k, v in total.items()}, "(INR; 'gain' = sum of profitable trades only)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["paper", "status", "trades", "stop", "no-entries", "resume-entries",
                                        "flatten", "reset-halt", "store-agent-key", "make-live-mandate",
                                        "activate-live", "live-preflight", "live", "board",
                                        "store-coindcx-key", "make-coindcx-mandate", "live-smoke-test",
                                        "tax-report", "go-live", "watch"])
    ap.add_argument("--mandate", type=Path, default=None)
    ap.add_argument("--account")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--from-mandate", type=Path, default=DEFAULT_MANDATE)
    ap.add_argument("--strategy", choices=["daily", "intraday"], default="daily")
    ap.add_argument("--equity-inr", type=float, default=1000.0)
    ap.add_argument("--max-loss-inr", type=float, help="hard total-loss limit in rupees (bot stops at start - this)")
    ap.add_argument("--fy", type=int, help="Indian financial year start, e.g. 2026 for Apr 2026-Mar 2027")
    ap.add_argument("--every", type=float, default=5.0, help="watch: seconds between updates")
    ap.add_argument("--once", action="store_true", help="watch: print the view once and exit")
    a = ap.parse_args()
    if a.command == "watch":
        return cmd_watch(a.mandate, max(1.0, a.every), a.once)
    a.mandate = a.mandate or DEFAULT_MANDATE
    if a.command == "store-coindcx-key":
        return cmd_store_coindcx_key()
    if a.command == "make-coindcx-mandate":
        cmd_make_dcx_mandate(a.strategy, a.equity_inr, a.max_loss_inr)
        return None
    if a.command == "go-live":
        return cmd_dcx_go_live(a.strategy, a.equity_inr, a.max_loss_inr)
    if a.command == "board":
        return cmd_board()
    if a.command == "store-agent-key":
        return cmd_store_agent_key()
    if a.command == "make-live-mandate":
        if not a.account or not a.equity:
            raise SystemExit("--account and --equity are required")
        return cmd_make_live_mandate(a.from_mandate, a.account, a.equity)
    mandate, digest = load_mandate(a.mandate)
    mandate["_file"] = str(a.mandate)   # for messages only; the hash is computed from the file
    dcx = mandate.get("venue") == "coindcx_futures"
    if a.command == "tax-report":
        return cmd_tax_report(mandate, digest, a.fy)
    if a.command == "live-smoke-test":
        cmd_dcx_smoke_test(mandate)
        return None
    if a.command == "activate-live":
        return cmd_dcx_activate(mandate, digest) if dcx else cmd_activate_live(mandate, digest)
    if a.command == "live-preflight":
        return cmd_dcx_preflight(mandate, digest) if dcx else cmd_live_preflight(mandate, digest)
    if a.command == "live":
        return cmd_dcx_live(mandate, digest) if dcx else cmd_live(mandate, digest)
    if a.command == "paper":
        touch(mandate, digest, "", remove=("STOP",))
        cmd_paper(mandate, digest)
    elif a.command == "status":
        cmd_status(mandate, digest)
    elif a.command == "trades":
        cmd_trades(mandate, digest)
    elif a.command == "stop":
        touch(mandate, digest, "STOP")
    elif a.command == "no-entries":
        touch(mandate, digest, "NO_ENTRIES")
    elif a.command == "resume-entries":
        touch(mandate, digest, "", remove=("NO_ENTRIES",))
    elif a.command == "flatten":
        touch(mandate, digest, "FLATTEN")
    elif a.command == "reset-halt":
        cmd_reset_halt(mandate, digest)


if __name__ == "__main__":
    main()
