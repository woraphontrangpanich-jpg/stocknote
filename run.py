"""Start Stock Note: local server on 127.0.0.1 and open the browser."""
import threading
import webbrowser

import uvicorn

from backend.app import PORT

if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    uvicorn.run("backend.app:app", host="127.0.0.1", port=PORT, log_level="warning")
