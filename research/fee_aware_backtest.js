// Fee-aware 1h trend-pullback backtest (Phase 2 research only; never imported by the bot).
//
// Runs in a browser page on api.hyperliquid*.xyz so the candles never leave the Mac:
//   paste this file into the page console (or the Claude browser tool), then
//   await FAB.run({markets: [...], cfg: FAB.SPEC})
//
// Spec (fixed before any data was looked at; nothing below is tuned):
//   trend  : 1h EMA20 vs EMA50, trade only in the trend direction
//   entry  : post-only limit at EMA20 -/+ 0.25*ATR(14, 1h); rejected if it would cross at placement;
//            cancelled if unfilled after 2 bars
//   exits  : SL 1.0*ATR (taker + measured stop slippage), TP 1.5*ATR (resting maker),
//            after +1.0*ATR move SL to entry +/- 0.12%, max hold 12 bars (taker at close + slippage)
//   filter : ATR(1h)% >= 3 * loss cost, loss cost = 0.03% + 0.09% + measured stop slippage
//   fills  : a resting limit fills ONLY if price trades THROUGH it (low < bid, high > ask), never on a touch
//   bar order (conservative): stop before target inside one bar; on the fill bar only the stop is checked;
//            a stop move takes effect from the next bar
//   split  : one common time cut at 70% of the window; trades are assigned by fill time
(function (root) {
  const SPEC = {
    maker: 0.0003, taker: 0.0009, stopSlip: 0.000455,   // measured on our 4 stop fills, 25 Oct
    emaFast: 20, emaSlow: 50, atrLen: 14, entryAtr: 0.25, slAtr: 1.0, tpAtr: 1.5,
    beTriggerAtr: 1.0, beOffset: 0.0012, maxHold: 12, orderLife: 2, costMultiple: 3,
    atrFloor: null,               // null = 3 * loss cost; a number overrides (sensitivity only)
    optimistic: false,            // diagnostic bound only: touch fills, target before stop, target on the fill bar
    riskFrac: 0.003, maxNotional: 5000, equity: 100000, maxPositions: 2, split: 0.7, warmup: 60,
  };

  function ema(xs, n) {
    const k = 2 / (n + 1), out = new Array(xs.length).fill(null);
    let s = 0;
    for (let i = 0; i < xs.length; i++) {
      if (i < n) { s += xs[i]; if (i === n - 1) out[i] = s / n; continue; }
      out[i] = xs[i] * k + out[i - 1] * (1 - k);
    }
    return out;
  }
  function atr(bars, n) {
    const out = new Array(bars.length).fill(null);
    let a = null, s = 0;
    for (let i = 1; i < bars.length; i++) {
      const b = bars[i], pc = bars[i - 1].c;
      const tr = Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc));
      if (i <= n) { s += tr; if (i === n) { a = s / n; out[i] = a; } continue; }
      a = (a * (n - 1) + tr) / n; out[i] = a;
    }
    return out;
  }
  function fundingAt(funding, t) {           // hourly funding rate in force at time t (positive: longs pay)
    if (!funding || !funding.length) return 0;
    let lo = 0, hi = funding.length - 1;
    if (t < funding[0].t) return 0;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (funding[m].t <= t) lo = m; else hi = m - 1; }
    return funding[lo].r;
  }

  // One market, independent of the others; returns orders and trades.
  function simulate(symbol, bars, funding, cfg) {
    const closes = bars.map(b => b.c);
    const e20 = ema(closes, cfg.emaFast), e50 = ema(closes, cfg.emaSlow), A = atr(bars, cfg.atrLen);
    const lossCost = cfg.maker + cfg.taker + cfg.stopSlip;
    const floor = cfg.atrFloor != null ? cfg.atrFloor : cfg.costMultiple * lossCost;
    const orders = [], trades = [];
    let order = null, pos = null;
    for (let i = cfg.warmup; i < bars.length; i++) {
      const b = bars[i];
      // 1) manage an open position on this bar
      if (pos && i > pos.fillBar) {
        const d = pos.dir;
        let exit = null, kind = null;
        const stopHit = d > 0 ? b.l <= pos.sl : b.h >= pos.sl;
        const gap = d > 0 ? b.o <= pos.sl : b.o >= pos.sl;
        const tpHit = cfg.optimistic ? (d > 0 ? b.h >= pos.tp : b.l <= pos.tp) : (d > 0 ? b.h > pos.tp : b.l < pos.tp);
        if (cfg.optimistic && tpHit && !gap) { exit = pos.tp; kind = 'TP'; }
        else if (stopHit) { const ref = gap ? b.o : pos.sl; exit = ref * (1 - d * cfg.stopSlip); kind = pos.be ? 'BE_STOP' : 'STOP'; }
        else if (tpHit) { exit = pos.tp; kind = 'TP'; }
        else if (i - pos.fillBar >= cfg.maxHold) { exit = b.c * (1 - d * cfg.stopSlip); kind = 'TIME'; }
        // funding for every hour held, charged at each bar the position is open
        pos.funding += -d * fundingAt(funding, b.t);
        if (exit != null) {
          const gross = d * (exit - pos.entry) / pos.entry;
          const fees = cfg.maker + (kind === 'TP' ? cfg.maker : cfg.taker);
          trades.push({ symbol, dir: d, fillT: bars[pos.fillBar].t, exitT: b.t, entry: pos.entry, exit, kind,
                        atrPct: pos.atrPct, gross, fees, funding: pos.funding, net: gross - fees + pos.funding,
                        bars: i - pos.fillBar });
          pos = null;
        } else if (!pos.be && (d > 0 ? b.h >= pos.entry + cfg.beTriggerAtr * pos.atr : b.l <= pos.entry - cfg.beTriggerAtr * pos.atr)) {
          pos.be = true; pos.sl = pos.entry * (1 + d * cfg.beOffset);       // effective from the next bar
        }
        // flat after this bar's exit: a new order may be placed at this bar's close (step 3)
      }
      // 2) a resting entry order
      if (order && !pos) {
        if (i > order.placed && i <= order.placed + cfg.orderLife) {
          const filled = cfg.optimistic ? (order.dir > 0 ? b.l <= order.px : b.h >= order.px)
                                        : (order.dir > 0 ? b.l < order.px : b.h > order.px);
          if (filled) {
            order.filled = true;
            pos = { dir: order.dir, entry: order.px, atr: order.atr, atrPct: order.atr / order.px,
                    sl: order.px - order.dir * cfg.slAtr * order.atr, tp: order.px + order.dir * cfg.tpAtr * order.atr,
                    fillBar: i, be: false, funding: 0 };
            order = null;
            // fill bar: only the stop is checked (unknown order inside the bar -> assume the worst)
            const d = pos.dir;
            if (cfg.optimistic && (d > 0 ? b.h >= pos.tp : b.l <= pos.tp)) {
              const gross = d * (pos.tp - pos.entry) / pos.entry, fees = 2 * cfg.maker;
              trades.push({ symbol, dir: d, fillT: b.t, exitT: b.t, entry: pos.entry, exit: pos.tp, kind: 'TP_FILL_BAR',
                            atrPct: pos.atrPct, gross, fees, funding: 0, net: gross - fees, bars: 0 });
              pos = null;
            } else if (d > 0 ? b.l <= pos.sl : b.h >= pos.sl) {
              const exit = pos.sl * (1 - d * cfg.stopSlip), gross = d * (exit - pos.entry) / pos.entry, fees = cfg.maker + cfg.taker;
              trades.push({ symbol, dir: d, fillT: b.t, exitT: b.t, entry: pos.entry, exit, kind: 'STOP_FILL_BAR',
                            atrPct: pos.atrPct, gross, fees, funding: 0, net: gross - fees, bars: 0 });
              pos = null;
            }
            continue;
          }
        }
        if (order && i >= order.placed + cfg.orderLife) order = null;      // unfilled after 2 bars: cancelled
        if (order) continue;
      }
      // 3) at this bar's close, maybe place a new post-only entry
      if (!pos && !order && e20[i] != null && e50[i] != null && A[i] != null) {
        const dir = e20[i] > e50[i] ? 1 : e20[i] < e50[i] ? -1 : 0;
        const atrPct = A[i] / b.c;
        if (!dir || atrPct < floor) continue;
        const px = e20[i] - dir * cfg.entryAtr * A[i];
        const wouldCross = dir > 0 ? px >= b.c : px <= b.c;              // ALO rejects a crossing order
        orders.push({ symbol, t: b.t, dir, px, atrPct, rejectedAlo: wouldCross });
        if (wouldCross) continue;
        order = { dir, px, atr: A[i], placed: i, filled: false };
        orders[orders.length - 1].ref = order;
      }
    }
    for (const o of orders) { o.filled = !!(o.ref && o.ref.filled); delete o.ref; }
    return { orders, trades, floor };
  }

  function stats(trades, orders, cfg) {
    const n = trades.length, wins = trades.filter(t => t.net > 0);
    const gp = wins.reduce((s, t) => s + t.net, 0), gl = -trades.filter(t => t.net <= 0).reduce((s, t) => s + t.net, 0);
    // equity curve with Phase 4 sizing, realised at exit time, max 2 concurrent positions
    const sorted = [...trades].sort((a, b) => a.fillT - b.fillT);
    const open = [], taken = [];
    for (const t of sorted) {
      for (let k = open.length - 1; k >= 0; k--) if (open[k].exitT <= t.fillT) open.splice(k, 1);
      if (open.length >= cfg.maxPositions) continue;
      open.push(t); taken.push(t);
    }
    const events = taken.map(t => ({ t: t.exitT, pnl: Math.min(cfg.riskFrac * cfg.equity / (cfg.slAtr * t.atrPct), cfg.maxNotional) * t.net }))
      .sort((a, b) => a.t - b.t);
    let eq = 0, peak = 0, dd = 0;
    for (const e of events) { eq += e.pnl; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); }
    let ceq = 0, cpeak = 0, cdd = 0;                     // drawdown in summed trade-% (unsized)
    for (const t of [...trades].sort((a, b) => a.exitT - b.exitT)) { ceq += t.net; cpeak = Math.max(cpeak, ceq); cdd = Math.max(cdd, cpeak - ceq); }
    const placed = orders.filter(o => !o.rejectedAlo).length, filled = orders.filter(o => o.filled).length;
    const kinds = {}; for (const t of trades) kinds[t.kind] = (kinds[t.kind] || 0) + 1;
    return {
      trades: n, winPct: n ? 100 * wins.length / n : null,
      avgNetPct: n ? 100 * trades.reduce((s, t) => s + t.net, 0) / n : null,
      avgGrossPct: n ? 100 * trades.reduce((s, t) => s + t.gross, 0) / n : null,
      profitFactor: gl > 0 ? gp / gl : (gp > 0 ? Infinity : null),
      sumNetPct: 100 * trades.reduce((s, t) => s + t.net, 0),
      maxDdEquityPct: 100 * dd / cfg.equity, returnEquityPct: 100 * eq / cfg.equity, takenTrades: taken.length,
      maxDdSumPct: 100 * cdd, ordersPlaced: placed, aloRejected: orders.length - placed,
      makerFillRatePct: placed ? 100 * filled / placed : null, exits: kinds,
    };
  }

  function evaluate(results, cut, cfg) {
    const out = { cutUtc: new Date(cut).toISOString(), markets: {}, combined: {} };
    const all = { is: { t: [], o: [] }, oos: { t: [], o: [] } };
    for (const [sym, r] of Object.entries(results)) {
      const part = k => ({ t: r.trades.filter(x => k === 'is' ? x.fillT < cut : x.fillT >= cut),
                           o: r.orders.filter(x => k === 'is' ? x.t < cut : x.t >= cut) });
      out.markets[sym] = { atrFloorPct: 100 * r.floor };
      for (const k of ['is', 'oos']) {
        const p = part(k); out.markets[sym][k] = stats(p.t, p.o, cfg);
        all[k].t.push(...p.t); all[k].o.push(...p.o);
      }
    }
    for (const k of ['is', 'oos']) out.combined[k] = stats(all[k].t, all[k].o, cfg);
    const o = out.combined.oos, pos = Object.values(out.markets).filter(m => m.oos.trades && m.oos.avgNetPct > 0).length;
    out.gate = {
      trades_ge_20: o.trades >= 20, avg_net_ge_0_05pct: o.avgNetPct != null && o.avgNetPct >= 0.05,
      pf_ge_1_2: o.profitFactor != null && o.profitFactor >= 1.2, max_dd_le_0_5pct: o.maxDdEquityPct <= 0.5,
      positive_markets_ge_2: pos >= 2, positiveMarkets: pos,
    };
    out.gate.GO = ['trades_ge_20', 'avg_net_ge_0_05pct', 'pf_ge_1_2', 'max_dd_le_0_5pct', 'positive_markets_ge_2'].every(k => out.gate[k]);
    return out;
  }

  async function info(host, body) {
    const r = await fetch(host + '/info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }
  async function candles(host, coin, bars = 5000) {
    const end = Date.now(), start = end - bars * 3600e3;
    const c = await info(host, { type: 'candleSnapshot', req: { coin, interval: '1h', startTime: start, endTime: end } });
    const out = c.map(x => ({ t: x.t, o: +x.o, h: +x.h, l: +x.l, c: +x.c, v: +x.v }));
    const last = out[out.length - 1];
    if (last && last.t + 3600e3 > end) out.pop();                     // drop the bar still forming
    return out;
  }
  async function fundingHistory(host, coin, startTime) {
    const out = [];
    let t = startTime;
    for (let k = 0; k < 40; k++) {
      const f = await info(host, { type: 'fundingHistory', coin, startTime: t });
      if (!f.length) break;
      for (const x of f) out.push({ t: x.time, r: +x.fundingRate });
      const nt = f[f.length - 1].time + 1;
      if (nt <= t || f.length < 2) break;
      t = nt;
    }
    return out;
  }

  // markets: [{symbol, coin, host}] ; returns per-market + combined IS/OOS table and the Phase 3 gate.
  async function run({ markets, cfg = SPEC, data = null, withFunding = true }) {
    cfg = Object.assign({}, SPEC, cfg);
    data = data || {};
    for (const m of markets) {
      if (!data[m.symbol]) {
        const bars = await candles(m.host, m.coin);
        const funding = withFunding && bars.length ? await fundingHistory(m.host, m.coin, bars[0].t) : [];
        data[m.symbol] = { bars, funding };
      }
    }
    const syms = markets.map(m => m.symbol).filter(s => data[s].bars.length > cfg.warmup + 10);
    const t0 = Math.max(...syms.map(s => data[s].bars[0].t)), t1 = Math.min(...syms.map(s => data[s].bars[data[s].bars.length - 1].t));
    const cut = t0 + cfg.split * (t1 - t0);
    const results = {};
    for (const s of syms) results[s] = simulate(s, data[s].bars, data[s].funding, cfg);
    const out = evaluate(results, cut, cfg);
    out.window = { startUtc: new Date(t0).toISOString(), endUtc: new Date(t1).toISOString(),
                   bars: Object.fromEntries(syms.map(s => [s, data[s].bars.length])) };
    out.cfg = cfg;
    return { out, data, results };
  }

  root.FAB = { SPEC, ema, atr, simulate, stats, evaluate, candles, fundingHistory, run };
})(typeof window !== 'undefined' ? window : globalThis);
