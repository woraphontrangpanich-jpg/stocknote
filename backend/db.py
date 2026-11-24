"""SQLite storage. One file in ./data, backed up once per day on startup.

Every account has its own ledger ("book"). Secrets never live here: API
credentials go to Windows Credential Manager (see providers.py).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import date
from pathlib import Path

from .ledger import FeeConfig, Txn

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("STOCKNOTE_DATA") or ROOT / "data")
DB_PATH = DATA / "ledger.db"
BACKUPS = DATA / "backups"
KEEP_BACKUPS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS txns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL CHECK (side IN ('BUY','SELL','DIV')),
    qty         REAL NOT NULL CHECK (qty > 0),
    price       REAL NOT NULL CHECK (price >= 0),
    fee         REAL,
    source      TEXT NOT NULL DEFAULT 'manual',
    external_id TEXT UNIQUE,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS txns_symbol ON txns(symbol);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    kind TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('api','manual')),
    broker_id    TEXT NOT NULL DEFAULT '',
    account_no   TEXT NOT NULL DEFAULT '',
    sandbox      INTEGER NOT NULL DEFAULT 0,
    price_source TEXT NOT NULL DEFAULT 'yahoo' CHECK (price_source IN ('yahoo','demo')),
    remember     INTEGER NOT NULL DEFAULT 1,
    last_used    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

DEFAULT_SETTINGS = {
    "fees": {"commission_rate": 0.00157, "regulatory_rate": 0.00007,
             "min_commission": 0.0, "vat": 0.07},
}
MAIN = "main"


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(txns)")}
    with con:
        if "book" not in cols:
            con.execute("ALTER TABLE txns ADD COLUMN book TEXT NOT NULL DEFAULT 'main'")
        con.execute("CREATE INDEX IF NOT EXISTS txns_book ON txns(book)")
        if not con.execute("SELECT 1 FROM accounts").fetchone():
            # migrate v1 single-account setup into a manual "main" account
            old = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM settings")}
            src = old.get("provider", "yahoo")
            con.execute("INSERT INTO accounts(id,label,kind,price_source) VALUES(?,?,?,?)",
                        (MAIN, "บัญชีหลัก", "manual", src if src in ("yahoo", "demo") else "yahoo"))
    return con


def daily_backup() -> Path | None:
    if not DB_PATH.exists():
        return None
    BACKUPS.mkdir(parents=True, exist_ok=True)
    target = BACKUPS / f"ledger-{date.today().isoformat()}.db"
    if not target.exists():
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close(); dst.close()
    for f in sorted(BACKUPS.glob("ledger-*.db"))[:-KEEP_BACKUPS]:
        f.unlink(missing_ok=True)
    return target


# --- settings -------------------------------------------------------------
def get_settings(con) -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for row in con.execute("SELECT key, value FROM settings"):
        if row["key"] in DEFAULT_SETTINGS:
            out[row["key"]] = json.loads(row["value"])
    return out


def set_settings(con, values: dict) -> dict:
    with con:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                con.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
    return get_settings(con)


def fee_config(con) -> FeeConfig:
    f = get_settings(con)["fees"]
    return FeeConfig(**{k: float(f[k]) for k in ("commission_rate", "regulatory_rate", "min_commission", "vat")})


# --- accounts ---------------------------------------------------------------
def list_accounts(con) -> list[dict]:
    rows = con.execute("SELECT a.*, (SELECT COUNT(*) FROM txns t WHERE t.book=a.id) AS txn_count "
                       "FROM accounts a ORDER BY last_used IS NULL, last_used DESC, created_at")
    return [dict(r) for r in rows]


def get_account(con, acc_id: str) -> dict | None:
    r = con.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
    return dict(r) if r else None


def create_account(con, label, kind, broker_id="", account_no="", sandbox=False,
                   price_source="yahoo", remember=True) -> str:
    acc_id = secrets.token_hex(6)
    with con:
        con.execute("INSERT INTO accounts(id,label,kind,broker_id,account_no,sandbox,price_source,remember) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (acc_id, label, kind, broker_id, account_no, int(sandbox), price_source, int(remember)))
    return acc_id


def update_account(con, acc_id: str, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("label", "price_source", "remember")}
    if not allowed:
        return
    with con:
        con.execute(f"UPDATE accounts SET {', '.join(f'{k}=?' for k in allowed)} WHERE id=?",
                    (*allowed.values(), acc_id))


def touch_account(con, acc_id: str) -> None:
    with con:
        con.execute("UPDATE accounts SET last_used=datetime('now','localtime') WHERE id=?", (acc_id,))


def delete_account(con, acc_id: str) -> None:
    with con:
        con.execute("DELETE FROM txns WHERE book=?", (acc_id,))
        con.execute("DELETE FROM accounts WHERE id=?", (acc_id,))


# --- transactions (always scoped to a book) ---------------------------------
def list_txns(con, book: str, symbol: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM txns WHERE book=?", [book]
    if symbol:
        q += " AND symbol=?"
        args.append(symbol.upper())
    return [dict(r) for r in con.execute(q + " ORDER BY date, id", args)]


def get_txn(con, book: str, txn_id: int) -> dict | None:
    r = con.execute("SELECT * FROM txns WHERE id=? AND book=?", (txn_id, book)).fetchone()
    return dict(r) if r else None


def as_txns(rows: list[dict]) -> list[Txn]:
    return [Txn(r["id"], r["date"], r["symbol"], r["side"], r["qty"], r["price"], r["fee"], r["note"]) for r in rows]


def _fee(t):
    return None if t.get("fee") in (None, "") else float(t["fee"])


def add_txn(con, book: str, t: dict, source="manual", external_id=None) -> int | None:
    with con:
        cur = con.execute(
            "INSERT OR IGNORE INTO txns(book,date,symbol,side,qty,price,fee,source,external_id,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (book, t["date"], t["symbol"].upper().strip(), t["side"].upper(), float(t["qty"]),
             float(t["price"]), _fee(t), source, external_id, t.get("note", "") or ""))
    return cur.lastrowid if cur.rowcount else None


def update_txn(con, book: str, txn_id: int, t: dict) -> None:
    with con:
        con.execute("UPDATE txns SET date=?, symbol=?, side=?, qty=?, price=?, fee=?, note=? WHERE id=? AND book=?",
                    (t["date"], t["symbol"].upper().strip(), t["side"].upper(), float(t["qty"]),
                     float(t["price"]), _fee(t), t.get("note", "") or "", txn_id, book))


def delete_txn(con, book: str, txn_id: int) -> None:
    with con:
        con.execute("DELETE FROM txns WHERE id=? AND book=?", (txn_id, book))


def wipe_book(con, book: str) -> None:
    with con:
        con.execute("DELETE FROM txns WHERE book=?", (book,))


# --- watchlist (shared across accounts) ---------------------------------------
def get_watchlist(con) -> list[str]:
    return [r["symbol"] for r in con.execute("SELECT symbol FROM watchlist ORDER BY position, symbol")]


def set_watchlist(con, symbols: list[str]) -> list[str]:
    with con:
        con.execute("DELETE FROM watchlist")
        for i, s in enumerate(dict.fromkeys(x.upper().strip() for x in symbols if x.strip())):
            con.execute("INSERT INTO watchlist(symbol, position) VALUES(?,?)", (s, i))
    return get_watchlist(con)


def log(con, kind: str, detail: str) -> None:
    with con:
        con.execute("INSERT INTO sync_log(kind, detail) VALUES(?,?)", (kind, detail))
