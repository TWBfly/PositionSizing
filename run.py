#!/usr/bin/env python3
"""
Launcher script for Position Sizing & Risk Management System.
Starts the FastAPI service on localhost:8000.
"""

import sys
import os
import webbrowser
import uvicorn

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    url = f"http://{host}:{port}"
    print(f"=====================================================================")
    print(f"  Futures Position Sizing & Risk Management System (1.md Quant)")
    print(f"  Web Dashboard: {url}")
    print(f"  API Docs:      {url}/docs")
    print(f"=====================================================================")

    # Run uvicorn server
    uvicorn.run("backend.main:app", host=host, port=port, reload=False, log_level="info")

if __name__ == "__main__":
    main()
