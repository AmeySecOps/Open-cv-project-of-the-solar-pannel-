"""
SolarGuard AI - Root Application Entry Point
Allows launching via `python app.py` or standard WSGI servers.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app import app, create_app
from backend.config import Config
from backend.utils import logger

if __name__ == "__main__":
    logger.info(f"Starting SolarGuard AI from root on {Config.HOST}:{Config.PORT}")
    app_instance = create_app()
    app_instance.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
