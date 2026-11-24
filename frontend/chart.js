// Price chart built on TradingView Lightweight Charts v4.
import { sma, ema, bollinger, rsi, macd, autoFib } from "./indicators.js";

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const LINE = { ma20: "#7C8CFF", ma50: "#FF9F43", ema12: "#2EC4F1", bb: "rgba(179,188,211,.55)", fib: "#C084FC" };

function baseOptions(el) {
  return {
    width: el.clientWidth, height: el.clientHeight,
    layout: { background: { color: "transparent" }, textColor: css("--text-2"), fontFamily: css("--font-ui"), fontSize: 12 },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: false },
    crosshair: { mode: 0 },
    localization: { locale: "th-TH" },
  };
}

export class PriceChart {
  constructor(mainEl, rsiEl, macdEl, legendEl, fibEl) {
    const LC = window.LightweightCharts;
    this.els = { mainEl, rsiEl, macdEl, legendEl, fibEl };
    this.main = LC.createChart(mainEl, baseOptions(mainEl));
    this.candle = this.main.addCandlestickSeries({
      upColor: css("--gain"), downColor: css("--loss"), borderVisible: false,
      wickUpColor: css("--gain"), wickDownColor: css("--loss"),
    });
    // keep cost / fib lines inside the visible price range
    this.extraPrices = [];
    this.candle.applyOptions({
      autoscaleInfoProvider: original => {
        const r = original();
        if (!r || !this.extraPrices.length) return r;
        return { ...r, priceRange: {
          minValue: Math.min(r.priceRange.minValue, ...this.extraPrices),
          maxValue: Math.max(r.priceRange.maxValue, ...this.extraPrices) } };
      },
    });
    this.vol = this.main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    this.main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    this.overlays = [];
    this.priceLines = [];
    this.sub = {};
    this.on = new Set(["ma20", "ma50", "cost"]);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(mainEl);
  }

