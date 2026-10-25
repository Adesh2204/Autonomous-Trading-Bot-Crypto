// node research/test_fee_aware_backtest.js  -- unit checks of the fill and cost model
require('./fee_aware_backtest.js');
const assert = require('assert');
const F = globalThis.FAB;
const cfg = Object.assign({}, F.SPEC, { warmup: 60, atrFloor: 0 });

// A steady uptrend so EMA20 > EMA50, ATR fixed by a constant 1.0 range around each close.
function trend(n, start = 100, step = 0.05) {
  const bars = [];
  for (let i = 0; i < n; i++) { const c = start + step * i; bars.push({ t: i * 3600e3, o: c - step, h: c + 0.5, l: c - 0.5, c }); }
  return bars;
}
function firstOrder(bars) { const r = F.simulate('X', bars, [], cfg); return { r, o: r.orders.find(o => !o.rejectedAlo) }; }

// 1) touch is not a fill, trade-through is
{
  const bars = trend(80);
  const { o } = firstOrder(bars);
  assert(o, 'an order is placed in an uptrend');
  const i = bars.findIndex(b => b.t === o.t) + 1;
  const touch = bars.map(b => ({ ...b })); for (let k = i; k < i + 2; k++) touch[k].l = o.px;     // exactly touches
  const rt = F.simulate('X', touch.slice(0, i + 2), [], cfg);
  assert.strictEqual(rt.orders.find(x => x.t === o.t).filled, false, 'touch must not fill');
  const through = bars.map(b => ({ ...b })); through[i].l = o.px - 1e-6;
  const rf = F.simulate('X', through.slice(0, i + 1), [], cfg);
  assert.strictEqual(rf.orders.find(x => x.t === o.t).filled, true, 'trade-through fills');
}

// 2) target touch is not an exit; stop before target in the same bar; fee accounting
{
  const bars = trend(80);
  const { o } = firstOrder(bars);
  const i = bars.findIndex(b => b.t === o.t) + 1;
  const A = F.atr(bars, 14)[i - 1];
  const tp = o.px + 1.5 * A, sl = o.px - 1.0 * A;
  const mk = () => { const b = bars.slice(0, i + 3).map(x => ({ ...x })); b[i] = { ...b[i], l: o.px - 1e-6, h: o.px + 0.1 };
                     for (let k = i + 1; k < b.length; k++) b[k] = { ...b[k], o: o.px, l: o.px - 0.1, h: o.px + 0.1, c: o.px }; return b; };
  const t1 = mk(); t1[i + 1].h = tp;                          // touches target only
  assert(!F.simulate('X', t1, [], cfg).trades.some(t => t.kind === 'TP'), 'target touch is not a fill');
  const t2 = mk(); t2[i + 1].h = tp + 1e-6;                   // through target
  const tr = F.simulate('X', t2, [], cfg).trades[0];
  assert.strictEqual(tr.kind, 'TP');
  assert(Math.abs(tr.net - ((tp - o.px) / o.px - 0.0006)) < 1e-12, 'TP net = gross - 0.06%');
  const t3 = mk(); t3[i + 1].h = tp + 1; t3[i + 1].l = sl - 1;   // both in one bar -> stop
  const ts = F.simulate('X', t3, [], cfg).trades[0];
  assert.strictEqual(ts.kind, 'STOP');
  const expected = (sl * (1 - cfg.stopSlip) - o.px) / o.px - 0.0012;
  assert(Math.abs(ts.net - expected) < 1e-12, 'stop net = gross with slippage - 0.12%');
}

// 3) cost filter blocks low-ATR markets
{
  const narrow = trend(80).map(b => ({ ...b, h: b.c + 0.1, l: b.c - 0.1 }));     // ~0.2% ATR
  const spec = Object.assign({}, cfg, { atrFloor: null });
  assert.strictEqual(F.simulate('X', narrow, [], spec).orders.length, 0, '0.2% ATR is below 3 x 0.1655%');
  assert(F.simulate('X', trend(80), [], spec).orders.length > 0, '~1% ATR passes the filter');
}
console.log('fee_aware_backtest: all checks passed');
