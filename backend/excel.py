"""Excel export (real formulas, styled) and CSV/XLSX import."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

INK = "16202A"
PAPER = "F6F3EC"
GAIN = "2E8B62"
LOSS = "C6474C"
AMBER = "E9B44C"
FONT = "Tahoma"   # renders Thai well on every Windows install

H_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
H_FILL = PatternFill("solid", fgColor=INK)
B_FONT = Font(name=FONT, size=10)
T_FONT = Font(name=FONT, bold=True, size=14, color=INK)
THIN = Side(style="thin", color="D9D4C7")
MONEY = '#,##0.00;[Red]-#,##0.00'
PRICE = '#,##0.00##'
QTY = '#,##0'
PCT = '0.00%;[Red]-0.00%'


def _sheet(ws, title, headers, widths):
    ws.title = title
    ws.sheet_view.showGridLines = False
    ws.append(headers)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(row=1, column=i)
        c.font, c.fill = H_FONT, H_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "B2"


def _style_rows(ws, first, last, formats):
    for r in range(first, last + 1):
        for col, fmt in formats.items():
            c = ws[f"{col}{r}"]
            c.font = B_FONT
            c.border = Border(bottom=THIN)
            if fmt:
                c.number_format = fmt


def _pnl_colors(ws, rng):
    ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"],
                                                  font=Font(name=FONT, color=GAIN, bold=True)))
    ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"],
                                                  font=Font(name=FONT, color=LOSS, bold=True)))


def _table(ws, name, last_row, last_col):
    if last_row < 2:
        return
    t = Table(displayName=name, ref=f"A1:{get_column_letter(last_col)}{last_row}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(t)


def build_workbook(positions: dict, prices: dict, txns: list[dict], fees) -> bytes:
    wb = Workbook()

    # ---------------- Lots (source of truth for formulas) ----------------
    lots_ws = wb.active
    _sheet(lots_ws, "ล็อตที่ถืออยู่",
           ["หุ้น", "วันที่ซื้อ", "จำนวนคงเหลือ", "ราคาซื้อ", "ต้นทุนรวมค่าธรรมเนียม",
            "ต้นทุน/หุ้น", "ราคาตลาด", "มูลค่าตลาด", "กำไร/ขาดทุน", "%", "ลำดับตัด FIFO"],
           [10, 13, 13, 11, 16, 12, 11, 15, 15, 10, 11])
    r = 2
    for sym in sorted(positions):
        p = positions[sym]
        for order, lot in enumerate(p.lots, 1):
            lots_ws.append([sym, lot.date[:10], lot.qty, lot.price, round(lot.cost, 2),
                            f"=E{r}/C{r}", prices.get(sym), f"=C{r}*G{r}",
                            f"=H{r}-E{r}", f'=IF(E{r}=0,0,I{r}/E{r})', order])
            r += 1
    last_lot = r - 1
    _style_rows(lots_ws, 2, last_lot, {"A": None, "B": None, "C": QTY, "D": PRICE, "E": MONEY,
                                       "F": PRICE, "G": PRICE, "H": MONEY, "I": MONEY,
                                       "J": PCT, "K": "0"})
    for row in range(2, last_lot + 1):
        lots_ws[f"G{row}"].fill = PatternFill("solid", fgColor="FFF6DF")  # editable input
    _pnl_colors(lots_ws, f"I2:J{max(last_lot, 2)}")
    _table(lots_ws, "Lots", last_lot, 11)

    # ---------------- Summary ---------------------------------------------
    sm = wb.create_sheet("สรุปพอร์ต", 0)
    sm.sheet_view.showGridLines = False
    sm["A1"] = "สรุปพอร์ตหุ้น"
    sm["A1"].font = T_FONT
    sm["A2"] = f"ออกรายงาน {datetime.now():%d/%m/%Y %H:%M}  ·  ราคาตลาดแก้ได้ในชีต ล็อตที่ถืออยู่ (ช่องสีเหลือง)"
    sm["A2"].font = Font(name=FONT, size=9, color="7A7466")
    headers = ["หุ้น", "จำนวนหุ้น", "ต้นทุนเฉลี่ย", "ต้นทุนรวม", "ราคาตลาด", "มูลค่าตลาด",
               "กำไรที่ยังไม่ขาย", "%", "กำไรที่ขายแล้ว (FIFO)", "เงินปันผล", "กำไรรวมตลอดอายุ", "สัดส่วนพอร์ต"]
    widths = [10, 12, 12, 15, 11, 15, 16, 9, 18, 12, 18, 12]
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = sm.cell(row=4, column=i, value=h)
        c.font, c.fill = H_FONT, H_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sm.column_dimensions[get_column_letter(i)].width = w
    sm.row_dimensions[4].height = 32
    sm.freeze_panes = "B5"
    L = "'ล็อตที่ถืออยู่'"
    start = 5
    syms = sorted(positions)
    for i, sym in enumerate(syms):
        p = positions[sym]
        row = start + i
        sm.append([
            sym,
            f'=SUMIF({L}!$A:$A,A{row},{L}!$C:$C)',
            f'=IF(B{row}=0,0,D{row}/B{row})',
            f'=SUMIF({L}!$A:$A,A{row},{L}!$E:$E)',
            prices.get(sym),
            f'=B{row}*E{row}',
            f'=F{row}-D{row}',
            f'=IF(D{row}=0,0,G{row}/D{row})',
            round(p.realized_fifo, 2),
            round(p.dividends, 2),
            f'=G{row}+I{row}+J{row}',
            None,  # filled below once total row known
        ])
    end = start + len(syms) - 1
    tot = end + 1
    if syms:
        for row in range(start, end + 1):
            sm[f"L{row}"] = f'=IF($F${tot}=0,0,F{row}/$F${tot})'
        sm.append(["รวม", None, None, f"=SUM(D{start}:D{end})", None, f"=SUM(F{start}:F{end})",
                   f"=SUM(G{start}:G{end})", f'=IF(D{tot}=0,0,G{tot}/D{tot})',
                   f"=SUM(I{start}:I{end})", f"=SUM(J{start}:J{end})", f"=SUM(K{start}:K{end})", None])
        for col in "ABCDEFGHIJKL":
            c = sm[f"{col}{tot}"]
            c.font = Font(name=FONT, bold=True, size=10)
            c.border = Border(top=Side(style="medium", color=INK))
    _style_rows(sm, start, end, {"A": None, "B": QTY, "C": PRICE, "D": MONEY, "E": PRICE,
                                 "F": MONEY, "G": MONEY, "H": PCT, "I": MONEY, "J": MONEY,
                                 "K": MONEY, "L": PCT})
    for col, fmt in {"D": MONEY, "F": MONEY, "G": MONEY, "H": PCT, "I": MONEY,
                     "J": MONEY, "K": MONEY}.items():
        sm[f"{col}{tot}"].number_format = fmt
    _pnl_colors(sm, f"G{start}:K{max(tot, start)}")
    for row in range(start, end + 1):
        sm[f"A{row}"].font = Font(name=FONT, bold=True, size=10)

    # ---------------- Transactions ------------------------------------------
    tx = wb.create_sheet("ประวัติซื้อขาย")
    _sheet(tx, "ประวัติซื้อขาย",
           ["วันที่", "หุ้น", "ประเภท", "จำนวน", "ราคา", "มูลค่า", "ค่าธรรมเนียม+VAT",
            "เงินเข้า(+)/ออก(-)", "แหล่งที่มา", "หมายเหตุ"],
           [13, 10, 10, 12, 11, 15, 15, 17, 11, 24])
    side_th = {"BUY": "ซื้อ", "SELL": "ขาย", "DIV": "ปันผล"}
    for i, t in enumerate(txns, start=2):
        fee = t["fee"] if t["fee"] is not None else (fees.fee(t["qty"] * t["price"]) if t["side"] != "DIV" else 0)
        sign = "-" if t["side"] == "BUY" else ""
        tx.append([t["date"][:10], t["symbol"], side_th[t["side"]], t["qty"], t["price"],
                   f"=D{i}*E{i}", round(fee, 2),
                   f"={sign}(F{i}{'+' if t['side'] == 'BUY' else '-'}G{i})",
                   t["source"], t["note"]])
    last_tx = len(txns) + 1
    _style_rows(tx, 2, last_tx, {"A": None, "B": None, "C": None, "D": QTY, "E": PRICE,
                                 "F": MONEY, "G": MONEY, "H": MONEY, "I": None, "J": None})
    _pnl_colors(tx, f"H2:H{max(last_tx, 2)}")
    _table(tx, "Transactions", last_tx, 10)

    # ---------------- Realized (FIFO fills) -----------------------------------
    rz = wb.create_sheet("กำไรที่ขายแล้ว")
    _sheet(rz, "กำไรที่ขายแล้ว",
           ["วันที่ขาย", "หุ้น", "ล็อตวันที่ซื้อ", "จำนวน", "ราคาซื้อ", "ต้นทุนล็อต",
            "เงินที่ได้สุทธิ", "กำไร/ขาดทุน", "%"],
           [13, 10, 14, 12, 11, 15, 15, 15, 10])
    r = 2
    for sym in sorted(positions):
        for h in positions[sym].history:
            for f in h.get("fills", []):
                rz.append([h["date"][:10], sym, f["lot_date"][:10], f["qty"], f["buy_price"],
                           f["cost"], f["proceeds"], f"=G{r}-F{r}", f"=IF(F{r}=0,0,H{r}/F{r})"])
                r += 1
    last_rz = r - 1
    _style_rows(rz, 2, last_rz, {"A": None, "B": None, "C": None, "D": QTY, "E": PRICE,
                                 "F": MONEY, "G": MONEY, "H": MONEY, "I": PCT})
    _pnl_colors(rz, f"H2:I{max(last_rz, 2)}")
    _table(rz, "Realized", last_rz, 9)

    # ---------------- How to read ----------------------------------------------
    hw = wb.create_sheet("วิธีอ่าน")
    hw.sheet_view.showGridLines = False
    hw.column_dimensions["A"].width = 95
    lines = [
        ("วิธีอ่านรายงานนี้", T_FONT),
        ("ต้นทุนเฉลี่ย = ต้นทุนรวมของล็อตที่ยังถือ ÷ จำนวนหุ้นที่ยังถือ (รวมค่าคอมและ VAT แล้ว)", B_FONT),
        ("FIFO = เวลาขาย โบรกจะตัดล็อตที่ซื้อเก่าที่สุดออกก่อน กำไรที่ขายแล้วในรายงานนี้คิดแบบเดียวกับโบรก", B_FONT),
        ("กำไรรวมตลอดอายุ = กำไรที่ยังไม่ขาย + กำไรที่ขายแล้ว + เงินปันผล  ตัวนี้ไม่เด้งไปมาตามวิธีตัดล็อต", B_FONT),
        (f"ค่าธรรมเนียมที่ใช้: ค่าคอม {fees.commission_rate*100:.3f}% + ค่าธรรมเนียมตลาด {fees.regulatory_rate*100:.4f}% + VAT {fees.vat*100:.0f}%", B_FONT),
        ("แก้ราคาตลาดในชีต ล็อตที่ถืออยู่ คอลัมน์ G (สีเหลือง) แล้วตัวเลขทุกชีตจะคำนวณใหม่เอง", B_FONT),
        ("กำไรที่ยังไม่ขายในไฟล์นี้ยังไม่หักค่าธรรมเนียมขาย ในแอปจะหักค่าธรรมเนียมขายโดยประมาณให้แล้ว ตัวเลขจึงต่างกันเล็กน้อย", B_FONT),
    ]
    for i, (text, font) in enumerate(lines, 1):
        hw.cell(row=i, column=1, value=text).font = font
        hw.row_dimensions[i].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- import
ALIASES = {
    "date": {"date", "วันที่", "trade date", "tradedate"},
    "symbol": {"symbol", "หุ้น", "stock", "ชื่อหุ้น"},
    "side": {"side", "ประเภท", "type", "buy/sell", "ซื้อ/ขาย"},
    "qty": {"qty", "จำนวน", "volume", "shares", "quantity"},
    "price": {"price", "ราคา"},
    "fee": {"fee", "ค่าธรรมเนียม", "commission", "ค่าธรรมเนียม+vat"},
    "note": {"note", "หมายเหตุ"},
}
SIDES = {"buy": "BUY", "b": "BUY", "ซื้อ": "BUY", "sell": "SELL", "s": "SELL", "ขาย": "SELL",
         "div": "DIV", "dividend": "DIV", "ปันผล": "DIV"}


def _norm_date(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            d = datetime.strptime(s[:10], fmt)
            if d.year > 2400:          # Buddhist year
                d = d.replace(year=d.year - 543)
            return d.date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"อ่านวันที่ไม่ออก: {s!r} (ใช้ 2024-03-15 หรือ 15/03/2024)")


def parse_rows(filename: str, data: bytes) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("ไฟล์ว่าง")
    header = [str(h or "").strip().lower() for h in rows[0]]
    idx = {}
    for key, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names:
                idx[key] = i
                break
    missing = [k for k in ("date", "symbol", "side", "qty", "price") if k not in idx]
    if missing:
        raise ValueError("ไม่พบคอลัมน์: " + ", ".join(missing) +
                         " (หัวตารางต้องมี date, symbol, side, qty, price)")
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if not any(c not in (None, "") for c in r):
            continue
        try:
            side = SIDES.get(str(r[idx["side"]]).strip().lower())
            if not side:
                raise ValueError(f"ประเภทไม่ถูกต้อง: {r[idx['side']]!r}")
            fee = r[idx["fee"]] if "fee" in idx else None
            out.append({
                "date": _norm_date(r[idx["date"]]),
                "symbol": str(r[idx["symbol"]]).strip().upper(),
                "side": side,
                "qty": float(str(r[idx["qty"]]).replace(",", "")),
                "price": float(str(r[idx["price"]]).replace(",", "")),
                "fee": None if fee in (None, "") else float(str(fee).replace(",", "")),
                "note": str(r[idx["note"]] or "") if "note" in idx else "",
            })
        except (ValueError, IndexError) as e:
            raise ValueError(f"แถว {n}: {e}") from None
    return out


def template_csv() -> bytes:
    return ("date,symbol,side,qty,price,fee,note\n"
            "2024-01-15,PTT,BUY,100,40,,ล็อตแรก\n"
            "2024-03-02,PTT,BUY,100,45,,\n"
            "2024-06-20,PTT,BUY,100,50,,\n"
            "2024-08-01,PTT,SELL,100,45,,\n").encode("utf-8-sig")
