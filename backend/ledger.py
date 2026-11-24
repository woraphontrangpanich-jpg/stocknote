"""Lot ledger engine.

Replays transactions per symbol in date order and keeps open lots FIFO,
matching how Thai brokers (and Streaming) cut lots on a sale. Next to that
it reports the two other views people need to stop being confused:

* average cost  - total cost still held / shares held
* lifetime P/L  - everything received + market value - everything paid

All money is in THB. Buy fees are folded into the lot cost, sell fees are
taken out of the proceeds, so "realized" is what actually hit the account.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Iterable

VAT = 0.07


@dataclass
class FeeConfig:
    commission_rate: float = 0.00157   # 0.157 %, typical internet cash account
    regulatory_rate: float = 0.00007   # trading fee + clearing + TSD ~ 0.007 %
    min_commission: float = 0.0        # some brokers charge a minimum per order
    vat: float = VAT

    def fee(self, gross: float) -> float:
        if gross <= 0:
            return 0.0
        commission = max(gross * self.commission_rate, self.min_commission)
        regulatory = gross * self.regulatory_rate
        return round((commission + regulatory) * (1 + self.vat), 2)


@dataclass
class Txn:
    id: int
    date: str          # ISO yyyy-mm-dd (or with time)
    symbol: str
    side: str          # BUY | SELL | DIV
    qty: float
    price: float
    fee: float | None = None   # None -> computed from FeeConfig
    note: str = ""


@dataclass
class Lot:
    txn_id: int
    date: str
    qty: float          # shares still open in this lot
    orig_qty: float
    price: float        # buy price per share
    cost: float         # cost of the open part, fee included

    @property
    def unit_cost(self) -> float:
        return self.cost / self.qty if self.qty else 0.0


@dataclass
class Fill:
    """One lot (or part of it) consumed by a sale."""
    lot_txn_id: int
    lot_date: str
    qty: float
    buy_price: float
    cost: float
    proceeds: float
    pnl: float


@dataclass
class Position:
    symbol: str
    lots: list[Lot] = field(default_factory=list)
    realized_fifo: float = 0.0
    realized_avg: float = 0.0   # what P/L would be under average-cost cutting
    dividends: float = 0.0
    total_bought: float = 0.0   # cash paid incl. fees
    total_sold: float = 0.0     # cash received net of fees
    fees_paid: float = 0.0
    history: list[dict] = field(default_factory=list)
    _avg_qty: float = 0.0
    _avg_cost: float = 0.0

    @property
    def qty(self) -> float:
        return sum(l.qty for l in self.lots)

    @property
    def cost(self) -> float:
        return sum(l.cost for l in self.lots)

    @property
    def avg_cost(self) -> float:
        q = self.qty
        return self.cost / q if q else 0.0

    def summary(self, market_price: float | None, fees: FeeConfig) -> dict:
        q, c = self.qty, self.cost
        out = {
            "symbol": self.symbol,
            "qty": q,
            "cost": round(c, 2),
            "avg_cost": round(self.avg_cost, 4),
            # average cost if every lot had been averaged in (broker "avg" view)
            "avg_method_cost": round(self._avg_cost / self._avg_qty, 4) if self._avg_qty else 0.0,
            "realized_fifo": round(self.realized_fifo, 2),
            "realized_avg": round(self.realized_avg, 2),
            "dividends": round(self.dividends, 2),
            "total_bought": round(self.total_bought, 2),
            "total_sold": round(self.total_sold, 2),
            "fees_paid": round(self.fees_paid, 2),
            "market_price": market_price,
            "lots": [
                {**asdict(l), "unit_cost": round(l.unit_cost, 4)} for l in self.lots
            ],
        }
        if market_price is not None:
            gross = q * market_price
            net_value = gross - fees.fee(gross)
            out["market_value"] = round(gross, 2)
            out["unrealized"] = round(net_value - c, 2)
            out["lifetime_pnl"] = round(
                self.total_sold + self.dividends + net_value - self.total_bought, 2
            )
            out["lots"] = [
                {
                    **lot,
                    "unrealized": round(
                        lot["qty"] * market_price
                        - fees.fee(lot["qty"] * market_price)
                        - lot["cost"],
                        2,
                    ),
                }
                for lot in out["lots"]
            ]
        return out


class LedgerError(ValueError):
    pass


def _sort_key(t: Txn):
    # same-day: buys before sells so intraday round trips work, then by id
    return (t.date, 0 if t.side == "BUY" else 1, t.id)


def build_positions(txns: Iterable[Txn], fees: FeeConfig) -> dict[str, Position]:
    positions: dict[str, Position] = {}
    for t in sorted(txns, key=_sort_key):
        sym = t.symbol.upper()
        p = positions.setdefault(sym, Position(sym))
        gross = t.qty * t.price
        if t.side == "BUY":
            fee = t.fee if t.fee is not None else fees.fee(gross)
            cost = gross + fee
            p.lots.append(Lot(t.id, t.date, t.qty, t.qty, t.price, cost))
            p.total_bought += cost
            p.fees_paid += fee
            p._avg_qty += t.qty
            p._avg_cost += cost
            p.history.append({"txn_id": t.id, "date": t.date, "side": "BUY",
                              "qty": t.qty, "price": t.price, "fee": fee,
                              "amount": round(-cost, 2)})
        elif t.side == "SELL":
            if t.qty > p.qty + 1e-9:
                raise LedgerError(
                    f"{sym}: sale of {t.qty:g} on {t.date} exceeds the {p.qty:g} shares held"
                )
            fee = t.fee if t.fee is not None else fees.fee(gross)
            proceeds = gross - fee
            fills = consume_fifo(p.lots, t.qty, proceeds)
            p.lots = [l for l in p.lots if l.qty > 1e-9]
            pnl = sum(f.pnl for f in fills)
            p.realized_fifo += pnl
            # average-cost comparison
            avg_unit = p._avg_cost / p._avg_qty if p._avg_qty else 0.0
            p.realized_avg += proceeds - avg_unit * t.qty
            p._avg_cost -= avg_unit * t.qty
            p._avg_qty -= t.qty
            p.total_sold += proceeds
            p.fees_paid += fee
            p.history.append({"txn_id": t.id, "date": t.date, "side": "SELL",
                              "qty": t.qty, "price": t.price, "fee": fee,
                              "amount": round(proceeds, 2), "pnl": round(pnl, 2),
                              "fills": [asdict(f) for f in fills]})
        elif t.side == "DIV":
            tax = t.fee or 0.0
            amount = gross - tax
            p.dividends += amount
            p.history.append({"txn_id": t.id, "date": t.date, "side": "DIV",
                              "qty": t.qty, "price": t.price, "fee": tax,
                              "amount": round(amount, 2)})
        else:
            raise LedgerError(f"Unknown side {t.side!r}")
    return positions


def consume_fifo(lots: list[Lot], qty: float, proceeds: float) -> list[Fill]:
    """Mutates lots (oldest first). Proceeds are split pro rata by shares."""
    fills: list[Fill] = []
    remaining = qty
    for lot in lots:
        if remaining <= 1e-9:
            break
        take = min(lot.qty, remaining)
        cost = lot.unit_cost * take
        part = proceeds * (take / qty)
        fills.append(Fill(lot.txn_id, lot.date, take, lot.price,
                          round(cost, 2), round(part, 2), round(part - cost, 2)))
        lot.cost -= cost
        lot.qty -= take
        remaining -= take
    return fills


def simulate_sell(position: Position, qty: float, price: float, fees: FeeConfig) -> dict:
    """What happens if I sell `qty` at `price` right now - without touching data."""
    if qty <= 0:
        raise LedgerError("Quantity must be more than 0")
    if qty > position.qty + 1e-9:
        raise LedgerError(f"You hold {position.qty:g} shares, cannot sell {qty:g}")
    lots = [Lot(l.txn_id, l.date, l.qty, l.orig_qty, l.price, l.cost) for l in position.lots]
    gross = qty * price
    fee = fees.fee(gross)
    proceeds = gross - fee
    fills = consume_fifo(lots, qty, proceeds)
    left = [l for l in lots if l.qty > 1e-9]
    left_qty = sum(l.qty for l in left)
    left_cost = sum(l.cost for l in left)
    sold_cost = sum(f.cost for f in fills)
    # price at which the sold shares exactly break even after fees
    r = (fees.commission_rate + fees.regulatory_rate) * (1 + fees.vat)
    breakeven_sold = sold_cost / (qty * (1 - r)) if qty else 0.0
    breakeven_all = position.cost / (position.qty * (1 - r)) if position.qty else 0.0
    return {
        "qty": qty,
        "price": price,
        "gross": round(gross, 2),
        "fee": fee,
        "proceeds": round(proceeds, 2),
        "pnl_fifo": round(sum(f.pnl for f in fills), 2),
        "pnl_vs_avg": round(proceeds - position.avg_cost * qty, 2),
        "fills": [asdict(f) for f in fills],
        "remaining_qty": left_qty,
        "remaining_cost": round(left_cost, 2),
        "remaining_avg_before": round(position.avg_cost, 4),
        "remaining_avg_after": round(left_cost / left_qty, 4) if left_qty else 0.0,
        "breakeven_sold": round(breakeven_sold, 4),
        "breakeven_all": round(breakeven_all, 4),
    }
