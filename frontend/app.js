import { PriceChart } from "./chart.js";

// ------------------------------------------------------------------ utils
const TOKEN = document.querySelector('meta[name="app-token"]').content;
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf2 = new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 });
const money = v => (v === null || v === undefined || Number.isNaN(v)) ? "–" : nf2.format(v);
const qty = v => nf0.format(v);
const signed = v => (v === null || v === undefined) ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf2.format(Math.abs(v));
const cls = v => v > 0 ? "gain" : v < 0 ? "loss" : "";
const pct = (a, b) => b ? (a / b) * 100 : 0;
const pctTxt = v => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) + "%";
const thDate = iso => new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "2-digit" });
const thLong = d => d.toLocaleDateString("th-TH", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const today = () => new Date().toLocaleDateString("sv-SE");
const debounce = (fn, ms = 200) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const SIDE_TH = { BUY: "ซื้อ", SELL: "ขาย", DIV: "ปันผล" };

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const headers = { "X-App-Token": TOKEN, ...(opts.body && !isForm ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch("/api" + path, { ...opts, headers, body: opts.body && !isForm ? JSON.stringify(opts.body) : opts.body });
  if (opts.raw) { if (!res.ok) throw new Error((await res.json()).detail); return res; }
  const data = await res.json().catch(() => null);
  if (res.status === 401 && data?.code === "LOGGED_OUT" && path !== "/session") { state.status = null; renderLogin(); throw new Error("กรุณาเข้าสู่ระบบ"); }
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map(x => `${x.loc?.slice(-1)[0]}: ${x.msg}`).join(", ") : d || `ผิดพลาด ${res.status}`);
  }
  return data;
}

function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.className = "toast", bad ? 5000 : 2600);
}

async function download(path, fallbackName) {
  try {
    const res = await api(path, { raw: true });
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || fallbackName;
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: name }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`ดาวน์โหลด ${name} แล้ว`);
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ state
const state = { status: null, watch: [], quotes: {}, positions: null, chart: null };

async function loadStatus() {
  state.status = await api("/status");
  await refreshSession();
}
async function loadPositions() { state.positions = await api("/positions"); return state.positions; }

// ------------------------------------------------------------------ ticker tape
async function loadWatch() { state.watch = await api("/watchlist"); await refreshQuotes(); }

async function refreshQuotes() {
  const held = (state.positions?.items || []).filter(i => i.qty > 0).map(i => i.symbol);
  const syms = [...new Set([...state.watch, ...held])];
  if (syms.length) { try { state.quotes = await api("/quotes?symbols=" + encodeURIComponent(syms.join(","))); } catch { /* keep */ } }
  renderWatch();
}

