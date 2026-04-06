#!/usr/bin/env python3
"""CEO GATEWAY - ONE CLICK LAUNCHER.
ALL systems unified: Trading, Brain, Knowledge, Clips.
ONE COMMAND: python3 run.py"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def install_deps():
    os.system("pip install fastapi uvicorn yfinance numpy httpx cryptography matplotlib 2>&1 | tail -2")

install_deps()

from gateway.main import app
import uvicorn, webbrowser

def launch():
    time.sleep(1.5)
    try: webbrowser.open("http://127.0.0.1:8000")
    except: print("Open: http://127.0.0.1:8000")

print("\n" + "="*60)
print("  CEO GATEWAY v3.0 - ALL SYSTEMS UNIFIED")
print("  Trading | Brain | Knowledge | Clips")
print("  Dashboard: http://127.0.0.1:8000")
print("="*60 + "\n")

threading.Thread(target=launch).start()
uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
