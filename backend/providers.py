"""Market data + broker providers.

demo     - deterministic fake prices, works offline, no account needed
yahoo    - free delayed SET prices (SYMBOL.BK) for brokers without Open API
settrade - Settrade Open API v2 (quotes, candles, portfolio, trades, orders)
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import keyring

KEYRING_SERVICE = "stocknote-settrade"
BKK = timezone(timedelta(hours=7))
INTERVALS = {"5m", "15m", "60m", "1d", "1w", "1M"}


class ProviderError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers
def _cache():
    store: dict = {}
    lock = threading.Lock()

    def get(key, ttl, fn):
        now = time.time()
        with lock:
            hit = store.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        val = fn()
        with lock:
            store[key] = (now, val)
        return val
    return get


cached = _cache()


# ---------------------------------------------------------------- demo
DEMO_BASE = {"PTT": 33.5, "AOT": 58.0, "CPALL": 55.25, "KBANK": 152.0,
             "ADVANC": 285.0, "SCB": 118.5, "GULF": 47.75, "BDMS": 26.5}


def _demo_series(symbol: str, n: int, step: timedelta) -> list[dict]:
    seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    rnd = random.Random(seed)
    price = DEMO_BASE.get(symbol, 10 + seed % 90)
    end = datetime.now(BKK).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    drift_phase = rnd.random() * 6
    for i in range(n):
        t = end - step * (n - 1 - i)
        drift = 0.0012 * math.sin(i / 37 + drift_phase)
        ret = rnd.gauss(drift, 0.016)
        o = price
        c = max(0.5, o * (1 + ret))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.006)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.006)))
        out.append({"time": int(t.timestamp()), "open": round(o, 2), "high": round(h, 2),
                    "low": round(l, 2), "close": round(c, 2),
                    "volume": int(rnd.uniform(2e6, 2.5e7))})
        price = c
    return out


class DemoProvider:
    name = "demo"
    live = False

    def candles(self, symbol, interval="1d", limit=500):
        step = {"1w": timedelta(weeks=1), "1M": timedelta(days=30)}.get(interval, timedelta(days=1))
        return _demo_series(symbol.upper(), limit, step)

    def quote(self, symbol):
        s = _demo_series(symbol.upper(), 600, timedelta(days=1))
        prev, last = s[-2]["close"], s[-1]["close"]
        return {"symbol": symbol.upper(), "last": last, "prev_close": prev,
                "change": round(last - prev, 2), "pct": round((last / prev - 1) * 100, 2),
                "delayed": False, "demo": True}


# ---------------------------------------------------------------- yahoo
class YahooProvider:
    name = "yahoo"
    live = False
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.BK"
    MAP = {"5m": ("5m", "1mo"), "15m": ("15m", "1mo"), "60m": ("60m", "6mo"),
           "1d": ("1d", "5y"), "1w": ("1wk", "10y"), "1M": ("1mo", "max")}

    def __init__(self):
        self.http = httpx.Client(timeout=10, headers={"User-Agent": "Mozilla/5.0"})

    def _chart(self, symbol, interval):
        iv, rng = self.MAP.get(interval, ("1d", "5y"))

        def fetch():
            r = self.http.get(self.URL.format(sym=symbol.upper()),
                              params={"interval": iv, "range": rng})
            if r.status_code == 404:
                raise ProviderError(f"No such symbol on SET: {symbol}")
            r.raise_for_status()
            res = r.json()["chart"]["result"]
            if not res:
                raise ProviderError(f"No data for {symbol}")
            return res[0]
        return cached(("y", symbol, interval), 60, fetch)

    def candles(self, symbol, interval="1d", limit=500):
        d = self._chart(symbol, interval)
        q = d["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(d.get("timestamp") or []):
            if q["close"][i] is None:
                continue
            out.append({"time": t, "open": q["open"][i], "high": q["high"][i],
                        "low": q["low"][i], "close": q["close"][i],
                        "volume": q["volume"][i] or 0})
        return out[-limit:]

    def quote(self, symbol):
        m = self._chart(symbol, "1d")["meta"]
        last, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
        return {"symbol": symbol.upper(), "last": last, "prev_close": prev,
                "change": round(last - prev, 2) if last and prev else None,
                "pct": round((last / prev - 1) * 100, 2) if last and prev else None,
                "delayed": True}


# ---------------------------------------------------------------- settrade
_memory_creds: dict[str, dict] = {}   # for accounts the user chose not to remember


def save_credentials(acc_id: str, app_id: str, app_secret: str, app_code: str, remember: bool = True) -> None:
    data = {"app_id": app_id, "app_secret": app_secret, "app_code": app_code}
    if remember:
        keyring.set_password(KEYRING_SERVICE, f"acct:{acc_id}", json.dumps(data))
    else:
        _memory_creds[acc_id] = data


def load_credentials(acc_id: str) -> dict | None:
    if acc_id in _memory_creds:
        return _memory_creds[acc_id]
    raw = keyring.get_password(KEYRING_SERVICE, f"acct:{acc_id}")
    return json.loads(raw) if raw else None


def clear_credentials(acc_id: str) -> None:
    _memory_creds.pop(acc_id, None)
    try:
        keyring.delete_password(KEYRING_SERVICE, f"acct:{acc_id}")
    except keyring.errors.PasswordDeleteError:
        pass


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class SettradeProvider:
    name = "settrade"
    live = True

    def __init__(self, acc_id: str, broker_id: str, account_no: str, sandbox: bool = False):
        creds = load_credentials(acc_id)
        if not creds:
            raise ProviderError("ไม่พบ API key ของบัญชีนี้ ให้เข้าสู่ระบบด้วย key อีกครั้ง")
        from settrade_v2 import Investor
        from settrade_v2.errors import SettradeError
        self.SettradeError = SettradeError
        self.account_no = account_no
        try:
            self.inv = Investor(app_id=creds["app_id"], app_secret=creds["app_secret"],
                                broker_id="SANDBOX" if sandbox else broker_id,
                                app_code=creds["app_code"], is_auto_queue=True)
            self.mkt = self.inv.MarketData()
            self.eq = self.inv.Equity(account_no=account_no)
        except SettradeError as e:
            raise ProviderError(f"เข้าสู่ระบบ Settrade ไม่สำเร็จ ({e.code}): {e}") from None
        except Exception:
            raise ProviderError("รูปแบบ App ID หรือ App Secret ไม่ถูกต้อง ให้คัดลอกจากหน้า API Key Management อีกครั้ง") from None
        self.lock = threading.Lock()

    def _call(self, fn, *a, **kw):
        with self.lock:
            try:
                return fn(*a, **kw)
            except self.SettradeError as e:
                raise ProviderError(f"Settrade {e.code}: {e}") from None

    def candles(self, symbol, interval="1d", limit=500):
        raw = cached(("s", symbol, interval, limit), 30,
                     lambda: self._call(self.mkt.get_candlestick, symbol=symbol.upper(),
                                        interval=interval, limit=limit))
        if isinstance(raw, dict) and "time" in raw:      # columnar response
            keys = ["time", "open", "high", "low", "close", "volume"]
            return [dict(zip(keys, row)) for row in zip(*(raw.get(k, []) for k in keys))]
        return [{"time": _pick(r, "time", "t"), "open": _pick(r, "open", "o"),
                 "high": _pick(r, "high", "h"), "low": _pick(r, "low", "l"),
                 "close": _pick(r, "close", "c"), "volume": _pick(r, "volume", "v", default=0)}
                for r in (raw or [])]

    def quote(self, symbol):
        q = cached(("sq", symbol), 5, lambda: self._call(self.mkt.get_quote_symbol, symbol.upper()))
        last = _pick(q, "last", "lastPrice")
        prev = _pick(q, "prior", "priorClose", "previousClose")
        return {"symbol": symbol.upper(), "last": last, "prev_close": prev,
                "change": _pick(q, "change"), "pct": _pick(q, "percentChange", "pctChange"),
                "delayed": False}

    def portfolio(self) -> list[dict]:
        raw = self._call(self.eq.get_portfolios)
        rows = raw.get("portfolioList", raw) if isinstance(raw, dict) else raw
        return [{"symbol": _pick(r, "symbol"),
                 "qty": float(_pick(r, "actualVolume", "currentVolume", "volume", default=0)),
                 "avg_cost": float(_pick(r, "averagePrice", "avgPrice", default=0)),
                 "raw": r} for r in rows or []]

    def trades(self) -> list[dict]:
        rows = self._call(self.eq.get_trades) or []
        out = []
        for r in rows:
            side = str(_pick(r, "side", default="")).upper()
            out.append({
                "external_id": f"st:{_pick(r, 'tradeNo', 'tradeId', 'dealNo')}:{_pick(r, 'orderNo')}",
                "date": str(_pick(r, "tradeDate", "tradeDateTime", "tradeTime",
                                  default=datetime.now(BKK).date().isoformat()))[:10],
                "symbol": _pick(r, "symbol"),
                "side": "BUY" if side.startswith("B") else "SELL",
                "qty": float(_pick(r, "qty", "volume", "matchedVolume", default=0)),
                "price": float(_pick(r, "px", "price", "matchedPrice", default=0)),
                "fee": None,
                "raw": r,
            })
        return out

    def orders(self) -> list[dict]:
        return self._call(self.eq.get_orders) or []

    def place_order(self, pin, side, symbol, volume, price):
        return self._call(self.eq.place_order, pin=pin, side="Buy" if side == "BUY" else "Sell",
                          symbol=symbol.upper(), volume=int(volume), price=float(price))

    def cancel_order(self, order_no, pin):
        return self._call(self.eq.cancel_order, order_no=str(order_no), pin=pin)


def make_provider(account: dict | None):
    if account and account["kind"] == "api":
        return SettradeProvider(account["id"], account["broker_id"], account["account_no"], bool(account["sandbox"]))
    if account and account["price_source"] == "demo":
        return DemoProvider()
    return YahooProvider()