function renderWatch() {
  const current = (location.hash.match(/^#\/s\/([^/?]+)/) || [])[1];
  const heldMap = Object.fromEntries((state.positions?.items || []).filter(i => i.qty > 0).map(i => [i.symbol, i.qty]));
  const list = [...new Set([...state.watch, ...Object.keys(heldMap)])];
  $("#watchlist").innerHTML = list.length ? list.map(s => {
    const q = state.quotes[s] || {};
    return `<li><a href="#/s/${esc(s)}" ${s === current ? 'aria-current="page"' : ""}>
      <span class="sym">${esc(s)}</span><span class="px">${money(q.last)}</span>
      <span class="held">${heldMap[s] ? "ถือ " + qty(heldMap[s]) : "ติดตาม"}</span>
      <span class="chg ${cls(q.change)}">${q.pct != null ? pctTxt(q.pct) : ""}</span></a>
      ${state.watch.includes(s) && !heldMap[s] ? `<button class="unpin" data-unpin="${esc(s)}" aria-label="เลิกติดตาม ${esc(s)}" title="เลิกติดตาม">×</button>` : ""}</li>`;
  }).join("") : `<li class="empty-tape">พิมพ์ชื่อหุ้นในช่องด้านขวาเพื่อเริ่มติดตาม</li>`;
}

$("#watchlist").addEventListener("click", async e => {
  const s = e.target.dataset?.unpin; if (!s) return;
  e.preventDefault();
  state.watch = await api("/watchlist", { method: "PUT", body: state.watch.filter(x => x !== s) });
  renderWatch();
});
$("#addSym").addEventListener("submit", async e => {
  e.preventDefault();
  const inp = $("#addSymInput"), s = inp.value.trim().toUpperCase();
  if (!/^[A-Z0-9\-.&]{1,20}$/.test(s)) return toast("ชื่อหุ้นใช้ได้เฉพาะตัวอักษรอังกฤษและตัวเลข", true);
  if (!state.watch.includes(s)) state.watch = await api("/watchlist", { method: "PUT", body: [...state.watch, s] });
  inp.value = ""; inp.blur(); await refreshQuotes(); location.hash = "#/s/" + s;
});
async function togglePin(s) {
  const pinned = state.watch.includes(s);
  state.watch = await api("/watchlist", { method: "PUT", body: pinned ? state.watch.filter(x => x !== s) : [...state.watch, s] });
  renderWatch(); return !pinned;
}

// ------------------------------------------------------------------ login & accounts
const KIND_TH = { api: "เชื่อม API", manual: "กรอกเอง" };
let BROKER_LIST = null;
async function brokers() { return BROKER_LIST ??= await api("/brokers"); }

function showApp(on) {
  $("#login").hidden = on;
  $("#appTop").hidden = !on;
  $("#appLayout").hidden = !on;
}

const KEY_HELP = `
  <details class="help">
    <summary>หา API key ได้จากไหน</summary>
    <ol class="steps">
      <li><span>เข้า <a href="https://streaming.settrade.com" target="_blank" rel="noopener noreferrer">streaming.settrade.com</a> ด้วย username และรหัสผ่านเดียวกับแอป Streaming</span></li>
      <li><span>กดเมนู <b>More</b> แล้วเลือก <b>API Key Management</b></span></li>
      <li><span>กด <b>Generate</b> จะได้ <b>App ID</b> และ <b>App Secret</b> คัดลอก App Secret เก็บไว้ทันที เพราะแสดงครั้งเดียว</span></li>
      <li><span><b>App Code</b> อยู่ในหน้าเดียวกัน ส่วนเลขบัญชีคือเลขบัญชีหุ้นของคุณ</span></li>
    </ol>
    <div class="broker-notes">
      <p><b>UOB</b> ใช้บัญชีหุ้นของ UOB Kay Hian (UOBKH) ซึ่งรองรับ API</p>
      <p><b>InnovestX (SCB)</b> รองรับ API แต่ไม่มีในหน้า streaming.settrade.com ให้ติดต่อ InnovestX เพื่อขอ Settrade Open API key</p>
      <p><b>ttb wealth</b> และ <b>กรุงศรี</b> ยังไม่เปิด API สำหรับหุ้น ให้เพิ่มเป็นบัญชีแบบกรอกเองแทน</p>
    </div>
    <p class="hint">ถ้าไม่เจอเมนู API Key Management แปลว่าโบรกยังไม่เปิดให้บัญชีคุณ ให้โทรถามโบรก</p>
  </details>`;

async function renderLogin(message = "") {
  if (state.chart) { state.chart.destroy(); state.chart = null; }
  showApp(false);
  const [sess, list] = await Promise.all([api("/session"), brokers()]);
  const apiBrokers = list.filter(b => b.api), allBrokers = list;
  const accs = sess.accounts;
  const root = $("#login");
  root.innerHTML = `
    <div class="login">
      <aside class="login-art" aria-hidden="true">
        <div class="brand big"><span class="logo"><i></i><i></i><i></i></span>Stock Note</div>
        <div class="art-stack">
          <div class="art-label art-top">▲ ขายออกจากด้านบนก่อน</div>
          <div class="art-col"><i class="l"></i><i class="g"></i><i class="g"></i><i class="b"></i></div>
          <div class="art-label art-bottom">▼ ซื้อเพิ่มต่อด้านล่าง</div>
        </div>
        <p class="art-copy">เห็นทุกล็อตที่ซื้อไว้ รู้ก่อนขายว่าโบรกจะตัดล็อตไหน และกำไรจริงทั้งก้อนเท่าไหร่</p>
      </aside>

      <section class="login-main">
        <div class="login-inner">
          ${message ? `<div class="notice bad" role="alert">${esc(message)}</div>` : ""}
          ${accs.length ? `
            <h1>เข้าสู่ระบบ</h1>
            <p class="soft lead">เลือกบัญชีที่จะใช้งาน แต่ละบัญชีมีสมุดล็อตแยกกัน</p>
            <ul class="acct-list">${accs.map(a => `
              <li class="acct-card" data-id="${a.id}">
                <div class="acct-ava ${a.kind}" aria-hidden="true">${esc(a.label.slice(0, 1))}</div>
                <div class="acct-info">
                  <div class="acct-name">${esc(a.label)}</div>
                  <div class="acct-meta"><span class="kind ${a.kind}">${KIND_TH[a.kind]}</span>
                    ${a.broker_name ? esc(a.broker_name) : ""} ${a.account_no ? `<span class="num">${esc(a.account_no)}</span>` : ""}
                    ${a.kind === "api" && !a.has_key ? `<span class="warn">ต้องใส่ key ใหม่</span>` : ""}</div>
                </div>
                <button class="btn small" type="button" data-login="${a.id}">เข้าใช้งาน</button>
                ${a.kind === "api" && !a.has_key ? `
                <form class="rekey" data-rekey="${a.id}" hidden autocomplete="off">
                  <label>App ID<input name="app_id" required autocomplete="off" spellcheck="false"></label>
                  <label>App Secret<input name="app_secret" type="password" required autocomplete="off"></label>
                  <label>App Code<input name="app_code" required autocomplete="off" spellcheck="false"></label>
                  <label class="check"><input type="checkbox" name="remember" checked>จำ key ไว้ในเครื่องนี้</label>
                  <button class="btn" type="submit">เข้าสู่ระบบ</button>
                </form>` : ""}
              </li>`).join("")}
            </ul>
            <h2 class="add-title">เพิ่มบัญชีใหม่</h2>` : `
            <h1>ยินดีต้อนรับ</h1>
            <p class="soft lead">เพิ่มบัญชีแรกของคุณ ถ้าโบรกรองรับ Settrade Open API ให้ใส่ API key เพื่อดึงข้อมูลและส่งคำสั่งได้ ถ้าไม่รองรับ ให้เลือกแบบกรอกเอง</p>`}

          <div class="seg wide" role="tablist" aria-label="ประเภทบัญชี">
            <button type="button" role="tab" data-tab="api" aria-selected="true" aria-pressed="true">เชื่อม API key</button>
            <button type="button" role="tab" data-tab="manual" aria-selected="false" aria-pressed="false">ไม่ใช้ API (กรอกเอง)</button>
          </div>

          <form class="login-form" id="apiForm" autocomplete="off">
            <div class="form-grid">
              <label>โบรกเกอร์<select name="broker_id" required>${apiBrokers.map(b => `<option value="${b.id}">${esc(b.name)} (${b.id})</option>`).join("")}</select></label>
              <label>เลขบัญชีหุ้น<input name="account_no" required inputmode="numeric" autocomplete="off" spellcheck="false" placeholder="เช่น 1234567…"></label>
              <label>App ID<input name="app_id" required autocomplete="off" spellcheck="false"></label>
              <label>App Secret<input name="app_secret" type="password" required autocomplete="off"></label>
              <label>App Code<input name="app_code" required autocomplete="off" spellcheck="false"></label>
              <label>ชื่อบัญชี (ไม่ใส่ก็ได้)<input name="label" maxlength="40" autocomplete="off" placeholder="เช่น พอร์ตเงินออม…"></label>
            </div>
            <div class="checks">
              <label class="check"><input type="checkbox" name="remember" checked>จำ key ไว้ในเครื่องนี้</label>
              <label class="check"><input type="checkbox" name="sandbox">ใช้ระบบทดสอบ Sandbox</label>
            </div>
            <p class="hint">ถ้าไม่ติ๊ก "จำ key" แอปจะลืม key เมื่อปิดโปรแกรม และต้องใส่ใหม่ครั้งหน้า</p>
            <button class="btn full" type="submit">เข้าสู่ระบบด้วย API key</button>
            ${KEY_HELP}
          </form>

          <form class="login-form" id="manualForm" hidden autocomplete="off">
            <div class="form-grid">
              <label>ชื่อบัญชี<input name="label" required maxlength="40" autocomplete="off" placeholder="เช่น กรุงศรี พอร์ตหลัก…"></label>
              <label>โบรกเกอร์<select name="broker_id"><option value="">ไม่ระบุ</option>${allBrokers.map(b => `<option value="${b.id}">${esc(b.name)} (${b.id})</option>`).join("")}</select></label>
            </div>
            <fieldset class="radios"><legend>ราคาหุ้น</legend>
              <label class="check"><input type="radio" name="price_source" value="yahoo" checked>ราคาจริงล่าช้า 15 นาที</label>
              <label class="check"><input type="radio" name="price_source" value="demo">ราคาจำลองสำหรับทดลอง</label>
            </fieldset>
            <p class="hint">บัญชีแบบนี้ใช้ได้กับทุกโบรก กรอกรายการซื้อขายเองหรือนำเข้าจาก Excel แต่ส่งคำสั่งจากแอปไม่ได้</p>
            <button class="btn full" type="submit">สร้างบัญชีและเข้าใช้งาน</button>
          </form>
          <p class="hint foot">key ถูกเก็บใน Windows Credential Manager ของเครื่องนี้เท่านั้น ไม่ถูกส่งไปที่อื่นนอกจาก Settrade</p>
        </div>
      </section>
    </div>`;

  root.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => {
    root.querySelectorAll("[data-tab]").forEach(x => { const on = x === b; x.setAttribute("aria-selected", on); x.setAttribute("aria-pressed", on); });
    $("#apiForm").hidden = b.dataset.tab !== "api";
    $("#manualForm").hidden = b.dataset.tab !== "manual";
  });

  const busy = (btn, on, text) => { btn.disabled = on; if (text) btn.textContent = text; };
  root.querySelectorAll("[data-login]").forEach(btn => btn.onclick = async () => {
    const id = btn.dataset.login, rekey = root.querySelector(`[data-rekey="${id}"]`);
    if (rekey) { rekey.hidden = false; rekey.querySelector("input").focus(); return; }
    const label = btn.textContent; busy(btn, true, "กำลังเข้า…");
    try { await api("/login", { method: "POST", body: { account_id: id } }); await enterApp(); }
    catch (e) { toast(e.message, true); busy(btn, false, label); }
  });
  root.querySelectorAll("[data-rekey]").forEach(f => f.onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f)), btn = f.querySelector("button");
    busy(btn, true, "กำลังเข้า…");
    try { await api("/login", { method: "POST", body: { account_id: f.dataset.rekey, app_id: d.app_id, app_secret: d.app_secret, app_code: d.app_code, remember: !!d.remember } }); await enterApp(); }
    catch (err) { toast(err.message, true); busy(btn, false, "เข้าสู่ระบบ"); }
  });
  $("#apiForm").onsubmit = async e => {
    e.preventDefault();
    const f = e.target, d = Object.fromEntries(new FormData(f)), btn = f.querySelector("button[type=submit]");
    busy(btn, true, "กำลังเชื่อมต่อ Settrade…");
    try {
      await api("/login", { method: "POST", body: { broker_id: d.broker_id, account_no: d.account_no, app_id: d.app_id, app_secret: d.app_secret, app_code: d.app_code, label: d.label, remember: !!d.remember, sandbox: !!d.sandbox } });
      await enterApp();
    } catch (err) { toast(err.message, true); busy(btn, false, "เข้าสู่ระบบด้วย API key"); }
  };
  $("#manualForm").onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target)), btn = e.target.querySelector("button[type=submit]");
    busy(btn, true, "กำลังสร้าง…");
    try { await api("/accounts", { method: "POST", body: { label: d.label, broker_id: d.broker_id, price_source: d.price_source } }); await enterApp(); }
    catch (err) { toast(err.message, true); busy(btn, false, "สร้างบัญชีและเข้าใช้งาน"); }
  };
}

