"""Stock Note launcher.

Double-click (or open from the desktop shortcut) to:
1. start the local server on 127.0.0.1 (if it is not running yet)
2. open the app in its own window (Edge/Chrome app mode, no address bar)
3. stop the server when that window is closed

Runs with pythonw, so no console window appears. Logs go to data/launcher.log.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)          # running from the packaged StockNote.exe
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# packaged app keeps data per Windows user so updating the program never touches it
DATA = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "StockNote") if FROZEN else ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("STOCKNOTE_DATA", str(DATA))
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# pythonw has no console: send output to a log file instead of crashing on print
_log = open(DATA / "launcher.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log

PORTS = range(47615, 47625)        # first free one wins; uncommon range avoids clashes with dev servers
PORT = PORTS[0]
URL = f"http://127.0.0.1:{PORT}/"
BROWSERS = [
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]


def port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ours_running() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=2) as r:
            return "<title>Stock Note</title>" in r.read().decode("utf-8", "ignore")
    except Exception:
        return False


def message(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Stock Note", 0x10)
    except Exception:
        print(text)


def start_server():
    import uvicorn
    from backend.app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):           # wait up to ~10 s
        if port_open():
            return server
        time.sleep(0.1)
    raise RuntimeError("server did not start")


def open_window() -> subprocess.Popen | None:
    exe = next((b for b in BROWSERS if b.is_file()), None)
    if exe is None:
        webbrowser.open(URL)
        return None
    profile = DATA / "app-window"
    return subprocess.Popen([str(exe), f"--app={URL}", f"--user-data-dir={profile}",
                             "--no-first-run", "--no-default-browser-check", "--window-size=1440,900",
                             "--disable-background-mode", "--disable-sync", "--disable-extensions",
                             "--disable-component-extensions-with-background-pages",
                             "--disable-features=msEdgeStartupBoost,msImplicitSignin,msEdgeSyncConsent,"
                             "EdgeCollections,msUndersideButton,msShoppingTrigger,Translate,TranslateUI",
                             "--lang=th-TH"])


TITLE = "Stock Note"


def window_open() -> bool:
    """True while a visible top-level window titled Stock Note exists."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = False

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        nonlocal found
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(TITLE):
                found = True
                return False
        return True
    user32.EnumWindows(cb, 0)
    return found


def stop_window_processes():
    """End the Edge/Chrome processes that belong to our private app-window profile only."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + str(DATA / "app-window") +
          "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, timeout=30)


def use_port(p: int) -> None:
    global PORT, URL
    PORT, URL = p, f"http://127.0.0.1:{p}/"
    os.environ["STOCKNOTE_PORT"] = str(p)


def main():
    print(f"--- launch {time.ctime()}")
    server = None
    # reuse a Stock Note that is already running, else take the first free port
    for p in PORTS:
        use_port(p)
        if not port_open():
            break
        if ours_running():
            server = "running"
            break
    else:
        message("ไม่มีพอร์ตว่างสำหรับ Stock Note (47615-47624) ปิดโปรแกรมอื่นบางตัวแล้วลองใหม่")
        return
    if server == "running":
        open_window()
        return
    else:
        try:
            server = start_server()
        except Exception as e:
            print("start failed:", repr(e))
            message(f"เปิด Stock Note ไม่สำเร็จ ดูรายละเอียดใน {DATA / 'launcher.log'}")
            return

    win = open_window()
    if win is None:
        # plain browser tab: keep serving until the process is ended from Task Manager
        threading.Event().wait()
    # wait for the window to appear, then for the user to close it
    for _ in range(300):
        if window_open():
            break
        time.sleep(0.1)
    misses = 0
    while misses < 3:              # 3 checks in a row without the window = closed
        misses = 0 if window_open() else misses + 1
        time.sleep(1)
    server.should_exit = True
    stop_window_processes()
    time.sleep(1)
    print("--- closed")


if __name__ == "__main__":
    main()