  resize() {
    const { mainEl, rsiEl, macdEl } = this.els;
    this.main.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight });
    if (this.sub.rsi) this.sub.rsi.chart.applyOptions({ width: rsiEl.clientWidth });
    if (this.sub.macd) this.sub.macd.chart.applyOptions({ width: macdEl.clientWidth });
  }

  setData(candles, position) {
    this.candles = candles;
    this.position = position;
    this.candle.setData(candles);
    this.vol.setData(candles.map(c => ({ time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(7,138,85,.28)" : "rgba(212,42,58,.28)" })));
    this.redraw();
    this.main.timeScale().fitContent();
  }

  toggle(key) { this.on.has(key) ? this.on.delete(key) : this.on.add(key); this.redraw(); return this.on.has(key); }

  redraw() {
    const c = this.candles || [];
    this.overlays.forEach(s => this.main.removeSeries(s)); this.overlays = [];
    this.priceLines.forEach(l => this.candle.removePriceLine(l)); this.priceLines = [];
    const legend = [];
    const add = (data, color, title, width = 1.5, style = 0) => {
      const s = this.main.addLineSeries({ color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(data); this.overlays.push(s); if (title) legend.push([color, title]);
    };
    if (this.on.has("ma20")) add(sma(c, 20), LINE.ma20, "SMA 20");
    if (this.on.has("ma50")) add(sma(c, 50), LINE.ma50, "SMA 50");
    if (this.on.has("ema12")) add(ema(c, 12), LINE.ema12, "EMA 12");
    if (this.on.has("bb")) { const b = bollinger(c); add(b.up, LINE.bb, "Bollinger 20, 2", 1, 2); add(b.mid, LINE.bb, null, 1, 2); add(b.low, LINE.bb, null, 1, 2); }

    const amber = css("--mark");
    if (this.on.has("cost") && this.position?.qty > 0) {
      this.priceLines.push(this.candle.createPriceLine({ price: this.position.avg_cost, color: amber, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: "ต้นทุนเฉลี่ย" }));
      this.position.lots.forEach((l, i) => this.priceLines.push(this.candle.createPriceLine({
        price: l.unit_cost, color: amber, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: `ล็อต ${i + 1}`,
      })));
      legend.push([amber, "ต้นทุนเฉลี่ย / แต่ละล็อต"]);
    }

    const fibEl = this.els.fibEl; fibEl.textContent = "";
    if (this.on.has("fib")) {
      const f = autoFib(c);
      if (f) {
        f.levels.forEach(lv => this.priceLines.push(this.candle.createPriceLine({
          price: lv.price, color: LINE.fib, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `Fib ${(lv.ratio * 100).toFixed(1)}%`,
        })));
        const fmt = v => v.toFixed(2);
        const where = f.below && f.above
          ? `ราคาตอนนี้ ${fmt(f.last)} อยู่ระหว่าง Fib ${(f.below.ratio * 100).toFixed(1)}% (${fmt(f.below.price)}) กับ ${(f.above.ratio * 100).toFixed(1)}% (${fmt(f.above.price)})`
          : `ราคาตอนนี้ ${fmt(f.last)} อยู่นอกช่วง Fibonacci`;
        fibEl.textContent = `Fibonacci อัตโนมัติจากรอบ${f.up ? "ขาขึ้น" : "ขาลง"} ${fmt(f.low)} ถึง ${fmt(f.high)} ใน 120 แท่งล่าสุด  ${where}`;
        legend.push([LINE.fib, "Fibonacci"]);
      }
    }

    this.renderSub("rsi", this.on.has("rsi"), chart => {
      const s = chart.addLineSeries({ color: LINE.ma20, lineWidth: 1.5, priceLineVisible: false });
      s.setData(rsi(c));
      [70, 30].forEach(p => s.createPriceLine({ price: p, color: css("--line-strong"), lineStyle: 2, lineWidth: 1, axisLabelVisible: false }));
    });
    this.renderSub("macd", this.on.has("macd"), chart => {
      const m = macd(c);
      const h = chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      h.setData(m.hist.map(p => ({ ...p, color: p.value >= 0 ? "rgba(7,138,85,.55)" : "rgba(212,42,58,.55)" })));
      chart.addLineSeries({ color: LINE.ma20, lineWidth: 1.5, priceLineVisible: false }).setData(m.macdLine);
      chart.addLineSeries({ color: amber, lineWidth: 1.5, priceLineVisible: false }).setData(m.signal);
    });

    this.extraPrices = this.on.has("cost") && this.position?.qty > 0 ? this.position.lots.map(l => l.unit_cost).concat(this.position.avg_cost) : [];
    this.main.timeScale().applyOptions({});  // trigger autoscale refresh
    this.candle.applyOptions({});
    this.els.legendEl.innerHTML = legend.map(([col, t]) => `<span><i style="background:${col}"></i>${t}</span>`).join("");
  }

  renderSub(key, show, build) {
    const el = key === "rsi" ? this.els.rsiEl : this.els.macdEl;
    if (this.sub[key]) { this.main.timeScale().unsubscribeVisibleLogicalRangeChange(this.sub[key].sync); this.sub[key].chart.remove(); delete this.sub[key]; }
    el.hidden = !show;
    if (!show) return;
    const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = key === "rsi" ? "RSI 14" : "MACD 12, 26, 9";
    el.replaceChildren(tag);
    const chart = window.LightweightCharts.createChart(el, { ...baseOptions(el), height: el.clientHeight, timeScale: { visible: false } });
    build(chart);
    const sync = r => r && chart.timeScale().setVisibleLogicalRange(r);
    this.main.timeScale().subscribeVisibleLogicalRangeChange(sync);
    const r = this.main.timeScale().getVisibleLogicalRange(); if (r) chart.timeScale().setVisibleLogicalRange(r);
    this.sub[key] = { chart, sync };
  }

  destroy() {
    this.ro.disconnect();
    Object.values(this.sub).forEach(s => s.chart.remove());
    this.main.remove();
  }
}