async function enterApp() {
  showApp(true);
  await loadStatus();
  await loadPositions();
  await loadWatch();
  if (!location.hash || location.hash === "#") location.hash = "#/";
  await route();
  toast(`เข้าสู่ระบบ ${state.status.account.label} แล้ว`);
}

// header account switcher
function renderAcctMenu(sess) {
  const btn = $("#acctBtn"), menu = $("#acctMenu"), a = sess.account;
  btn.innerHTML = `<span class="acct-ava sm ${a.kind}" aria-hidden="true">${esc(a.label.slice(0, 1))}</span>
    <span class="acct-btn-text"><b>${esc(a.label)}</b><small>${KIND_TH[a.kind]}${a.broker_name ? " " + esc(a.broker_name) : ""}</small></span>
    <span aria-hidden="true" class="caret">▾</span>`;
  menu.innerHTML = `<p class="menu-title">สลับบัญชี</p>
    ${sess.accounts.map(x => `<button type="button" role="menuitem" class="menu-item" data-switch="${x.id}" ${x.id === a.id ? 'aria-current="true"' : ""}>
      <span class="acct-ava sm ${x.kind}" aria-hidden="true">${esc(x.label.slice(0, 1))}</span>
      <span><b>${esc(x.label)}</b><small>${KIND_TH[x.kind]}${x.broker_name ? " " + esc(x.broker_name) : ""}</small></span>
      ${x.id === a.id ? '<span class="tick" aria-hidden="true">✓</span>' : ""}</button>`).join("")}
    <hr>
    <button type="button" role="menuitem" class="menu-item" data-act="add">+ เพิ่มบัญชี</button>
    <button type="button" role="menuitem" class="menu-item danger" data-act="logout">ออกจากระบบ</button>`;
}

async function refreshSession() { const s = await api("/session"); if (s.logged_in) renderAcctMenu(s); return s; }

