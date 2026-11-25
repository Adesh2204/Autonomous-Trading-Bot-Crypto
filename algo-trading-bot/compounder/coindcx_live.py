"""LIVE broker for CoinDCX futures (INR-margined by default), built from the official API docs
(docs.coindcx.com, read 25 Nov 2026):

  signing   HMAC-SHA256(secret, json.dumps(body, separators=(',', ':'))) -> X-AUTH-SIGNATURE;
            key -> X-AUTH-APIKEY; body always carries "timestamp" (ms; >10 s old is rejected)
  orders    POST /exchange/v1/derivatives/futures/orders/create   (market_order, no time_in_force)
  stop      POST /exchange/v1/derivatives/futures/positions/create_tpsl  (stop_market only)
  exit      POST /exchange/v1/derivatives/futures/positions/exit
  reads     positions, orders, trades, wallets, conversions; limits 16/s, 960/min
  wallet    "Total wallet balance = balance + locked_balance" (docs, Wallet Transfer note): the margin of
            open isolated (INR) positions moves from ``balance`` into ``locked_balance``

Locked unless ``CoinDCXLiveGate.verify`` passes: LIVE mandate, a typed activation receipt bound to
the mandate hash, the API key file outside the repo with permissions 0600.

CoinDCX has no client order id. A lost reply is therefore never retried blindly: the broker
re-reads the position and adopts what the exchange reports, and the runner closes and halts on any
position it does not own. INR-margined positions use isolated margin, so every entry is sent with a
stop-safe leverage (runner) and the reported liquidation price is checked against the stop.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import stat
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

import requests

from .brokers import Fill, OrderRefused
from .costs import VenueCosts
from .market_data import DataError

API = "https://api.coindcx.com"
READ_ATTEMPTS = 3                                   # reads only; orders, stops and exits are sent once
READ_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class CoinDCXError(DataError):
    """Any non-200 reply. A DataError, so the runner logs it and carries on instead of stopping."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LiveLocked(RuntimeError):
    pass


def activation_phrase(mandate_hash: str) -> str:
    return f"I ACCEPT REAL LOSSES ON COINDCX {mandate_hash[:6].upper()}"


@dataclass(frozen=True)
class CoinDCXLiveGate:
    mandate: dict
    mandate_hash: str
    receipt_path: Path
    key_path: Path
    repo_root: Path

    def verify(self) -> None:
        m = self.mandate
        if m.get("mode") != "LIVE" or m.get("live_orders_allowed") is not True:
            raise LiveLocked("MANDATE_NOT_LIVE")
        if m.get("venue") != "coindcx_futures":
            raise LiveLocked("MANDATE_NOT_COINDCX")
        if not self.receipt_path.exists():
            raise LiveLocked("NO_HUMAN_ACTIVATION_RECEIPT")
        receipt = json.loads(self.receipt_path.read_text())
        if receipt.get("mandate_hash") != self.mandate_hash or receipt.get("typed") != activation_phrase(self.mandate_hash):
            raise LiveLocked("ACTIVATION_RECEIPT_DOES_NOT_MATCH_MANDATE")
        check_key_file(self.key_path, self.repo_root)


def check_key_file(key_path: Path, repo_root: Path) -> None:
    key = key_path.resolve()
    if repo_root.resolve() in key.parents:
        raise LiveLocked("API_KEY_INSIDE_REPOSITORY")
    if not key.exists():
        raise LiveLocked("API_KEY_FILE_MISSING")
    if stat.S_IMODE(key.stat().st_mode) & 0o077:
        raise LiveLocked("API_KEY_FILE_PERMISSIONS_MUST_BE_0600")
    data = json.loads(key.read_text())
    if not data.get("key") or not data.get("secret"):
        raise LiveLocked("API_KEY_FILE_INCOMPLETE")


