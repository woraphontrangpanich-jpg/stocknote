// Technical indicators. Input: candles [{time, open, high, low, close, volume}].
// Output: [{time, value}] aligned to the input, starting where the value is defined.

export function sma(c, n) {
  const out = []; let sum = 0;
  for (let i = 0; i < c.length; i++) {
    sum += c[i].close;
    if (i >= n) sum -= c[i - n].close;
    if (i >= n - 1) out.push({ time: c[i].time, value: sum / n });
  }
  return out;
}

export function emaValues(values, n) {
  const k = 2 / (n + 1); const out = new Array(values.length).fill(null);
  let prev = null, seed = 0;
  for (let i = 0; i < values.length; i++) {
    if (i < n - 1) { seed += values[i]; continue; }
    if (prev === null) { prev = (seed + values[i]) / n; } else { prev = values[i] * k + prev * (1 - k); }
    out[i] = prev;
  }
  return out;
}

export function ema(c, n) {
  const v = emaValues(c.map(x => x.close), n);
  return c.map((x, i) => ({ time: x.time, value: v[i] })).filter(p => p.value !== null);
}

export function bollinger(c, n = 20, k = 2) {
  const up = [], mid = [], low = [];
  for (let i = n - 1; i < c.length; i++) {
    const w = c.slice(i - n + 1, i + 1).map(x => x.close);
    const m = w.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / n);
    mid.push({ time: c[i].time, value: m });
    up.push({ time: c[i].time, value: m + k * sd });
    low.push({ time: c[i].time, value: m - k * sd });
  }
  return { up, mid, low };
}

export function rsi(c, n = 14) {
  const out = []; let g = 0, l = 0;
  for (let i = 1; i < c.length; i++) {
    const d = c[i].close - c[i - 1].close;
    const up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= n) { g += up; l += dn; if (i === n) { g /= n; l /= n; out.push({ time: c[i].time, value: l === 0 ? 100 : 100 - 100 / (1 + g / l) }); } continue; }
    g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n;
    out.push({ time: c[i].time, value: l === 0 ? 100 : 100 - 100 / (1 + g / l) });
  }
  return out;
}

export function macd(c, fast = 12, slow = 26, sig = 9) {
  const closes = c.map(x => x.close);
  const f = emaValues(closes, fast), s = emaValues(closes, slow);
  const line = c.map((x, i) => (f[i] !== null && s[i] !== null ? f[i] - s[i] : null));
  const valid = line.map((v, i) => [v, i]).filter(([v]) => v !== null);
  const sigV = emaValues(valid.map(([v]) => v), sig);
  const macdLine = [], signal = [], hist = [];
  valid.forEach(([v, i], j) => {
    macdLine.push({ time: c[i].time, value: v });
    if (sigV[j] !== null) {
      signal.push({ time: c[i].time, value: sigV[j] });
      hist.push({ time: c[i].time, value: v - sigV[j] });
    }
  });
  return { macdLine, signal, hist };
}

export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

// Auto Fibonacci on the largest swing within the last `look` bars.
export function autoFib(c, look = 120) {
  if (c.length < 10) return null;
  const w = c.slice(-look);
  let hi = 0, lo = 0;
  w.forEach((x, i) => { if (x.high > w[hi].high) hi = i; if (x.low < w[lo].low) lo = i; });
  const H = w[hi].high, L = w[lo].low, range = H - L;
  if (range <= 0) return null;
  const up = lo < hi; // swing low came first -> uptrend, retrace down from the high
  const levels = FIB_RATIOS.map(r => ({ ratio: r, price: up ? H - range * r : L + range * r }));
  const last = c[c.length - 1].close;
  const sorted = [...levels].sort((a, b) => a.price - b.price);
  let below = null, above = null;
  for (const lv of sorted) { if (lv.price <= last) below = lv; else if (!above) above = lv; }
  return { up, high: H, low: L, highTime: w[hi].time, lowTime: w[lo].time, levels, last, below, above };
}
