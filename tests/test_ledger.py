import pytest

from backend.ledger import FeeConfig, LedgerError, Txn, build_positions, simulate_sell

NOFEE = FeeConfig(commission_rate=0, regulatory_rate=0, vat=0)


def tx(i, d, side, q, p, sym="PTT", fee=None):
    return Txn(i, d, sym, side, q, p, fee)


def user_example():
    return [tx(1, "2024-01-01", "BUY", 100, 40), tx(2, "2024-02-01", "BUY", 100, 45),
            tx(3, "2024-03-01", "BUY", 100, 50)]


def test_average_before_sale():
    p = build_positions(user_example(), NOFEE)["PTT"]
    assert p.qty == 300 and p.avg_cost == pytest.approx(45)


def test_fifo_cuts_oldest_lot_and_avg_jumps():
    p = build_positions(user_example() + [tx(4, "2024-04-01", "SELL", 100, 45)], NOFEE)["PTT"]
    assert p.realized_fifo == pytest.approx(500)      # broker shows +5/share
    assert p.realized_avg == pytest.approx(0)          # average-cost view: break-even
    assert p.avg_cost == pytest.approx(47.5)           # remaining jumps to 47.5
    s = p.summary(45, NOFEE)
    assert s["unrealized"] == pytest.approx(-500)      # looks red...
    assert s["lifetime_pnl"] == pytest.approx(0)       # ...but overall flat


def test_partial_lot_and_fees():
    fees = FeeConfig()
    p = build_positions(user_example() + [tx(4, "2024-04-01", "SELL", 150, 48)], fees)["PTT"]
    assert p.qty == 150
    assert [l.qty for l in p.lots] == [50, 100]
    buy_fee = fees.fee(4500)
    assert p.lots[0].cost == pytest.approx((4500 + buy_fee) / 2, abs=0.01)


def test_oversell_rejected():
    with pytest.raises(LedgerError):
        build_positions([tx(1, "2024-01-01", "BUY", 100, 10), tx(2, "2024-01-02", "SELL", 200, 10)], NOFEE)


def test_same_day_buy_then_sell():
    p = build_positions([tx(2, "2024-01-01", "SELL", 100, 11), tx(1, "2024-01-01", "BUY", 100, 10)], NOFEE)["PTT"]
    assert p.realized_fifo == pytest.approx(100)


def test_simulate_does_not_mutate():
    p = build_positions(user_example(), NOFEE)["PTT"]
    r = simulate_sell(p, 100, 45, NOFEE)
    assert r["pnl_fifo"] == pytest.approx(500)
    assert r["remaining_avg_after"] == pytest.approx(47.5)
    assert r["breakeven_all"] == pytest.approx(45)
    assert p.qty == 300 and len(p.lots) == 3


def test_fee_formula():
    f = FeeConfig()
    assert f.fee(100_000) == pytest.approx(round((157 + 7) * 1.07, 2))


def test_dividend_counts_in_lifetime():
    p = build_positions(user_example() + [tx(4, "2024-05-01", "DIV", 300, 1.0, fee=30)], NOFEE)["PTT"]
    assert p.summary(45, NOFEE)["lifetime_pnl"] == pytest.approx(270)