class CoinDCXPrivate:
    def __init__(self, key: str, secret: str, *, session=None, clock=time.time, timeout: float = 10.0,
                 min_interval_s: float = 0.08, sleep=time.sleep, read_retry_pause_s: float = 1.0):
        self._key = key
        self._secret = secret.encode()
        self.session = session or requests.Session()
        self.clock = clock
        self.timeout = timeout
        self.min_interval_s = min_interval_s      # 12.5 calls/s max, under the 16/s limit
        self.sleep = sleep
        self.read_retry_pause_s = read_retry_pause_s
        self._last = 0.0

    def __repr__(self) -> str:  # never show credentials
        return "CoinDCXPrivate(<credentials hidden>)"

    def _call(self, method: str, path: str, body: dict | None = None):
        wait = self.min_interval_s - (time.monotonic() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()
        payload_obj = {**(body or {}), "timestamp": int(self.clock() * 1000)}
        payload = json.dumps(payload_obj, separators=(",", ":"))
        sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-AUTH-APIKEY": self._key, "X-AUTH-SIGNATURE": sig}
        r = self.session.request(method, API + path, data=payload, headers=headers, timeout=self.timeout)
        if r.status_code != 200:
            raise CoinDCXError(f"HTTP_{r.status_code}:{path}:{r.text[:300]}", status=r.status_code)
        return r.json()

    def _with_read_retries(self, fn):
        """Reads only: a network error, timeout, rate limit (429) or server error (5xx) is tried again
        (READ_ATTEMPTS in all, short pauses). Safe because a read changes nothing, and every try is
        signed afresh. Orders, stops and exits never come through here: a lost order reply is looked
        up on the exchange (CoinDCXLiveBroker.market), never resent."""
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                return fn()
            except (requests.ConnectionError, requests.Timeout):
                if attempt == READ_ATTEMPTS:
                    raise
            except CoinDCXError as exc:
                if exc.status not in READ_RETRY_STATUS or attempt == READ_ATTEMPTS:
                    raise
            self.sleep(self.read_retry_pause_s * attempt)
        raise AssertionError("unreachable")

    def _read(self, method: str, path: str, body: dict | None = None):
        return self._with_read_retries(lambda: self._call(method, path, body))

    # ---------------------------------------------------------------- reads
    def wallets(self):
        return self._read("GET", "/exchange/v1/derivatives/futures/wallets")

    def cross_margin_details(self):
        return self._read("GET", "/exchange/v1/derivatives/futures/positions/cross_margin_details")

    def positions(self, ccy: str):
        return self._read("POST", "/exchange/v1/derivatives/futures/positions",
                          {"page": "1", "size": "100", "margin_currency_short_name": [ccy]})

    def orders(self, status: str, side: str, ccy: str):
        return self._read("POST", "/exchange/v1/derivatives/futures/orders",
                          {"status": status, "side": side, "page": "1", "size": "100",
                           "margin_currency_short_name": [ccy]})

    def trades(self, pair: str, from_date: str, to_date: str, ccy: str):
        return self._read("POST", "/exchange/v1/derivatives/futures/trades",
                          {"pair": pair, "from_date": from_date, "to_date": to_date, "page": "1", "size": "100",
                           "margin_currency_short_name": [ccy]})

    def transactions(self, stage: str, ccy: str):
        return self._read("POST", "/exchange/v1/derivatives/futures/positions/transactions",
                          {"stage": stage, "page": "1", "size": "100", "margin_currency_short_name": [ccy]})

    def conversion_price(self) -> float:
        def get():
            r = self.session.get(f"{API}/api/v1/derivatives/futures/data/conversions", timeout=self.timeout)
            if r.status_code != 200:
                raise CoinDCXError(f"HTTP_{r.status_code}:conversions", status=r.status_code)
            return r.json()
        for row in self._with_read_retries(get):
            if row.get("symbol") == "USDTINR":
                return float(row["conversion_price"])
        raise CoinDCXError("NO_USDTINR_CONVERSION")

    # ---------------------------------------------------------------- writes
    def update_leverage(self, pair: str, leverage: int, ccy: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/positions/update_leverage",
                          {"leverage": str(int(leverage)), "pair": pair, "margin_currency_short_name": ccy})

    def create_market_order(self, pair: str, side: str, qty: float, leverage: int, ccy: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/orders/create",
                          {"order": {"side": side, "pair": pair, "order_type": "market_order", "price": None,
                                     "total_quantity": qty, "leverage": int(leverage),
                                     "notification": "no_notification", "margin_currency_short_name": ccy}})

    def create_stop_loss(self, position_id: str, stop_price: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/positions/create_tpsl",
                          {"id": position_id, "stop_loss": {"stop_price": stop_price, "order_type": "stop_market"}})

    def cancel_order(self, order_id: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/orders/cancel", {"id": order_id})

    def exit_position(self, position_id: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/positions/exit", {"id": position_id})

    def cancel_all_for_position(self, position_id: str):
        return self._call("POST", "/exchange/v1/derivatives/futures/positions/cancel_all_open_orders_for_position",
                          {"id": position_id})


def _step_round(x: float, step: float, *, up: bool) -> float:
    s = Decimal(repr(float(step)))
    q = (Decimal(repr(float(x))) / s).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR) * s
    return float(q)


def _fmt(x: float, step: float) -> str:
    places = max(0, -Decimal(repr(float(step))).normalize().as_tuple().exponent)
    return f"{x:.{places}f}"


class CoinDCXLiveBroker:
    """PaperBroker interface plus account truth. Quantities in coins, prices in USDT."""
    mode = "LIVE"

    def __init__(self, *, api: CoinDCXPrivate, md, costs: VenueCosts, specs: dict, margin_ccy: str = "INR",
                 fill_timeout_s: float = 20.0, poll_s: float = 1.0, clock=time.time, sleep=time.sleep):
        self.api = api
        self.md = md
        self.costs = costs
        self.specs = specs
        self.ccy = margin_ccy
        self.fill_timeout_s = fill_timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.sleep = sleep
        self._fx: tuple[float, float] = (0.0, 0.0)

    @staticmethod
    def pair(coin: str) -> str:
        return f"B-{coin}_USDT"

    @staticmethod
    def coin_of(pair: str) -> str:
        return pair[2:].split("_")[0]

    def _now(self) -> int:
        return int(self.clock() * 1000)

    def usd_inr(self) -> float:
        ts, px = self._fx
        if px and self.clock() - ts < 600:
            return px
        px = self.api.conversion_price()
        self._fx = (self.clock(), px)
        return px

    # ---------------------------------------------------------------- account truth
    def _positions_raw(self) -> list:
        rows = self.api.positions(self.ccy)
        if not isinstance(rows, list):
            raise CoinDCXError(f"POSITIONS_UNREADABLE:{str(rows)[:200]}")
        return rows

    def positions(self) -> dict:
        return {self.coin_of(p["pair"]): float(p["active_pos"]) for p in self._positions_raw()
                if float(p.get("active_pos") or 0) != 0}

    def position_row(self, coin: str) -> dict | None:
        for p in self._positions_raw():
            if p.get("pair") == self.pair(coin):
                return p
        return None

    def wallet_total(self) -> float:
        """Margin-currency futures wallet in its own currency: balance + locked_balance. While a
        position is open its margin sits in locked_balance; ``balance`` alone would look like a loss."""
        rows = self.api.wallets()
        wallet = next((w for w in (rows if isinstance(rows, list) else [])
                       if isinstance(w, dict) and w.get("currency_short_name") == self.ccy), None)
        if wallet is None:
            raise CoinDCXError(f"NO_{self.ccy}_FUTURES_WALLET:{str(rows)[:200]}")
        return float(wallet["balance"]) + float(wallet.get("locked_balance") or 0.0)

    def account_value(self) -> float:
        """Futures account value in USD: margin-currency wallet total + unrealized P&L, converted at
        the INR-margin conversion price for INR margin."""
        balance = self.wallet_total()
        upnl_usdt = 0.0
        for p in self._positions_raw():
            q = float(p.get("active_pos") or 0)
            if q:
                upnl_usdt += q * (float(p["mark_price"]) - float(p["avg_price"]))
        if self.ccy == "INR":
            return balance / self.usd_inr() + upnl_usdt
        return balance + upnl_usdt

    def open_orders(self) -> list:
        out = []
        for side in ("buy", "sell"):
            rows = self.api.orders("open,partially_filled,untriggered", side, self.ccy)
            out.extend(rows if isinstance(rows, list) else [])
        return out

    def preflight(self, universe: tuple, owned_positions: dict) -> dict:
        """Read-only checks before trading. Raises LiveLocked on anything unexpected."""
        local = self._now()
        server = int(self.md._get(f"{self.md.PUB}/market_data/v3/current_prices/futures/rt").get("ts", 0))
        skew = abs(local - server)
        if skew > 3000:
            raise LiveLocked(f"CLOCK_SKEW_MS:{skew}")
        wallets = self.api.wallets()
        value = self.account_value()
        if value * self.usd_inr() < 100:   # less than Rs 100 in the futures wallet
            raise LiveLocked(f"FUTURES_WALLET_NOT_FUNDED:{value:.4f}USD")
        pos = self.positions()
        for coin, q in pos.items():
            if abs(owned_positions.get(coin, 0.0) - q) > 1e-9:
                raise LiveLocked(f"UNOWNED_OR_MISMATCHED_POSITION:{coin}:{q}")
        orders = self.open_orders()
        owned_coins = set(owned_positions)
        stray = [o for o in orders if self.coin_of(o.get("pair", "B-?_")) not in owned_coins]
        if stray:
            raise LiveLocked(f"UNOWNED_OPEN_ORDERS:{[o.get('pair') for o in stray]}")
        return {"account_value_usd": round(value, 4), "account_value_inr": round(value * self.usd_inr(), 2),
                "usd_inr_conversion": self.usd_inr(), "clock_skew_ms": skew, "positions": pos,
                "open_orders": len(orders), "wallets_raw": wallets}

    # ---------------------------------------------------------------- orders
    def _wait_position(self, coin: str, want: float, *, timeout: float | None = None) -> dict | None:
        """Poll until active_pos reaches ``want`` (0 for an exit). Returns the last row read."""
        deadline = self.clock() + (timeout or self.fill_timeout_s)
        row = None
        while True:
            row = self.position_row(coin)
            q = float((row or {}).get("active_pos") or 0)
            if (want == 0 and q == 0) or (want != 0 and q != 0 and abs(q) >= abs(want) * 0.999):
                return row
            if self.clock() >= deadline:
                return row
            self.sleep(self.poll_s)

    def _fills_since(self, coin: str, side: str, since_ms: int) -> list:
        """Our fills on one side since ``since_ms``. The docs do not say whether to_date is inclusive or
        which time zone the dates use, so the window starts a day early and ends a day after today in
        India (covers UTC/IST, inclusive/exclusive); the exact cut is the fill timestamp. A refused
        future end date falls back to today's date."""
        ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
        start = (dt.datetime.fromtimestamp(since_ms / 1000, dt.timezone.utc) - dt.timedelta(days=1)).date()
        today_ist = dt.datetime.fromtimestamp(self.clock(), ist).date()
        rows = None
        for end in (today_ist + dt.timedelta(days=1), today_ist):
            try:
                rows = self.api.trades(self.pair(coin), start.isoformat(), end.isoformat(), self.ccy)
            except CoinDCXError:
                rows = None
            if isinstance(rows, list):
                break
        if not isinstance(rows, list):
            raise CoinDCXError(f"TRADES_UNREADABLE:{coin}:{str(rows)[:200]}")
        return [r for r in rows if r.get("side") == side and float(r.get("timestamp", 0)) >= since_ms - 2000]

    def market(self, coin: str, side: int, qty: float, *, reduce_only: bool, reason: str,
               leverage: int | None = None) -> Fill:
        bids, asks, _ = self.md.book(coin)
        mid = (bids[0][0] + asks[0][0]) / 2
        if reduce_only:
            return self._exit(coin, side, qty, mid, reason)
        row = self.position_row(coin)
        if row is not None and (float(row.get("active_pos") or 0) != 0 or float(row.get("inactive_pos_buy") or 0)
                                or float(row.get("inactive_pos_sell") or 0)):
            raise OrderRefused(f"NOT_FLAT_BEFORE_ENTRY:{coin}")
        step = self.specs[coin].qty_step or 1.0
        qty = _step_round(qty, step, up=False)
        if qty <= 0:
            raise OrderRefused(f"QTY_BELOW_STEP:{coin}")
        lev = int(leverage or 1)
        self.api.update_leverage(self.pair(coin), lev, self.ccy)
        sent = self._now()
        try:
            self.api.create_market_order(self.pair(coin), "buy" if side > 0 else "sell", qty, lev, self.ccy)
        except (requests.RequestException, CoinDCXError) as exc:
            # A lost reply may still have filled: look before deciding (never resend blindly).
            row = self._wait_position(coin, side * qty, timeout=self.fill_timeout_s)
            if not row or float(row.get("active_pos") or 0) == 0:
                raise OrderRefused(f"ENTRY_NOT_PLACED:{coin}:{exc}") from exc
        else:
            row = self._wait_position(coin, side * qty)
        filled = float((row or {}).get("active_pos") or 0)
        if filled == 0:
            raise OrderRefused(f"ENTRY_NOT_FILLED_IN_TIME:{coin}")
        if filled * side < 0:
            raise OrderRefused(f"ENTRY_WRONG_SIDE:{coin}:{filled}")
        price = float(row["avg_price"])
        fee = self.costs.fee(abs(filled) * price)
        return Fill(coin, side, abs(filled), price, fee, mid, sent, reason)

    def _exit(self, coin: str, side: int, qty: float, mid: float, reason: str) -> Fill:
        row = self.position_row(coin)
        if row is None or float(row.get("active_pos") or 0) == 0:
            raise OrderRefused(f"ALREADY_FLAT:{coin}")
        sent = self._now()
        self.api.exit_position(row["id"])
        row = self._wait_position(coin, 0)
        if row is not None and float(row.get("active_pos") or 0) != 0:
            raise OrderRefused(f"EXIT_NOT_CONFIRMED:{coin}")
        try:
            self.api.cancel_all_for_position(row["id"] if row else "")
        except (requests.RequestException, CoinDCXError):
            pass   # the stop belongs to a closed position; it cannot open anything
        try:   # the position is flat now: never fail after this point, only the price record may be estimated
            fills = self._fills_since(coin, "buy" if side > 0 else "sell", sent)
        except (requests.RequestException, CoinDCXError):
            fills = []
        if fills:
            sz = sum(float(f["quantity"]) for f in fills)
            px = sum(float(f["price"]) * float(f["quantity"]) for f in fills) / sz
        else:
            sz, px = qty, mid
        return Fill(coin, side, sz, px, self.costs.fee(sz * px), mid, sent, reason)

    def place_stop(self, coin: str, pos_side: int, qty: float, trigger: float) -> str:
        row = self.position_row(coin)
        if row is None or float(row.get("active_pos") or 0) == 0:
            raise OrderRefused(f"NO_POSITION_FOR_STOP:{coin}")
        tick = self.specs[coin].price_step or 0.0001
        # round toward the entry so the risk never exceeds the plan
        px = _step_round(trigger, tick, up=pos_side > 0)
        resp = self.api.create_stop_loss(row["id"], _fmt(px, tick))
        sl = (resp or {}).get("stop_loss") if isinstance(resp, dict) else None
        if not sl or not sl.get("id") or sl.get("success") is False:
            raise OrderRefused(f"STOP_NOT_ACCEPTED:{coin}:{str(resp)[:300]}")
        return str(sl["id"])

    def liquidation_ok(self, coin: str, pos_side: int, stop: float) -> bool:
        row = self.position_row(coin)
        liq = float((row or {}).get("liquidation_price") or 0)
        if liq <= 0:
            return True   # no liquidation price reported (fully margined)
        return liq < stop * 0.995 if pos_side > 0 else liq > stop * 1.005

    def cancel_stop(self, coin: str, order_id: str | None) -> None:
        if order_id:
            try:
                self.api.cancel_order(order_id)
            except CoinDCXError:
                pass   # already triggered/cancelled; the exit path re-reads the position

    def stop_triggered(self, coin: str, pos_side: int, stop: float, contexts: dict) -> bool:
        return coin not in self.positions()

    def exit_fill_after_stop(self, coin: str, pos_side: int, qty: float, since_ms: int) -> Fill:
        fills = self._fills_since(coin, "sell" if pos_side > 0 else "buy", since_ms)
        if not fills:
            raise DataError(f"STOP_FILL_NOT_INDEXED:{coin}")
        sz = sum(float(f["quantity"]) for f in fills)
        px = sum(float(f["price"]) * float(f["quantity"]) for f in fills) / sz
        fee = sum(float(f.get("fee_amount") or 0) for f in fills) or self.costs.fee(sz * px)
        return Fill(coin, -pos_side, sz, px, fee, px, int(max(float(f["timestamp"]) for f in fills)), "STOP")

    def funding(self, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return self.md.funding_history(coin, start_ms, end_ms)


def load_api(key_path: Path, **kw) -> CoinDCXPrivate:
    data = json.loads(key_path.read_text())
    return CoinDCXPrivate(data["key"], data["secret"], **kw)
