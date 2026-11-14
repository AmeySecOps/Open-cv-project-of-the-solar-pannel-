"""
SolarGuard AI - Configuration Module
Centralized configuration management for backend services, OpenCV, and ESP32.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of Project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if it exists
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    # Also attempt loading from default
    load_dotenv()


class Config:
    """System configuration parameters."""

    BASE_DIR = BASE_DIR

    # Server settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    SECRET_KEY = os.getenv("SECRET_KEY", "solarguard_ai_secure_token_secret_key_2026")

    # Storage paths
    DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/solarguard.db")
    REFERENCE_DIR = BASE_DIR / "reference_images"
    REFERENCE_IMAGE_PATH = BASE_DIR / os.getenv("REFERENCE_IMAGE_PATH", "reference_images/clean_reference.jpg")
    LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "logs/application.log")

    # Camera defaults
    DEFAULT_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", 0))
    DEFAULT_CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", os.getenv("CAMERA_INDEX", "0"))
    DEFAULT_IP_WEBCAM_URL = os.getenv("IP_WEBCAM_URL", "http://192.168.1.100:8080")
    DEFAULT_WIDTH = int(os.getenv("CAMERA_WIDTH", 640))
    DEFAULT_HEIGHT = int(os.getenv("CAMERA_HEIGHT", 480))
    DEFAULT_FPS = int(os.getenv("CAMERA_FPS", 30))

    # ESP32 settings
    ESP32_DEFAULT_IP = os.getenv("ESP32_IP", "192.168.1.150")
    ESP32_PORT = int(os.getenv("ESP32_PORT", 80))
    ESP32_TIMEOUT = float(os.getenv("ESP32_TIMEOUT", 2.5))
    ESP32_MAX_RETRIES = int(os.getenv("ESP32_MAX_RETRIES", 3))

    # Dust Detection Calibration Thresholds (0.0 - 100.0%)
    # Below THRESHOLD_CLEAN: Clean
    # Between THRESHOLD_CLEAN and THRESHOLD_HEAVY: Moderately Dusty
    # Above THRESHOLD_HEAVY: Heavily Dusty
    DEFAULT_THRESHOLD_CLEAN = float(os.getenv("THRESHOLD_CLEAN", 22.0))
    DEFAULT_THRESHOLD_HEAVY = float(os.getenv("THRESHOLD_HEAVY", 48.0))

    # Temporal Smoothing & Stability
    CONSECUTIVE_REQUIRED = int(os.getenv("CONSECUTIVE_DETECTIONS_REQUIRED", 3))
    SCAN_INTERVAL_SECONDS = float(os.getenv("SCAN_INTERVAL_SECONDS", 2.0))

    # Region of Interest (normalized 0.0 - 1.0)
    DEFAULT_ROI = {
        "x_min": float(os.getenv("ROI_X_MIN", 0.05)),
        "y_min": float(os.getenv("ROI_Y_MIN", 0.05)),
        "x_max": float(os.getenv("ROI_X_MAX", 0.95)),
        "y_max": float(os.getenv("ROI_Y_MAX", 0.95)),
    }

    # Ensure critical directories exist
    @classmethod
    def ensure_directories(cls):
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


Config.ensure_directories()
