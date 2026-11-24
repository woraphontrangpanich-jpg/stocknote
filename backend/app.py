"""Stock Note local server.

Runs on 127.0.0.1 only. Every /api call must carry the per-run token that is
written into index.html when it is served, and the Host header must be the
local address, which blocks other websites and DNS-rebinding tricks from
talking to this server. Settrade secrets live in Windows Credential Manager
(or only in memory when the user chooses not to remember them) and are never
sent back to the browser. The trading PIN is never stored.

Sessions: the app starts logged out. The user picks an account (or adds one
with an API key) on the login screen. Each account has its own ledger.
"""
from __future__ import annotations

import os
import secrets
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db, excel
from .ledger import LedgerError, build_positions, simulate_sell
from .providers import (INTERVALS, ProviderError, SettradeProvider, clear_credentials,
                        load_credentials, make_provider, save_credentials)

PORT = int(os.environ.get("STOCKNOTE_PORT", "47615"))
TOKEN = secrets.token_urlsafe(32)
FRONT = Path(__file__).resolve().parent.parent / "frontend"
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
OPEN_PATHS = {"/api/session", "/api/login", "/api/accounts", "/api/brokers"}

app = FastAPI(title="Stock Note", docs_url=None, redoc_url=None, openapi_url=None)
con = db.connect()
db.daily_backup()
_state: dict = {"account": None, "provider": None}
_lock = threading.Lock()


# ---------------------------------------------------------------- security
@app.middleware("http")
async def guard(request: Request, call_next):
    if request.headers.get("host") not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    path = request.url.path
    if path.startswith("/api/"):
        if not secrets.compare_digest(request.headers.get("x-app-token", ""), TOKEN):
            return JSONResponse({"detail": "Missing or wrong app token"}, status_code=401)
        if _state["account"] is None and path not in OPEN_PATHS and not path.startswith("/api/accounts/"):
            return JSONResponse({"detail": "ยังไม่ได้เข้าสู่ระบบ", "code": "LOGGED_OUT"}, status_code=401)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    if path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(LedgerError)
async def _ledger_err(_, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(ProviderError)
async def _prov_err(_, e):
    return JSONResponse({"detail": str(e)}, status_code=502)


# ---------------------------------------------------------------- session
def account() -> dict:
    acc = _state["account"]
    if acc is None:
        raise HTTPException(401, "ยังไม่ได้เข้าสู่ระบบ")
    return acc


def book() -> str:
    return account()["id"]


def provider():
    with _lock:
        if _state["provider"] is None:
            _state["provider"] = make_provider(account())
        return _state["provider"]


def _activate(acc: dict):
    """Log in to `acc`. For API accounts this really signs in to Settrade."""
    prov = make_provider(acc)   # raises ProviderError when the key is wrong
    with _lock:
        _state["account"] = acc
        _state["provider"] = prov
    db.touch_account(con, acc["id"])


def broker() -> SettradeProvider:
    p = provider()
    if not isinstance(p, SettradeProvider):
        raise HTTPException(409, "บัญชีนี้ไม่ได้เชื่อม Settrade Open API")
    return p


def price_map(symbols) -> dict:
    out, p = {}, provider()
    for s in symbols:
        try:
            out[s] = p.quote(s)["last"]
        except Exception:
            out[s] = None
    return out


def _public(acc: dict) -> dict:
    keys = ("id", "label", "kind", "broker_id", "account_no", "sandbox", "price_source", "remember", "last_used")
    out = {k: acc.get(k) for k in keys}
    out["account_no"] = _mask(acc.get("account_no", ""))
    out["has_key"] = acc["kind"] == "api" and load_credentials(acc["id"]) is not None
    out["txn_count"] = acc.get("txn_count")
    out["broker_name"] = BROKER_NAMES.get(acc.get("broker_id", ""), "")
    return out


def _mask(no: str) -> str:
    return no if len(no) <= 4 else "•" * (len(no) - 4) + no[-4:]


# ---------------------------------------------------------------- brokers
BROKERS = [
    # (id, name, equity Open API supported) - from developer.settrade.com broker list
    ("015", "BEYOND", True), ("025", "Globlex", True), ("023", "InnovestX (INVX)", True),
    ("013", "KGI", True), ("022", "Trinity", True), ("026", "UOB Kay Hian (UOBKH)", True),
    ("008", "ASP", False), ("007", "CGS International", False), ("063", "Classic Ausiris", False),
    ("032", "DAOL SEC", False), ("029", "Krungsri", False), ("018", "KTX", False),
    ("060", "MTSGF", False), ("003", "Pi", False), ("034", "PST", False),
    ("062", "YLG", False), ("019", "Yuanta", False),
]
BROKER_NAMES = {b[0]: b[1] for b in BROKERS}


@app.get("/api/brokers")
def brokers():
    return [{"id": i, "name": n, "api": a} for i, n, a in BROKERS]


# ---------------------------------------------------------------- models
class TxnIn(BaseModel):
    date: str
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9\-\.&]+$")
    side: str = Field(pattern=r"^(BUY|SELL|DIV)$")
    qty: float = Field(gt=0)
    price: float = Field(ge=0)
    fee: float | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=200)

    @field_validator("date")
    @classmethod
    def _d(cls, v):
        date.fromisoformat(v[:10])
        return v[:10]


