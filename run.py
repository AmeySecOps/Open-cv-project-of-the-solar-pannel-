"""
SolarGuard AI - Launcher Script
Alias for python run.py
"""

from app import app, create_app, Config, logger

if __name__ == "__main__":
    logger.info(f"Starting SolarGuard AI on {Config.HOST}:{Config.PORT}")
    app_instance = create_app()
    app_instance.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
