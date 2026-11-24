import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend import app as appmod

H = {"X-App-Token": appmod.TOKEN}
c = TestClient(appmod.app, base_url=f"http://127.0.0.1:{appmod.PORT}")


@pytest.fixture()
def two_accounts():
    a = c.post("/api/accounts", headers=H, json={"label": "ทดสอบ A", "price_source": "demo"}).json()["account"]["id"]
    b = c.post("/api/accounts", headers=H, json={"label": "ทดสอบ B", "price_source": "demo"}).json()["account"]["id"]
    yield a, b
    for i in (a, b):
        c.delete(f"/api/accounts/{i}?confirm=DELETE", headers=H)


def test_rejects_without_token():
    assert c.get("/api/session").status_code == 401


def test_rejects_foreign_host():
    assert c.get("/api/session", headers={**H, "host": "evil.example:1"}).status_code == 403


def test_logged_out_blocks_data():
    c.post("/api/logout", headers=H)
    r = c.get("/api/positions", headers=H)
    assert r.status_code == 401 and r.json()["code"] == "LOGGED_OUT"


def test_books_are_separate(two_accounts):
    a, b = two_accounts
    c.post("/api/login", headers=H, json={"account_id": a})
    assert c.post("/api/txns", headers=H, json={"date": "2024-01-01", "symbol": "PTT", "side": "BUY", "qty": 100, "price": 30}).status_code == 200
    c.post("/api/login", headers=H, json={"account_id": b})
    assert c.get("/api/txns", headers=H).json() == []
    c.post("/api/login", headers=H, json={"account_id": a})
    assert len(c.get("/api/txns", headers=H).json()) == 1


def test_secret_never_returned(two_accounts):
    c.post("/api/login", headers=H, json={"account_id": two_accounts[0]})
    for path in ("/api/session", "/api/status"):
        assert "app_secret" not in c.get(path, headers=H).text


def test_export_and_oversell(two_accounts):
    c.post("/api/login", headers=H, json={"account_id": two_accounts[0]})
    r = c.post("/api/txns", headers=H, json={"date": "2020-01-01", "symbol": "ZZZ", "side": "SELL", "qty": 100, "price": 1})
    assert r.status_code == 400
    x = c.get("/api/export.xlsx", headers=H)
    assert x.status_code == 200
    assert load_workbook(io.BytesIO(x.content)).sheetnames[0] == "สรุปพอร์ต"


def test_order_needs_api_account(two_accounts):
    c.post("/api/login", headers=H, json={"account_id": two_accounts[0]})
    r = c.post("/api/orders", headers=H, json={"side": "BUY", "symbol": "PTT", "volume": 100, "price": 33.25, "pin": "1234", "confirm": True})
    assert r.status_code == 409


def test_new_api_account_with_bad_key_is_rolled_back():
    before = len(c.get("/api/session", headers=H).json()["accounts"])
    r = c.post("/api/login", headers=H, json={"app_id": "x", "app_secret": "bad", "app_code": "y",
                                               "broker_id": "013", "account_no": "1234567", "remember": False})
    assert r.status_code in (400, 502)
    assert len(c.get("/api/session", headers=H).json()["accounts"]) == before
