// Funding-carry basket risk (decision support only; NOT an implementation, nothing here trades).
// Basket: long BTC, ETH, HYPE, SP500 and short USDJPY on pas, 1x, equal notional per leg.
// Price paths: 24 h block bootstrap of joint hourly mainnet returns (BTC, ETH, HYPE, xyz:SP500, xyz:JPY=USDJPY),
// so cross-correlation and volatility clustering are kept. Funding: pas testnet hourly rates (8-day mean),
// received by the side the strategy holds. Costs: taker 0.09% + 0.0455% measured slippage per leg per side.
// Rules modelled: per-leg 8% stop (existing carry mandate), optional account halt, optional basket hard stop
// checked every hour on marked P&L (an hourly check lets the realised loss overshoot the stop: reported).
(function (root) {
  function align(series) {                        // series: {name: [{t,c}]} -> {t:[], px:{name:[]}}
    const names = Object.keys(series);
    const maps = names.map(n => new Map(series[n].map(b => [b.t, b.c])));
    const ts = series[names[0]].map(b => b.t).filter(t => maps.every(m => m.has(t)));
    return { names, ts, px: Object.fromEntries(names.map((n, i) => [n, ts.map(t => maps[i].get(t))])) };
  }
  function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

  function simulate({ aligned, legs, equity = 100000, notional, hours, fundingPerHour, paths = 20000, block = 24,
                      cost = 0.0009 + 0.000455, legStop = 0.08, accountHalt = null, basketStop = null, seed = 7 }) {
    const R = legs.map(l => { const p = aligned.px[l.name]; return p.slice(1).map((x, i) => x / p[i]); });
    const n = R[0].length, rand = rng(seed), results = [];
    let stopHits = 0, haltHits = 0;
    for (let k = 0; k < paths; k++) {
      const level = legs.map(() => 1), alive = legs.map(() => true), closed = legs.map(() => 0);
      let funding = 0, entry = -legs.length * notional * cost, start = 0, outcome = null;
      for (let h = 0; h < hours && outcome == null; h++) {
        if (h % block === 0) start = Math.floor(rand() * (n - block)) - h;     // new block every `block` hours
        let mtm = 0;
        for (let i = 0; i < legs.length; i++) {
          if (!alive[i]) continue;
          level[i] *= R[i][start + h];
          funding += notional * fundingPerHour[i];
          const pnl = legs[i].dir * (level[i] - 1) * notional;
          if (-legs[i].dir * (level[i] - 1) >= legStop) { alive[i] = false; closed[i] = pnl - notional * cost; continue; }
          mtm += pnl;
        }
        const exitCost = alive.filter(Boolean).length * notional * cost;
        const net = entry + funding + mtm + closed.reduce((a, b) => a + b, 0) - exitCost;
        if (basketStop != null && net <= -basketStop * equity) { outcome = net; stopHits++; }
        else if (accountHalt != null && net <= -accountHalt * equity) { outcome = net; haltHits++; }
        else if (h === hours - 1) outcome = net;
      }
      results.push(outcome / equity * 100);
    }
    results.sort((a, b) => a - b);
    const q = p => results[Math.min(results.length - 1, Math.floor(p * results.length))];
    return {
      paths, notionalPerLeg: notional, medianPct: q(0.5), meanPct: results.reduce((a, b) => a + b, 0) / results.length,
      pLossPct: 100 * results.filter(x => x < 0).length / results.length, p5Pct: q(0.05), p1Pct: q(0.01),
      worstPct: results[0], p95Pct: q(0.95), basketStopHitPct: 100 * stopHits / paths, haltHitPct: 100 * haltHits / paths,
    };
  }
  root.CARRY = { align, simulate };
})(typeof window !== 'undefined' ? window : globalThis);
