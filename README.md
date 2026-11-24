# Stock Note

แอปดูพอร์ตหุ้นไทยแบบแยกทุกล็อตที่ซื้อ เห็นก่อนขายว่าโบรกจะตัดล็อตไหน (FIFO) และกำไรจริงทั้งก้อนเท่าไหร่

**ดาวน์โหลด:** https://woraphontrangpanich-jpg.github.io/stocknote/
หรือ [StockNote-windows.zip](https://github.com/woraphontrangpanich-jpg/stocknote/releases/latest/download/StockNote-windows.zip) (Windows 10/11 ไม่ต้องติดตั้ง Python)

## สร้างตัวติดตั้งเอง (สำหรับนักพัฒนา)

```
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller launcher.pyw --noconfirm --clean --windowed --onedir --name StockNote --icon frontend/app.ico --add-data "frontend;frontend" --paths . --hidden-import backend.app --collect-submodules uvicorn --collect-submodules settrade_v2 --collect-submodules keyring --collect-submodules backend --exclude-module PIL --exclude-module pytest --exclude-module tkinter
```

ไฟล์จะอยู่ใน `dist/StockNote` ข้อมูลของเวอร์ชัน exe เก็บที่ `%LOCALAPPDATA%\StockNote`

แอปติดตามพอร์ตหุ้นไทยแบบแยกล็อต รันบนเครื่องตัวเอง (localhost) ใช้ได้กับทุกโบรก

## เปิดใช้งาน

- ดับเบิลคลิกไอคอน **Stock Note** บนหน้าจอหรือใน Start Menu แอปจะเปิดเป็นหน้าต่างของตัวเอง
- ปิดหน้าต่างแล้วโปรแกรมจะหยุดทำงานเอง
- ถ้าไอคอนหายหรือย้ายโฟลเดอร์ ให้คลิกขวาที่ `install-shortcut.ps1` แล้วเลือก Run with PowerShell เพื่อสร้างไอคอนใหม่
- หรือดับเบิลคลิก `start.bat` ก็ได้ (ครั้งแรกจะติดตั้งไลบรารีให้อัตโนมัติ ต้องมี Python 3.10 ขึ้นไป)
- ถ้าเปิดไม่ขึ้น ดูสาเหตุได้ใน `data/launcher.log`

## เข้าสู่ระบบและบัญชี

- เปิดแอปมาจะเจอหน้าเข้าสู่ระบบก่อนเสมอ เลือกบัญชีที่บันทึกไว้ หรือเพิ่มบัญชีใหม่
- บัญชีแบบเชื่อม API: ใส่ App ID, App Secret, App Code, รหัสโบรก และเลขบัญชี ติ๊ก "จำ key" เพื่อไม่ต้องใส่ใหม่
- บัญชีแบบกรอกเอง: สำหรับโบรกที่ไม่มี API (เช่น กรุงศรี) ใช้ราคาล่าช้าฟรี
- แต่ละบัญชีมีสมุดล็อตแยกกัน สลับบัญชีหรือออกจากระบบได้จากปุ่มชื่อบัญชีมุมขวาบน
- UOB ใช้ผ่าน UOB Kay Hian (026) และ SCB ใช้ผ่าน InnovestX (023) ซึ่งรองรับ API ส่วน TTB ไม่มี

## สิ่งที่ทำได้

- สมุดล็อต (แยกทุกล็อตที่ซื้อ): กรอกรายการเอง หรือนำเข้า .xlsx/.csv (มีไฟล์ตัวอย่างในหน้าสมุดรายการ)
- ดู 3 มุมพร้อมกัน: ต้นทุนเฉลี่ย, กำไรแบบ FIFO (ตรงกับโบรก), กำไรรวมตลอดอายุ
- กองล็อต + จำลองการขาย: เห็นว่าล็อตไหนโดนตัด ได้เงินสุทธิเท่าไหร่ ต้นทุนที่เหลือเปลี่ยนเป็นเท่าไหร่
- กราฟแท่งเทียน SMA, EMA, Bollinger, RSI, MACD, Fibonacci อัตโนมัติ และเส้นต้นทุนของแต่ละล็อต
- ดาวน์โหลด Excel ที่มีสูตรจริง 5 ชีต
- เชื่อม Settrade Open API (เฉพาะโบรกที่รองรับ) เพื่อดึงรายการซื้อขายของวันนี้ เทียบยอดกับพอร์ต และส่งคำสั่ง

## แหล่งราคา

| แหล่ง | ใช้เมื่อ |
|---|---|
| ข้อมูลจำลอง | ลองเล่น ไม่ต้องต่อเน็ต |
| ราคาล่าช้าฟรี | โบรกไม่รองรับ Open API (เช่น กรุงศรี, SCB) |
| Settrade Open API | โบรก BEYOND, Globlex, INVX, KGI, Trinity, UOBKH |

## ความปลอดภัย

- เซิร์ฟเวอร์รับเฉพาะ 127.0.0.1 ทุก API ต้องมี token ที่สุ่มใหม่ทุกครั้งที่เปิดแอป และตรวจ Host header
- App ID / Secret เก็บใน Windows Credential Manager ไม่ส่งกลับไปที่หน้าเว็บ
- PIN ซื้อขายใช้ครั้งเดียวต่อคำสั่ง ไม่ถูกบันทึกที่ใด
- ข้อมูลอยู่ใน `data/ledger.db` สำรองวันละไฟล์ใน `data/backups` (เก็บ 30 วัน)

## ข้อจำกัด

- Settrade API ดึงรายการซื้อขายได้เฉพาะวันนี้ ถ้าซื้อขายผ่าน Streaming ให้เปิดแอปแล้วกด "ดึงรายการวันนี้จากโบรก" ภายในวันนั้น ถ้าลืม แอปจะเตือนเมื่อยอดไม่ตรง
- การส่งคำสั่งจริงยังไม่ได้ทดสอบกับบัญชีจริง ให้ลองบน Sandbox ก่อน
- ยังไม่รองรับการแตกพาร์/เพิ่มทุน (ปรับด้วยการแก้รายการเองไปก่อน)

## ทดสอบ

```
.venv\Scripts\python -m pytest -q tests
```