function closeMenu() { $("#acctMenu").hidden = true; $("#acctBtn").setAttribute("aria-expanded", "false"); }
$("#acctBtn").addEventListener("click", e => {
  e.stopPropagation();
  const m = $("#acctMenu"); m.hidden = !m.hidden; $("#acctBtn").setAttribute("aria-expanded", String(!m.hidden));
});
document.addEventListener("click", e => { if (!e.target.closest(".acct")) closeMenu(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
$("#acctMenu").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return;
  closeMenu();
  if (b.dataset.switch) {
    if (b.dataset.switch === state.status.account.id) return;
    try { await api("/login", { method: "POST", body: { account_id: b.dataset.switch } }); await enterApp(); }
    catch (err) { await api("/logout", { method: "POST" }); renderLogin(err.message); }
  } else if (b.dataset.act === "logout") {
    await api("/logout", { method: "POST" }); location.hash = "#/"; renderLogin(); toast("ออกจากระบบแล้ว");
  } else if (b.dataset.act === "add") {
    await api("/logout", { method: "POST" }); renderLogin();
  }
});

// ------------------------------------------------------------------ router
const routes = [
  [/^#\/?$/, viewPortfolio],
  [/^#\/s\/([A-Za-z0-9\-.&]+)$/, viewSymbol],
  [/^#\/ledger(\?.*)?$/, viewLedger],
  [/^#\/settings$/, viewSettings],
];
async function route() {
  if (state.chart) { state.chart.destroy(); state.chart = null; }
  const h = location.hash || "#/";
  const nav = h.startsWith("#/ledger") ? "ledger" : h.startsWith("#/settings") ? "settings" : h.startsWith("#/s/") ? "" : "portfolio";
  document.querySelectorAll("[data-nav]").forEach(a => a.dataset.nav === nav ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (!m) continue;
    main.innerHTML = `<p class="muted" aria-live="polite">กำลังโหลด…</p>`;
    try { await fn(...m.slice(1)); } catch (e) { main.innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; }
    renderWatch(); window.scrollTo(0, 0);
    return;
  }
  location.hash = "#/";
}

// ------------------------------------------------------------------ portfolio
function miniStack(item) {
  return `<span class="mini-stack" aria-hidden="true">${item.lots.map(l =>
    `<i class="${(l.unrealized ?? 0) < 0 ? "under" : ""}" style="flex:${l.qty}"></i>`).join("")}</span>`;
}

async function viewPortfolio() {
  const { items, totals: t } = await loadPositions();
  refreshQuotes();
  if (!items.length) {
    main.innerHTML = `<section class="empty">
      <div class="art" aria-hidden="true"><i style="background:var(--loss)"></i><i style="background:var(--gain)"></i><i style="background:var(--brand)"></i></div>
      <h1>เริ่มบันทึกหุ้นของคุณ</h1>
      <p>ใส่การซื้อแต่ละครั้งเป็นล็อต แล้วดูได้ทันทีว่าตอนขาย โบรกตัดล็อตไหนออก และกำไรจริงทั้งก้อนเป็นเท่าไหร่</p>
      <div class="actions"><a class="btn" href="#/ledger">เพิ่มรายการซื้อขาย</a><a class="btn line" href="#/ledger?import">นำเข้าไฟล์ Excel/CSV</a>
      <button class="btn line" id="seed" type="button">ลองด้วยข้อมูลตัวอย่าง</button></div></section>`;
    $("#seed").onclick = async () => { await api("/demo/seed", { method: "POST" }); await loadWatch(); route(); toast("ใส่ข้อมูลตัวอย่างแล้ว"); };
    return;
  }
  const held = items.filter(i => i.qty > 0), closed = items.filter(i => i.qty === 0);
  const life = t.unrealized + t.realized + t.dividends;
  main.innerHTML = `
    <section class="hero">
      <div class="hero-row">
        <div>
          <div class="k">มูลค่าพอร์ตตอนนี้</div>
          <div class="total">${money(t.market_value)}<small>บาท</small></div>
          <span class="delta ${cls(t.unrealized)}">${signed(t.unrealized)} บาท (${pctTxt(pct(t.unrealized, t.cost))})</span>
          <div class="cost">ต้นทุนของหุ้นที่ถืออยู่ ${money(t.cost)} บาท ใน ${held.length} หุ้น</div>
        </div>
        ${state.status.can_trade ? `<button class="btn line" id="syncBtn" type="button" style="color:#fff;border-color:rgba(255,255,255,.3)">ดึงรายการวันนี้จากโบรก</button>` : ""}
      </div>
    </section>
    <div id="syncOut"></div>
    <section class="metrics">
      <div class="metric"><div class="k">กำไรที่ยังไม่ขาย</div><div class="v ${cls(t.unrealized)}">${signed(t.unrealized)}</div><div class="d">หักค่าธรรมเนียมขายโดยประมาณแล้ว</div></div>
      <div class="metric"><div class="k">กำไรที่ขายไปแล้ว</div><div class="v ${cls(t.realized)}">${signed(t.realized)}</div><div class="d">คิดแบบ FIFO ตรงกับแอปโบรก</div></div>
      <div class="metric"><div class="k">กำไรรวมทั้งหมด</div><div class="v ${cls(life)}">${signed(life)}</div><div class="d">รวมเงินปันผล ${money(t.dividends)} บาท</div></div>
    </section>
    <div class="sheet-head"><h2>หุ้นที่ถืออยู่</h2><span class="hint">แท่งด้านซ้ายคือล็อตที่ถือ บนสุดจะถูกขายก่อน</span></div>
    <section class="cards">${held.map(i => `<a class="hcard" href="#/s/${esc(i.symbol)}">
      ${miniStack(i)}
      <div><div class="name" translate="no">${esc(i.symbol)}</div><div class="sub">${qty(i.qty)} หุ้น ${i.lots.length} ล็อต</div>
        <div class="price">ราคา ${money(i.market_price)} <span class="muted">ทุน ${money(i.avg_cost)}</span></div></div>
      <div class="right"><span class="pl ${cls(i.unrealized)}">${signed(i.unrealized)}</span>
        <span class="pct ${cls(i.unrealized)}">${i.unrealized != null ? pctTxt(pct(i.unrealized, i.cost)) : "–"}</span>
        <span class="life">รวมทั้งก้อน ${signed(i.lifetime_pnl)}</span></div>
    </a>`).join("")}</section>
    ${closed.length ? `<section class="sheet" style="margin-top:22px"><div class="sheet-head"><h2>ขายหมดแล้ว</h2></div><div class="closed">
      ${closed.map(i => `<a href="#/s/${esc(i.symbol)}"><b class="num" translate="no">${esc(i.symbol)}</b>
      <span>กำไรที่ขาย <b class="num ${cls(i.realized_fifo)}">${signed(i.realized_fifo)}</b> ปันผล <span class="num">${money(i.dividends)}</span></span></a>`).join("")}</div></section>` : ""}`;
  const sb = $("#syncBtn"); if (sb) sb.onclick = doSync;
}

async function doSync() {
  const out = $("#syncOut");
  try {
    const r = await api("/sync", { method: "POST" });
    toast(`ดึงรายการใหม่ ${r.added} รายการ`);
    out.innerHTML = r.mismatches.length ? `<div class="notice bad"><b>ยอดหุ้นในสมุดไม่ตรงกับโบรก</b>
      ${r.mismatches.map(m => `<div>${esc(m.symbol)} ในสมุดมี ${qty(m.ledger_qty)} หุ้น แต่โบรกมี ${qty(m.broker_qty)} หุ้น</div>`).join("")}
      <div>อาจมีวันที่ซื้อขายแต่ไม่ได้เปิดแอป ให้เพิ่มรายการที่ขาดใน <a href="#/ledger">สมุดรายการ</a></div></div>` : `<div class="notice ok">ยอดหุ้นตรงกับโบรกทุกตัว</div>`;
    if (r.added) viewPortfolio();
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ symbol
async function viewSymbol(sym) {
  sym = sym.toUpperCase();
  let pos = null;
  try { pos = await api("/positions/" + sym); } catch { /* not in ledger */ }
  const q = (await api("/quotes?symbols=" + sym))[sym] || {};
  const last = q.last ?? pos?.market_price;
  const tradable = state.status.can_trade;
  const holds = pos && pos.qty > 0;

  main.innerHTML = `
    <header class="sym-head">
      <h1 translate="no">${esc(sym)}</h1>
      <span class="last">${money(last)}</span>
      <span class="chg ${cls(q.change)}">${q.change != null ? `${signed(q.change)} (${pctTxt(q.pct)})` : esc(q.error || "")}</span>
      ${q.delayed ? `<span class="hint">ราคาล่าช้า</span>` : ""}
      <div class="actions"><button class="btn line small" id="pinBtn" type="button">${state.watch.includes(sym) ? "เลิกติดตาม" : "ติดตาม"}</button>
      <a class="btn line small" href="#/ledger?symbol=${esc(sym)}">เพิ่มรายการ</a></div>
    </header>
    <div class="sym-grid">
      <div class="stack">
        <section class="sheet">
          <div class="chart-tools">
            <div class="seg" role="group" aria-label="ช่วงเวลา">${[["1d", "วัน"], ["1w", "สัปดาห์"], ["1M", "เดือน"]].map(([v, t]) => `<button type="button" data-iv="${v}" aria-pressed="${v === "1d"}">${t}</button>`).join("")}</div>
            <div class="toggles">${[["ma20", "SMA 20"], ["ma50", "SMA 50"], ["ema12", "EMA 12"], ["bb", "Bollinger"], ["rsi", "RSI"], ["macd", "MACD"], ["fib", "Fibonacci"], ["cost", "เส้นต้นทุน"]]
              .map(([k, t]) => `<button type="button" class="chip" data-ind="${k}" aria-pressed="${["ma20", "ma50", "cost"].includes(k)}">${t}</button>`).join("")}</div>
          </div>
          <div class="chart-box" id="chartMain"></div>
          <div class="sub-chart" id="chartRsi" hidden></div>
          <div class="sub-chart" id="chartMacd" hidden></div>
          <div class="legend" id="chartLegend"></div>
          <p class="fib-note" id="fibNote"></p>
        </section>
        ${pos ? `<section class="sheet"><div class="sheet-head"><h2>ประวัติ ${esc(sym)}</h2></div>
          <ul class="hist">${[...pos.history].reverse().map(h => `<li>
            <span class="muted">${thDate(h.date)}</span><span class="side-word ${h.side}">${SIDE_TH[h.side]}</span>
            <span class="num">${qty(h.qty)} × ${money(h.price)}${h.side === "SELL" ? ` <span class="hint">ตัด ${h.fills.length} ล็อต</span>` : ""}</span>
            <span class="num ${h.side === "SELL" ? cls(h.pnl) : ""}">${h.side === "SELL" ? signed(h.pnl) : money(h.amount)}</span></li>`).join("")}</ul></section>` : ""}
      </div>
      <div class="stack">
        ${holds ? positionSheet(pos, last) : `<section class="sheet"><h2>ยังไม่ได้ถือ ${esc(sym)}</h2><p class="soft" style="margin-top:8px">ถ้าเคยซื้อไว้แล้ว <a href="#/ledger?symbol=${esc(sym)}">เพิ่มรายการในสมุด</a> แล้วล็อตจะขึ้นที่นี่</p></section>`}
        ${orderSlip(sym, last, tradable, holds)}
      </div>
    </div>`;

  $("#pinBtn").onclick = async e => { e.target.textContent = (await togglePin(sym)) ? "เลิกติดตาม" : "ติดตาม"; };

  const loadChart = async iv => {
    try {
      const candles = await api(`/candles/${sym}?interval=${iv}&limit=600`);
      if (!state.chart) state.chart = new PriceChart($("#chartMain"), $("#chartRsi"), $("#chartMacd"), $("#chartLegend"), $("#fibNote"));
      state.chart.setData(candles, pos);
    } catch (e) { $("#chartMain").innerHTML = `<div class="notice bad">โหลดกราฟไม่ได้: ${esc(e.message)}</div>`; }
  };
  if (window.LightweightCharts) await loadChart("1d");
  else $("#chartMain").innerHTML = `<div class="notice bad">โหลดไลบรารีกราฟไม่ได้ ตรวจการเชื่อมต่ออินเทอร์เน็ต</div>`;
  main.querySelectorAll("[data-iv]").forEach(b => b.onclick = () => {
    main.querySelectorAll("[data-iv]").forEach(x => x.setAttribute("aria-pressed", x === b)); loadChart(b.dataset.iv);
  });
  main.querySelectorAll("[data-ind]").forEach(b => b.onclick = () => { if (state.chart) b.setAttribute("aria-pressed", state.chart.toggle(b.dataset.ind)); });

  if (holds) wireSimulator(sym, pos);
  wireOrder(sym, last, tradable, pos);
}

// Vertical FIFO stack: top row = oldest lot (sold first), buys append at the bottom.
function lotStack(pos) {
  return `<div class="lotstack" id="lotstack">
    <div class="ls-edge ls-top"><span class="arrow" aria-hidden="true">▲</span><span>ขายออกจากด้านบนก่อน (FIFO)</span></div>
    <div class="ls-rows" id="lsRows">${pos.lots.map((l, i) => `
      <div class="ls-row ${(l.unrealized ?? 0) < 0 ? "under" : ""}" data-i="${i}" style="flex:${l.qty} 1 0">
        <div class="ls-bar"><span class="cut"></span><span class="qty">${qty(l.qty)}</span></div>
        <div class="ls-info">
          <span class="t">${i === 0 ? '<span class="tag">ขายก่อน</span> ' : ""}${qty(l.qty)} หุ้น @ ${money(l.price)}</span>
          <span class="m">ซื้อ ${thDate(l.date)} ทุน ${money(l.unit_cost)}/หุ้น</span>
          <span class="p ${cls(l.unrealized)}">${signed(l.unrealized)}<small>${pctTxt(pct(l.unrealized ?? 0, l.cost))}</small></span>
        </div>
      </div>`).join("")}
      <div class="ls-row ghost" id="lsGhost" hidden style="flex:100 1 0">
        <div class="ls-bar"><span class="qty"></span></div>
        <div class="ls-info"><span class="t"></span><span class="m">ล็อตใหม่ต่อท้ายด้านล่าง</span></div>
      </div>
    </div>
    <div class="ls-edge ls-bottom"><span class="arrow" aria-hidden="true">▼</span><span>ซื้อเพิ่มจะต่อด้านล่าง</span></div>
  </div>`;
}

function positionSheet(pos, last) {
  const unreal = pos.unrealized ?? 0;
  const step = pos.qty >= 100 ? 100 : 1;
  return `<section class="sheet">
    <div class="sheet-head"><h2>ล็อตที่ถืออยู่</h2><span class="hint">${pos.lots.length} ล็อต ${qty(pos.qty)} หุ้น</span></div>
    <div class="readings">
      <div><div class="k">ต้นทุนเฉลี่ย</div><div class="v">${money(pos.avg_cost)}</div><div class="d">ของหุ้นที่ถืออยู่</div></div>
      <div><div class="k">ขายไปแล้ว</div><div class="v ${cls(pos.realized_fifo)}">${signed(pos.realized_fifo)}</div><div class="d">ตรงกับแอปโบรก</div></div>
      <div><div class="k">รวมทั้งก้อน</div><div class="v ${cls(pos.lifetime_pnl)}">${signed(pos.lifetime_pnl)}</div><div class="d">ไม่เปลี่ยนตามการตัดล็อต</div></div>
    </div>
    ${lotStack(pos)}
    <div class="ls-foot"><span>ราคาตลาด <span class="mark">${money(last)}</span></span><span>รวม <b class="num ${cls(unreal)}">${signed(unreal)}</b></span></div>
    <div class="sim">
      <h3>ลองขายดู</h3>
      <div class="sim-range">
        <label for="simRange">จำนวนที่จะขาย</label><output id="simQtyOut" for="simRange"></output>
        <input id="simRange" type="range" min="${step}" max="${pos.qty}" step="${step}" value="${Math.min(pos.lots[0].qty, pos.qty)}" style="grid-column:1/-1">
      </div>
      <label style="max-width:200px">ที่ราคา<input id="simPx" name="simPx" type="number" inputmode="decimal" min="0.01" step="0.01" value="${last ?? ""}" autocomplete="off"></label>
      <div id="simOut"></div>
    </div>
  </section>`;
}

function markStack(pos, fills) {
  const rows = $("#lsRows"); if (!rows) return;
  const used = {}; (fills || []).forEach(f => used[f.lot_txn_id] = (used[f.lot_txn_id] || 0) + f.qty);
  pos.lots.forEach((l, i) => {
    const el = rows.querySelector(`[data-i="${i}"]`), frac = (used[l.txn_id] || 0) / l.qty;
    el.classList.toggle("out", frac >= 0.999);
    el.querySelector(".cut").style.height = frac > 0 && frac < 0.999 ? (frac * 100) + "%" : (frac >= 0.999 ? "100%" : "0");
  });
}

function ghostBuy(q, p) {
  const g = $("#lsGhost"); if (!g) return;
  if (!(q > 0 && p > 0)) { g.hidden = true; return; }
  g.hidden = false; g.style.flex = `${q} 1 0`;
  g.querySelector(".qty").textContent = qty(q);
  g.querySelector(".t").textContent = `+ ${qty(q)} หุ้น @ ${money(p)}`;
}

function wireSimulator(sym, pos) {
  const out = $("#simOut"), range = $("#simRange"), qOut = $("#simQtyOut");
  const run = debounce(async () => {
    const q = +range.value, p = +$("#simPx").value;
    qOut.textContent = `${qty(q)} หุ้น`;
    if (!(q > 0 && p > 0)) { out.innerHTML = ""; markStack(pos, []); return; }
    try {
      const r = await api("/simulate", { method: "POST", body: { symbol: sym, qty: q, price: p } });
      ghostBuy(0, 0); markStack(pos, r.fills);
      const word = r.pnl_fifo >= 0 ? "กำไร" : "ขาดทุน";
      out.innerHTML = `
        <p class="answer">ขาย ${qty(r.qty)} หุ้นที่ ${money(r.price)} ได้เงิน <span class="fig">${money(r.proceeds)}</span> บาท
          โบรกจะตัด${r.fills.length > 1 ? ` ${r.fills.length} ล็อตบนสุด` : "ล็อตบนสุด"} และแสดงว่า${word} <span class="fig ${cls(r.pnl_fifo)}">${money(Math.abs(r.pnl_fifo))}</span> บาท
          ${r.remaining_qty ? `หุ้นที่เหลือ ${qty(r.remaining_qty)} หุ้น ต้นทุนเฉลี่ยเปลี่ยนจาก ${money(r.remaining_avg_before)} เป็น <span class="fig">${money(r.remaining_avg_after)}</span>` : "และจะไม่เหลือหุ้นตัวนี้"}</p>
        <dl class="answer-table">
          <dt>ค่าธรรมเนียมขายโดยประมาณ</dt><dd>${money(r.fee)}</dd>
          <dt>ถ้าคิดจากต้นทุนเฉลี่ย</dt><dd class="${cls(r.pnl_vs_avg)}">${signed(r.pnl_vs_avg)}</dd>
          <dt>ขายราคานี้แล้วเท่าทุนทั้งก้อน</dt><dd><span class="mark">${money(r.breakeven_all)}</span></dd>
        </dl>`;
    } catch (e) { out.innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; }
  }, 120);
  range.oninput = run; $("#simPx").oninput = run; run();
}

function orderSlip(sym, last, tradable, holds) {
  return `<section class="order" id="order">
    <h2>ส่งคำสั่ง ${esc(sym)}</h2>
    ${tradable ? "" : `<p class="locked">ต้องเชื่อม Settrade Open API ก่อนจึงจะส่งคำสั่งได้ <a href="#/settings">ไปที่ตั้งค่า</a></p>`}
    <div class="side-toggle" role="group" aria-label="ซื้อหรือขาย">
      <button type="button" data-side="BUY" aria-pressed="true">ซื้อ</button><button type="button" data-side="SELL" aria-pressed="false" ${holds ? "" : "disabled"}>ขาย</button>
    </div>
    <div class="field-row">
      <label>จำนวนหุ้น<input id="tkQty" name="tkQty" type="number" inputmode="numeric" min="100" step="100" value="100" autocomplete="off"></label>
      <label>ราคา<input id="tkPx" name="tkPx" type="number" inputmode="decimal" min="0.01" step="0.01" value="${last ?? ""}" autocomplete="off"></label>
    </div>
    <dl class="answer-table" id="tkOut"></dl>
    <div class="errs" id="tkErr" aria-live="polite"></div>
    <div class="form-actions"><button class="btn buy" id="tkSend" type="button" style="width:100%" ${tradable ? "" : "disabled"}>ตรวจสอบคำสั่งซื้อ</button></div>
    ${holds ? `<p class="hint" style="margin-top:10px">ตัวเลขในช่องนี้จะแสดงผลบนแท่งล็อตด้านบนให้ดูก่อน</p>` : ""}
  </section>`;
}

const TICKS = [[2, .01], [5, .02], [10, .05], [25, .1], [100, .25], [200, .5], [400, 1], [Infinity, 2]];
const tick = p => TICKS.find(([lim]) => p < lim)[1];

function wireOrder(sym, last, tradable, pos) {
  let side = "BUY";
  const fees = state.status.fees;
  const feeOf = g => g <= 0 ? 0 : Math.round((Math.max(g * fees.commission_rate, fees.min_commission) + g * fees.regulatory_rate) * (1 + fees.vat) * 100) / 100;
  const send = $("#tkSend");
  const preview = debounce(async (q, p) => {
    if (!pos || !(pos.qty > 0)) return;
    if (side === "BUY") { markStack(pos, []); ghostBuy(q, p); return; }
    ghostBuy(0, 0);
    if (q > 0 && q <= pos.qty && p > 0) {
      try { const r = await api("/simulate", { method: "POST", body: { symbol: sym, qty: q, price: p } }); markStack(pos, r.fills); } catch { /* ignore */ }
    }
  }, 150);
  const calc = () => {
    const q = +$("#tkQty").value, p = +$("#tkPx").value, g = q * p, f = feeOf(g);
    const errs = [];
    if (q % 100) errs.push("จำนวนต้องเป็นทวีคูณของ 100");
    if (p > 0 && Math.abs(Math.round(p / tick(p)) * tick(p) - p) > 1e-9) errs.push(`ราคาช่วงนี้ขยับทีละ ${tick(p)} บาท`);
    if (side === "SELL" && pos && q > pos.qty) errs.push(`ถืออยู่ ${qty(pos.qty)} หุ้น`);
    $("#tkOut").innerHTML = `<dt>มูลค่า</dt><dd>${money(g)}</dd><dt>ค่าธรรมเนียมโดยประมาณ</dt><dd>${money(f)}</dd>
      <dt><b>${side === "BUY" ? "จ่ายทั้งหมด" : "ได้รับสุทธิ"}</b></dt><dd><b>${money(side === "BUY" ? g + f : g - f)}</b></dd>`;
    $("#tkErr").innerHTML = errs.map(esc).join("<br>");
    send.disabled = !tradable || errs.length > 0 || !(q > 0 && p > 0);
    return { q, p, g, f };
  };
  const onEdit = () => { const { q, p } = calc(); preview(q, p); };
  main.querySelectorAll("[data-side]").forEach(b => b.onclick = () => {
    side = b.dataset.side;
    main.querySelectorAll("[data-side]").forEach(x => x.setAttribute("aria-pressed", x === b));
    send.className = "btn " + (side === "BUY" ? "buy" : "sell");
    send.textContent = side === "BUY" ? "ตรวจสอบคำสั่งซื้อ" : "ตรวจสอบคำสั่งขาย";
    onEdit();
  });
  $("#tkQty").oninput = onEdit; $("#tkPx").oninput = onEdit;
  $("#tkQty").onfocus = $("#tkPx").onfocus = onEdit;
  calc();

  send.onclick = async () => {
    const { q, p, g, f } = calc();
    let fifo = "";
    if (side === "SELL") {
      try {
        const r = await api("/simulate", { method: "POST", body: { symbol: sym, qty: q, price: p } });
        fifo = `<dt>ล็อตที่จะถูกตัด</dt><dd>${r.fills.map(x => `${qty(x.qty)}@${money(x.buy_price)}`).join(" + ")}</dd>
                <dt>กำไรที่โบรกจะแสดง</dt><dd class="${cls(r.pnl_fifo)}">${signed(r.pnl_fifo)}</dd>`;
      } catch { /* ignore */ }
    }
    const dlg = $("#dialog");
    dlg.innerHTML = `<form method="dialog" id="confirmForm">
      <h2>ยืนยันคำสั่ง${SIDE_TH[side]} ${esc(sym)}</h2>
      <dl class="confirm-grid"><dt>จำนวน</dt><dd>${qty(q)} หุ้น</dd><dt>ราคา</dt><dd>${money(p)}</dd>
        <dt>มูลค่า</dt><dd>${money(g)}</dd><dt>ค่าธรรมเนียมโดยประมาณ</dt><dd>${money(f)}</dd>${fifo}</dl>
      <label>PIN ซื้อขาย<input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="off" required minlength="4" maxlength="12"></label>
      <p class="hint" style="margin-top:6px">PIN ใช้กับคำสั่งนี้ครั้งเดียว ไม่ถูกบันทึกไว้ที่ใด</p>
      <div class="form-actions"><button class="btn ${side === "BUY" ? "buy" : "sell"}" value="ok">ส่งคำสั่ง${SIDE_TH[side]}</button>
      <button class="btn line" value="cancel" formnovalidate>ยกเลิก</button></div></form>`;
    dlg.showModal();
    dlg.onclose = async () => {
      const pin = $("#pin", dlg)?.value; dlg.innerHTML = "";
      if (dlg.returnValue !== "ok" || !pin) return;
      try {
        await api("/orders", { method: "POST", body: { side, symbol: sym, volume: q, price: p, pin, confirm: true } });
        toast("ส่งคำสั่งแล้ว รายการจะเข้าสมุดเมื่อจับคู่ได้");
      } catch (e) { toast(e.message, true); }
    };
  };
}

// ------------------------------------------------------------------ ledger
async function viewLedger() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const rows = await api("/txns");
  main.innerHTML = `
    <div class="page-head"><h1>สมุดรายการ</h1><span class="hint">${rows.length} รายการ บันทึกอัตโนมัติทุกครั้งที่แก้</span></div>
    <section class="sheet">
      <div class="sheet-head"><h2>เพิ่มรายการ</h2></div>
      <form class="txn-form" id="txnForm" autocomplete="off">
        <label>วันที่<input name="date" type="date" required value="${today()}"></label>
        <label>หุ้น<input name="symbol" required maxlength="20" value="${esc(params.get("symbol") || "")}" style="text-transform:uppercase"></label>
        <label>ประเภท<select name="side"><option value="BUY">ซื้อ</option><option value="SELL">ขาย</option><option value="DIV">ปันผล</option></select></label>
        <label><span id="qtyLbl">จำนวน</span><input name="qty" type="number" min="1" step="any" required></label>
        <label><span id="pxLbl">ราคา</span><input name="price" type="number" min="0" step="any" required></label>
        <label><span id="feeLbl">ค่าธรรมเนียม</span><input name="fee" type="number" min="0" step="any" placeholder="คำนวณเอง…"></label>
        <label>หมายเหตุ<input name="note" maxlength="200"></label>
        <button class="btn" type="submit">บันทึก</button>
      </form>
      <p class="hint" style="margin-top:10px">เว้นค่าธรรมเนียมว่างไว้ได้ แอปจะคำนวณจากอัตราในหน้าตั้งค่า</p>
    </section>
    <section class="sheet" id="importPanel">
      <div class="sheet-head"><h2>นำเข้าจากไฟล์</h2><button class="linkbtn" id="tplBtn">ดาวน์โหลดไฟล์ตัวอย่าง</button></div>
      <label class="drop" id="drop">ลากไฟล์ .xlsx หรือ .csv มาวางตรงนี้ หรือคลิกเพื่อเลือกไฟล์
        <input type="file" id="fileIn" accept=".csv,.xlsx" class="sr"></label>
      <p class="hint" style="margin-top:10px">ต้องมีคอลัมน์ วันที่ หุ้น ประเภท จำนวน ราคา (หรือ date, symbol, side, qty, price) ใช้ปี พ.ศ. ได้</p>
      <div id="importOut"></div>
    </section>
    <section class="sheet">
      <div class="sheet-head"><h2>ทุกรายการ</h2><input id="filter" class="filter" placeholder="ค้นหาหุ้น…"></div>
      <div class="table-wrap"><table class="grid" id="txnTable">
        <thead><tr><th>วันที่</th><th>หุ้น</th><th>ประเภท</th><th>จำนวน</th><th>ราคา</th><th>ค่าธรรมเนียม</th><th>ที่มา</th><th>หมายเหตุ</th><th></th></tr></thead>
        <tbody></tbody></table></div>
    </section>`;

  const form = $("#txnForm");
  form.side.onchange = () => {
    const div = form.side.value === "DIV";
    $("#qtyLbl").textContent = div ? "จำนวนหุ้นที่ได้ปันผล" : "จำนวน";
    $("#pxLbl").textContent = div ? "ปันผลต่อหุ้น" : "ราคา";
    $("#feeLbl").textContent = div ? "ภาษีหัก ณ ที่จ่าย" : "ค่าธรรมเนียม";
  };
  form.onsubmit = async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    try {
      await api("/txns", { method: "POST", body: { ...f, symbol: f.symbol.toUpperCase(), qty: +f.qty, price: +f.price, fee: f.fee === "" ? null : +f.fee } });
      toast(`บันทึก ${f.symbol.toUpperCase()} แล้ว`); await loadPositions(); viewLedger();
    } catch (err) { toast(err.message, true); }
  };

  const tbody = $("#txnTable tbody");
  const draw = () => {
    const fl = $("#filter").value.trim().toUpperCase();
    const list = [...rows].reverse().filter(r => !fl || r.symbol.includes(fl));
    tbody.innerHTML = list.length ? list.map(r => `<tr>
      <td>${thDate(r.date)}</td><td class="sym">${esc(r.symbol)}</td><td><span class="side-word ${r.side}">${SIDE_TH[r.side]}</span></td>
      <td class="num">${qty(r.qty)}</td><td class="num">${money(r.price)}</td><td class="num">${r.fee == null ? '<span class="muted">อัตโนมัติ</span>' : money(r.fee)}</td>
      <td class="muted">${{ manual: "กรอกเอง", import: "นำเข้า", settrade: "โบรก", demo: "ตัวอย่าง" }[r.source] || esc(r.source)}</td><td class="soft">${esc(r.note)}</td>
      <td><div class="row-actions"><button class="linkbtn" data-edit="${r.id}">แก้</button><button class="linkbtn" data-del="${r.id}">ลบ</button></div></td></tr>`).join("")
      : `<tr><td colspan="9" class="muted" style="text-align:center;padding:28px">ยังไม่มีรายการ</td></tr>`;
  };
  draw();
  $("#filter").oninput = draw;
  tbody.onclick = async e => {
    const del = e.target.dataset.del, edit = e.target.dataset.edit;
    if (del) {
      const r = rows.find(x => x.id == del);
      if (!confirm(`ลบรายการ${SIDE_TH[r.side]} ${r.symbol} ${r.qty} หุ้น วันที่ ${thDate(r.date)}?`)) return;
      try { await api("/txns/" + del, { method: "DELETE" }); toast("ลบแล้ว"); await loadPositions(); viewLedger(); } catch (err) { toast(err.message, true); }
    }
    if (edit) editTxn(rows.find(x => x.id == edit));
  };

  $("#tplBtn").onclick = () => download("/template.csv", "template.csv");
  const drop = $("#drop"), fileIn = $("#fileIn");
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) previewImport(e.dataTransfer.files[0]); };
  fileIn.onchange = () => fileIn.files[0] && previewImport(fileIn.files[0]);
  if (params.has("import")) $("#importPanel").scrollIntoView();
}

async function previewImport(file) {
  const out = $("#importOut");
  const fd = () => { const f = new FormData(); f.append("file", file); return f; };
  try {
    const r = await api("/import", { method: "POST", body: fd() });
    out.innerHTML = `<div class="notice ok" style="margin-top:14px">พบ ${r.count} รายการใน ${esc(file.name)} ตรวจดูก่อนนำเข้า</div>
      <div class="table-wrap"><table class="grid"><thead><tr><th>วันที่</th><th>หุ้น</th><th>ประเภท</th><th>จำนวน</th><th>ราคา</th></tr></thead>
      <tbody>${r.rows.slice(0, 12).map(x => `<tr><td>${thDate(x.date)}</td><td class="sym">${esc(x.symbol)}</td><td><span class="side-word ${x.side}">${SIDE_TH[x.side]}</span></td><td class="num">${qty(x.qty)}</td><td class="num">${money(x.price)}</td></tr>`).join("")}</tbody></table></div>
      ${r.count > 12 ? `<p class="hint">และอีก ${r.count - 12} รายการ</p>` : ""}
      <div class="form-actions"><button class="btn" id="doImport">นำเข้า ${r.count} รายการ</button></div>`;
    $("#doImport").onclick = async () => {
      try { const x = await api("/import?commit=true", { method: "POST", body: fd() }); toast(`นำเข้า ${x.imported} รายการแล้ว`); await loadPositions(); viewLedger(); }
      catch (e) { toast(e.message, true); }
    };
  } catch (e) { out.innerHTML = `<div class="notice bad" style="margin-top:14px">${esc(e.message)}</div>`; }
}

function editTxn(r) {
  const dlg = $("#dialog");
  dlg.innerHTML = `<form method="dialog" id="editForm"><h2>แก้รายการ</h2>
    <div class="form-grid" style="margin-top:12px">
      <label>วันที่<input name="date" type="date" value="${r.date.slice(0, 10)}" required></label>
      <label>หุ้น<input name="symbol" value="${esc(r.symbol)}" required></label>
      <label>ประเภท<select name="side">${["BUY", "SELL", "DIV"].map(s => `<option value="${s}" ${s === r.side ? "selected" : ""}>${SIDE_TH[s]}</option>`).join("")}</select></label>
      <label>จำนวน<input name="qty" type="number" step="any" value="${r.qty}" required></label>
      <label>ราคา<input name="price" type="number" step="any" value="${r.price}" required></label>
      <label>ค่าธรรมเนียม<input name="fee" type="number" step="any" value="${r.fee ?? ""}" placeholder="คำนวณเอง…"></label>
    </div>
    <label style="margin-top:14px">หมายเหตุ<input name="note" value="${esc(r.note)}"></label>
    <div class="form-actions"><button class="btn" value="ok">บันทึกการแก้ไข</button><button class="btn line" value="cancel" formnovalidate>ยกเลิก</button></div></form>`;
  dlg.showModal();
  dlg.onclose = async () => {
    if (dlg.returnValue !== "ok") return;
    const f = Object.fromEntries(new FormData($("#editForm")));
    try {
      await api("/txns/" + r.id, { method: "PUT", body: { ...f, symbol: f.symbol.toUpperCase(), qty: +f.qty, price: +f.price, fee: f.fee === "" ? null : +f.fee } });
      toast("บันทึกการแก้ไขแล้ว"); await loadPositions(); viewLedger();
    } catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------ settings
async function viewSettings() {
  await loadStatus();
  const s = state.status, a = s.account, f = s.fees;
  main.innerHTML = `<div class="settings stack">
    <h1>ตั้งค่า</h1>
    <section class="sheet">
      <div class="sheet-head"><h2>บัญชีนี้</h2><span class="kind ${a.kind}">${KIND_TH[a.kind]}</span></div>
      <dl class="answer-table" style="margin:0 0 16px">
        <dt>โบรกเกอร์</dt><dd>${a.broker_name ? esc(a.broker_name) + " (" + esc(a.broker_id) + ")" : "ไม่ระบุ"}</dd>
        ${a.account_no ? `<dt>เลขบัญชี</dt><dd>${esc(a.account_no)}</dd>` : ""}
        ${a.kind === "api" ? `<dt>API key</dt><dd>${a.remember ? "จำไว้ในเครื่องนี้" : "ใช้ครั้งนี้เท่านั้น"}${a.sandbox ? " (Sandbox)" : ""}</dd>` : ""}
        <dt>ราคาหุ้น</dt><dd>${{ settrade: "Settrade ราคาสด", yahoo: "ราคาจริงล่าช้า 15 นาที", demo: "ราคาจำลอง" }[s.provider]}</dd>
      </dl>
      <form id="acctForm" class="form-grid" autocomplete="off">
        <label>ชื่อบัญชี<input name="label" required maxlength="40" value="${esc(a.label)}" autocomplete="off"></label>
        ${a.kind === "manual" ? `<label>ราคาหุ้น<select name="price_source">
          <option value="yahoo" ${a.price_source === "yahoo" ? "selected" : ""}>ราคาจริงล่าช้า 15 นาที</option>
          <option value="demo" ${a.price_source === "demo" ? "selected" : ""}>ราคาจำลอง</option></select></label>` : ""}
        <div class="form-actions" style="grid-column:1/-1"><button class="btn" type="submit">บันทึกการตั้งค่าบัญชี</button></div>
      </form>
      <div class="form-actions" style="border-top:1px solid var(--line);padding-top:16px">
        ${a.kind === "api" ? `<button class="btn line" id="forgetKey" type="button">ลืม API key ของบัญชีนี้</button>` : ""}
        <button class="btn danger" id="delAcct" type="button">ลบบัญชีนี้และรายการทั้งหมด</button>
      </div>
    </section>

    <section class="sheet">
      <div class="sheet-head"><h2>ค่าธรรมเนียม</h2></div>
      <p>ใช้คำนวณต้นทุนเมื่อไม่ได้ใส่ค่าธรรมเนียมเอง ดูอัตราของคุณได้จากใบยืนยันการซื้อขาย ค่านี้ใช้กับทุกบัญชี</p>
      <form id="feeForm" class="form-grid" autocomplete="off">
        <label>ค่าคอมมิชชั่น (%)<input name="commission_rate" type="number" inputmode="decimal" step="0.001" min="0" value="${(f.commission_rate * 100).toFixed(3)}"></label>
        <label>ค่าธรรมเนียมตลาด (%)<input name="regulatory_rate" type="number" inputmode="decimal" step="0.0001" min="0" value="${(f.regulatory_rate * 100).toFixed(4)}"></label>
        <label>ค่าคอมขั้นต่ำต่อรายการ (บาท)<input name="min_commission" type="number" inputmode="decimal" step="1" min="0" value="${f.min_commission}"></label>
        <label>VAT (%)<input name="vat" type="number" inputmode="decimal" step="0.01" min="0" value="${(f.vat * 100).toFixed(2)}"></label>
        <div class="form-actions" style="grid-column:1/-1"><button class="btn" type="submit">บันทึกค่าธรรมเนียม</button></div>
      </form>
    </section>

    <section class="sheet">
      <div class="sheet-head"><h2>ข้อมูลในเครื่อง</h2></div>
      <p>ทุกรายการบันทึกอัตโนมัติในโฟลเดอร์ data ของแอป และสำรองไว้วันละไฟล์ เก็บย้อนหลัง 30 วัน</p>
      <div class="form-actions"><button class="btn line" id="themeBtn" type="button">สลับโหมดสว่าง/มืด</button>
        <button class="btn danger" id="wipeBtn" type="button">ล้างรายการของบัญชีนี้</button></div>
    </section></div>`;

  $("#acctForm").onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    try { await api("/account", { method: "PATCH", body: d }); await loadStatus(); toast("บันทึกการตั้งค่าบัญชีแล้ว"); refreshQuotes(); viewSettings(); }
    catch (err) { toast(err.message, true); }
  };
  const fk = $("#forgetKey");
  if (fk) fk.onclick = async () => {
    if (!confirm("ลืม API key ของบัญชีนี้? ครั้งหน้าต้องใส่ App ID, App Secret และ App Code ใหม่ รายการในสมุดยังอยู่ครบ")) return;
    await api(`/accounts/${a.id}/forget-key`, { method: "POST" }); renderLogin(); toast("ลืม API key แล้ว");
  };
  $("#delAcct").onclick = async () => {
    if (prompt(`พิมพ์ DELETE เพื่อลบบัญชี "${a.label}" และรายการทั้งหมดของบัญชีนี้ (มีไฟล์สำรองของวันนี้ใน data/backups)`) !== "DELETE") return;
    await api(`/accounts/${a.id}?confirm=DELETE`, { method: "DELETE" }); renderLogin(); toast("ลบบัญชีแล้ว");
  };
  $("#feeForm").onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    try {
      await api("/settings", { method: "PUT", body: { fees: { commission_rate: d.commission_rate / 100, regulatory_rate: d.regulatory_rate / 100, min_commission: +d.min_commission, vat: d.vat / 100 } } });
      await loadStatus(); toast("บันทึกค่าธรรมเนียมแล้ว");
    } catch (err) { toast(err.message, true); }
  };
  $("#themeBtn").onclick = () => {
    const next = (document.documentElement.dataset.theme || "dark") === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next; try { localStorage.setItem("theme", next); } catch { /* ignore */ }
    document.querySelector('meta[name="theme-color"]').content = next === "dark" ? "#0B1020" : "#F3F5FA";
    toast(next === "dark" ? "เปลี่ยนเป็นโหมดมืดแล้ว" : "เปลี่ยนเป็นโหมดสว่างแล้ว");
  };
  $("#wipeBtn").onclick = async () => {
    if (prompt(`พิมพ์ DELETE เพื่อล้างรายการทั้งหมดของบัญชี "${a.label}" (มีไฟล์สำรองของวันนี้ใน data/backups)`) !== "DELETE") return;
    await api("/all?confirm=DELETE", { method: "DELETE" }); await loadPositions(); toast("ล้างรายการแล้ว");
  };
}

// ------------------------------------------------------------------ boot
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }
$("#exportBtn").onclick = () => download("/export.xlsx", "portfolio.xlsx");
window.addEventListener("hashchange", () => { if (state.status) route(); });
(async () => {
  showApp(false);
  try {
    const s = await api("/session");
    if (s.logged_in) await enterApp(); else await renderLogin();
  } catch (e) { toast(e.message, true); }
  setInterval(() => { if (!$("#appTop").hidden) refreshQuotes(); }, 30000);
})();
