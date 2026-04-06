#!/usr/bin/env python3
"""Alpha Trader Desktop - Complete single-file launcher.
No Electron, no npm, just Python + Browser.
Runs FastAPI auto-server + opens desktop-style browser window.
"""
import os, sys, threading, time

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(base))

    print("=" * 60)
    print("  Alpha Trader Desktop v1.0.0")
    print("  Starting server on http://127.0.0.1:8765")
    print("=" * 60)
    print()

    # Install deps if needed
    try:
        from fastapi import FastAPI
    except ImportError:
        print("  Installing: fastapi uvicorn yfinance numpy matplotlib")
        os.system("pip install fastapi uvicorn yfinance numpy matplotlib cryptography requests httpx 2>&1 | tail -3")

    import uvicorn
    import webbrowser
    from gui.api.main import app

    def open_browser():
        time.sleep(1.5)
        try:
            webbrowser.open("http://127.0.0.1:8765")
        except Exception as e:
            print("  Could not open browser: " + str(e))
            print("  Open manually: http://127.0.0.1:8765")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False, log_level="warning")

if __name__ == "__main__":
    main()