class SimIn(BaseModel):
    symbol: str
    qty: float = Field(gt=0)
    price: float = Field(gt=0)


class LoginIn(BaseModel):
    account_id: str | None = None
    # new API account
    label: str | None = Field(default=None, max_length=40)
    app_id: str | None = Field(default=None, max_length=200)
    app_secret: str | None = Field(default=None, max_length=400)
    app_code: str | None = Field(default=None, max_length=100)
    broker_id: str | None = Field(default=None, pattern=r"^\d{3}$")
    account_no: str | None = Field(default=None, max_length=30)
    sandbox: bool = False
    remember: bool = True


class ManualIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    broker_id: str = Field(default="", pattern=r"^(\d{3})?$")
    price_source: str = Field(default="yahoo", pattern=r"^(yahoo|demo)$")


class AccountPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=40)
    price_source: str | None = Field(default=None, pattern=r"^(yahoo|demo)$")


class OrderIn(BaseModel):
    side: str = Field(pattern=r"^(BUY|SELL)$")
    symbol: str = Field(pattern=r"^[A-Za-z0-9\-\.&]+$")
    volume: int = Field(gt=0)
    price: float = Field(gt=0)
    pin: str = Field(min_length=4, max_length=12)
    confirm: bool


class CancelIn(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


# ---------------------------------------------------------------- SET rules
TICKS = [(2, "0.01"), (5, "0.02"), (10, "0.05"), (25, "0.10"), (100, "0.25"),
         (200, "0.50"), (400, "1"), (float("inf"), "2")]


def tick_size(price: float) -> Decimal:
    for limit, t in TICKS:
        if price < limit:
            return Decimal(t)
    return Decimal("2")


def check_order(o: OrderIn):
    if o.volume % 100:
        raise HTTPException(400, "จำนวนหุ้นต้องเป็นทวีคูณของ 100 (board lot)")
    t = tick_size(o.price)
    if Decimal(str(o.price)) % t:
        raise HTTPException(400, f"ราคา {o.price} ไม่ตรงช่วงราคา (tick size {t})")


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index():
    return (FRONT / "index.html").read_text(encoding="utf-8").replace("__APP_TOKEN__", TOKEN)


# ---------------------------------------------------------------- session routes
@app.get("/api/session")
def session():
    acc = _state["account"]
    return {"logged_in": acc is not None,
            "account": _public(acc) if acc else None,
            "accounts": [_public(a) for a in db.list_accounts(con)]}


@app.post("/api/login")
def login(body: LoginIn):
    if body.account_id:
        acc = db.get_account(con, body.account_id)
        if not acc:
            raise HTTPException(404, "ไม่พบบัญชีนี้")
        if acc["kind"] == "api" and body.app_id and body.app_secret and body.app_code:
            # re-entering the key for a saved account
            save_credentials(acc["id"], body.app_id.strip(), body.app_secret.strip(), body.app_code.strip(), body.remember)
        if acc["kind"] == "api" and not load_credentials(acc["id"]):
            raise HTTPException(409, "บัญชีนี้ไม่ได้จำ API key ไว้ ใส่ App ID, App Secret และ App Code อีกครั้ง")
        _activate(acc)
        db.log(con, "login", acc["id"])
        return session()

    # new API account
    if not all([body.app_id, body.app_secret, body.app_code, body.broker_id, body.account_no]):
        raise HTTPException(400, "กรอกโบรก เลขบัญชี App ID App Secret และ App Code ให้ครบ")
    label = (body.label or "").strip() or f"{BROKER_NAMES.get(body.broker_id, 'โบรก ' + body.broker_id)} {_mask(body.account_no.strip())}"
    acc_id = db.create_account(con, label, "api", body.broker_id, body.account_no.strip(), body.sandbox, remember=body.remember)
    save_credentials(acc_id, body.app_id.strip(), body.app_secret.strip(), body.app_code.strip(), body.remember)
    try:
        _activate(db.get_account(con, acc_id))
    except ProviderError:
        clear_credentials(acc_id)
        db.delete_account(con, acc_id)
        raise
    db.log(con, "login", f"new api account broker {body.broker_id}")
    return session()


@app.post("/api/accounts")
def add_manual(body: ManualIn):
    acc_id = db.create_account(con, body.label.strip(), "manual", body.broker_id, price_source=body.price_source)
    _activate(db.get_account(con, acc_id))
    return session()


@app.patch("/api/account")
def patch_account(body: AccountPatch):
    acc = account()
    db.update_account(con, acc["id"], **body.model_dump(exclude_none=True))
    new = db.get_account(con, acc["id"])
    with _lock:
        _state["account"] = new
        _state["provider"] = None
    return session()


@app.delete("/api/accounts/{acc_id}")
def remove_account(acc_id: str, confirm: str = ""):
    acc = db.get_account(con, acc_id)
    if not acc:
        raise HTTPException(404, "ไม่พบบัญชีนี้")
    if confirm != "DELETE":
        raise HTTPException(400, "ต้องยืนยันด้วย confirm=DELETE")
    db.daily_backup()
    clear_credentials(acc_id)
    db.delete_account(con, acc_id)
    if _state["account"] and _state["account"]["id"] == acc_id:
        logout()
    return session()


@app.post("/api/accounts/{acc_id}/forget-key")
def forget_key(acc_id: str):
    if not db.get_account(con, acc_id):
        raise HTTPException(404, "ไม่พบบัญชีนี้")
    clear_credentials(acc_id)
    if _state["account"] and _state["account"]["id"] == acc_id:
        logout()
    return session()


@app.post("/api/logout")
def logout():
    with _lock:
        _state["account"] = None
        _state["provider"] = None
    return {"logged_in": False}


# ---------------------------------------------------------------- status & settings
@app.get("/api/status")
def status():
    acc, p = account(), provider()
    return {"provider": p.name, "account": _public(acc), "fees": db.get_settings(con)["fees"],
            "can_trade": isinstance(p, SettradeProvider), "txn_count": len(db.list_txns(con, book()))}


@app.put("/api/settings")
def put_settings(body: dict):
    if "fees" in body:
        f = body["fees"]
        for k in ("commission_rate", "regulatory_rate", "min_commission", "vat"):
            if not isinstance(f.get(k), (int, float)) or f[k] < 0 or f[k] > (1000 if k == "min_commission" else 0.2):
                raise HTTPException(400, f"ค่า {k} ไม่ถูกต้อง")
        db.set_settings(con, {"fees": f})
    return status()


# ---------------------------------------------------------------- ledger
def _positions(symbol: str | None = None):
    return build_positions(db.as_txns(db.list_txns(con, book(), symbol)), db.fee_config(con))


@app.get("/api/positions")
def positions():
    pos = _positions()
    fees = db.fee_config(con)
    prices = price_map([s for s, p in pos.items() if p.qty > 0])
    items = [p.summary(prices.get(s), fees) for s, p in pos.items()]
    held = [i for i in items if i["qty"] > 0]
    totals = {
        "cost": round(sum(i["cost"] for i in held), 2),
        "market_value": round(sum(i.get("market_value") or 0 for i in held), 2),
        "unrealized": round(sum(i.get("unrealized") or 0 for i in held), 2),
        "realized": round(sum(i["realized_fifo"] for i in items), 2),
        "dividends": round(sum(i["dividends"] for i in items), 2),
    }
    return {"items": sorted(items, key=lambda i: (i["qty"] == 0, -(i.get("market_value") or i["cost"]))),
            "totals": totals}


@app.get("/api/positions/{symbol}")
def position(symbol: str):
    sym = symbol.upper()
    pos = _positions(sym)
    if sym not in pos:
        raise HTTPException(404, f"ยังไม่มีรายการของ {sym}")
    p = pos[sym]
    out = p.summary(price_map([sym])[sym], db.fee_config(con))
    out["history"] = p.history
    return out


@app.post("/api/simulate")
def simulate(s: SimIn):
    sym = s.symbol.upper()
    pos = _positions(sym)
    if sym not in pos:
        raise HTTPException(404, f"ไม่มีหุ้น {sym} ในพอร์ต")
    return simulate_sell(pos[sym], s.qty, s.price, db.fee_config(con))


def _validate_ledger():
    build_positions(db.as_txns(db.list_txns(con, book())), db.fee_config(con))


@app.get("/api/txns")
def txns(symbol: str | None = None):
    return db.list_txns(con, book(), symbol)


@app.post("/api/txns")
def add_txn(t: TxnIn):
    new_id = db.add_txn(con, book(), t.model_dump())
    try:
        _validate_ledger()
    except LedgerError:
        db.delete_txn(con, book(), new_id)
        raise
    return {"id": new_id}


@app.put("/api/txns/{txn_id}")
def edit_txn(txn_id: int, t: TxnIn):
    old = db.get_txn(con, book(), txn_id)
    if not old:
        raise HTTPException(404, "ไม่พบรายการ")
    db.update_txn(con, book(), txn_id, t.model_dump())
    try:
        _validate_ledger()
    except LedgerError:
        db.update_txn(con, book(), txn_id, old)
        raise
    return {"ok": True}


@app.delete("/api/txns/{txn_id}")
def remove_txn(txn_id: int):
    old = db.get_txn(con, book(), txn_id)
    if not old:
        raise HTTPException(404, "ไม่พบรายการ")
    db.delete_txn(con, book(), txn_id)
    try:
        _validate_ledger()
    except LedgerError:
        db.add_txn(con, book(), old, source=old["source"], external_id=old["external_id"])
        raise
    return {"ok": True}


@app.post("/api/import")
async def import_file(file: UploadFile = File(...), commit: bool = False):
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "ไฟล์ใหญ่เกิน 5 MB")
    try:
        rows = excel.parse_rows(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not commit:
        return {"rows": rows, "count": len(rows)}
    ids = [db.add_txn(con, book(), r, source="import") for r in rows]
    try:
        _validate_ledger()
    except LedgerError:
        for i in ids:
            if i:
                db.delete_txn(con, book(), i)
        raise
    db.log(con, "import", f"{len(rows)} rows from {file.filename}")
    return {"imported": len(rows)}


@app.get("/api/template.csv")
def template():
    return Response(excel.template_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="stocknote-template.csv"'})


@app.get("/api/export.xlsx")
def export():
    pos = _positions()
    prices = price_map([s for s, p in pos.items() if p.qty > 0])
    data = excel.build_workbook(pos, prices, db.list_txns(con, book()), db.fee_config(con))
    name = f"portfolio-{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/demo/seed")
def seed_demo():
    if db.list_txns(con, book()):
        raise HTTPException(409, "บัญชีนี้มีข้อมูลอยู่แล้ว")
    sample = [
        ("2024-01-15", "PTT", "BUY", 100, 40), ("2024-03-02", "PTT", "BUY", 100, 45),
        ("2024-06-20", "PTT", "BUY", 100, 50), ("2024-08-01", "PTT", "SELL", 100, 45),
        ("2024-02-10", "AOT", "BUY", 200, 62.5), ("2024-09-05", "AOT", "BUY", 100, 55),
        ("2024-04-11", "KBANK", "BUY", 100, 128), ("2024-10-30", "KBANK", "BUY", 100, 141),
        ("2025-01-08", "KBANK", "SELL", 100, 150), ("2024-05-15", "KBANK", "DIV", 200, 2.5),
        ("2024-07-01", "CPALL", "BUY", 300, 58.75),
    ]
    for d, s, side, q, p in sample:
        db.add_txn(con, book(), {"date": d, "symbol": s, "side": side, "qty": q, "price": p,
                                 "fee": 50.0 if side == "DIV" else None, "note": "ตัวอย่าง"}, source="demo")
    db.set_watchlist(con, ["PTT", "AOT", "KBANK", "CPALL", "ADVANC", "GULF"])
    return {"ok": True}


@app.delete("/api/all")
def wipe(confirm: str = ""):
    if confirm != "DELETE":
        raise HTTPException(400, "ต้องยืนยันด้วย confirm=DELETE")
    db.daily_backup()
    db.wipe_book(con, book())
    return {"ok": True}


# ---------------------------------------------------------------- market
@app.get("/api/watchlist")
def watchlist():
    return db.get_watchlist(con)


@app.put("/api/watchlist")
def put_watchlist(symbols: list[str]):
    if len(symbols) > 100:
        raise HTTPException(400, "ติดตามได้สูงสุด 100 ตัว")
    return db.set_watchlist(con, symbols)


@app.get("/api/quotes")
def quotes(symbols: str):
    out, p = {}, provider()
    for s in [x.strip().upper() for x in symbols.split(",") if x.strip()][:60]:
        try:
            out[s] = p.quote(s)
        except Exception as e:
            out[s] = {"symbol": s, "error": str(e)}
    return out


@app.get("/api/candles/{symbol}")
def candles(symbol: str, interval: str = "1d", limit: int = 500):
    if interval not in INTERVALS:
        raise HTTPException(400, "interval ไม่ถูกต้อง")
    return provider().candles(symbol.upper(), interval, max(50, min(limit, 2000)))


# ---------------------------------------------------------------- broker
@app.post("/api/sync")
def sync():
    b = broker()
    added = 0
    for t in b.trades():
        if t["qty"] > 0 and db.add_txn(con, book(), t, source="settrade", external_id=t["external_id"]):
            added += 1
    pos = _positions()
    port = b.portfolio()
    mismatches = []
    for row in port:
        sym = (row["symbol"] or "").upper()
        mine = pos[sym].qty if sym in pos else 0
        if abs(mine - row["qty"]) > 1e-6:
            mismatches.append({"symbol": sym, "ledger_qty": mine, "broker_qty": row["qty"], "broker_avg": row["avg_cost"]})
    broker_syms = {(r["symbol"] or "").upper() for r in port}
    for sym, p in pos.items():
        if p.qty > 0 and sym not in broker_syms:
            mismatches.append({"symbol": sym, "ledger_qty": p.qty, "broker_qty": 0, "broker_avg": 0})
    db.log(con, "sync", f"added {added}, mismatches {len(mismatches)}")
    return {"added": added, "mismatches": mismatches}


@app.get("/api/orders")
def orders():
    return broker().orders()


@app.post("/api/orders")
def place(o: OrderIn):
    if not o.confirm:
        raise HTTPException(400, "ต้องยืนยันคำสั่งก่อนส่ง")
    check_order(o)
    if o.side == "SELL":
        pos = _positions(o.symbol.upper())
        held = pos[o.symbol.upper()].qty if o.symbol.upper() in pos else 0
        if o.volume > held:
            raise HTTPException(400, f"ในสมุดล็อตมี {o.symbol.upper()} {held:g} หุ้น ขาย {o.volume} ไม่ได้")
    res = broker().place_order(o.pin, o.side, o.symbol, o.volume, o.price)
    db.log(con, "order", f"{o.side} {o.symbol.upper()} {o.volume}@{o.price}")
    return res


@app.post("/api/orders/{order_no}/cancel")
def cancel(order_no: str, c: CancelIn):
    res = broker().cancel_order(order_no, c.pin)
    db.log(con, "cancel", order_no)
    return res


app.mount("/static", StaticFiles(directory=FRONT), name="static")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(FRONT / "favicon.svg", media_type="image/svg+xml")
