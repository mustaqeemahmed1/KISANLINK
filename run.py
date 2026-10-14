"""
run.py -- 1-Command Launcher for KisanLink AI (Local & Production).
Starts both the FastAPI Backend and Web UI on a single port
and automatically opens the app in your default browser if running locally.
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure backend directory is importable
sys.path.insert(0, str(Path(__file__).parent / "backend"))


def open_browser(port: int):
    time.sleep(1.2)
    print(f"\n[+] Opening KisanLink AI in your browser: http://localhost:{port} ...\n")
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    is_cloud = bool(os.environ.get("PORT") or os.environ.get("RENDER") or os.environ.get("RAILWAY_STATIC_URL"))
    host = os.environ.get("HOST", "0.0.0.0" if is_cloud else "127.0.0.1")

    # Only open browser on local interactive runs
    if not is_cloud and not os.environ.get("NO_BROWSER"):
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    print("=" * 60)
    print("  * KisanLink AI Platform")
    print(f"  -> App URL:   http://{host}:{port}")
    print(f"  -> API Docs:  http://{host}:{port}/docs")
    print(f"  -> Health:    http://{host}:{port}/health")
    print("=" * 60)

    uvicorn.run("backend.main:app", host=host, port=port, reload=not is_cloud)

