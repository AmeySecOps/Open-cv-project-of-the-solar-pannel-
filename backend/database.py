"""
SolarGuard AI - SQLite Database Manager
Provides thread-safe storage for detection logs, system events, and persistent configuration.
"""

import sqlite3
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.config import Config
from backend.utils import logger

# Thread-local storage for database connections
_local = threading.local()
_db_lock = threading.Lock()


def get_db_connection() -> sqlite3.Connection:
    """Returns a thread-local SQLite connection."""
    if not hasattr(_local, "connection") or _local.connection is None:
        Config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(Config.DATABASE_PATH),
            timeout=10.0,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        _local.connection = conn
    return _local.connection


class Database:
    """Database interface for SolarGuard AI."""

    @staticmethod
    def initialize():
        """Creates tables and indexes if they do not exist."""
        with _db_lock:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Detection Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS detection_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    soiling_index REAL NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metric_ssim REAL,
                    metric_texture REAL,
                    metric_contrast REAL,
                    metric_hsv REAL,
                    esp32_status TEXT,
                    esp32_command_sent TEXT
                );
            """)

            # System Logs Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    component TEXT NOT NULL,
                    message TEXT NOT NULL
                );
            """)

            # Settings Key-Value Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # Indexes for faster queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_timestamp ON detection_logs (timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs (timestamp);")

            conn.commit()
            logger.info("SQLite database tables initialized successfully.")

    @staticmethod
    def log_detection(
        soiling_index: float,
        status: str,
        confidence: float,
        metric_ssim: float = 0.0,
        metric_texture: float = 0.0,
        metric_contrast: float = 0.0,
        metric_hsv: float = 0.0,
        esp32_status: str = "DISCONNECTED",
        esp32_command_sent: str = "NONE",
        timestamp: Optional[str] = None
    ) -> int:
        """Stores a detection scan record in the database."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                ts = timestamp or datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO detection_logs (
                        timestamp, soiling_index, status, confidence,
                        metric_ssim, metric_texture, metric_contrast, metric_hsv,
                        esp32_status, esp32_command_sent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts, round(soiling_index, 2), status, round(confidence, 1),
                    round(metric_ssim, 4), round(metric_texture, 4),
                    round(metric_contrast, 4), round(metric_hsv, 4),
                    esp32_status, esp32_command_sent
                ))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"Failed to log detection to database: {e}")
                return -1

    @staticmethod
    def get_latest_detection() -> Optional[Dict[str, Any]]:
        """Retrieves the most recent detection result."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM detection_logs
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                return dict(row) if row else None
            except Exception as e:
                logger.error(f"Error fetching latest detection: {e}")
                return None

    @staticmethod
    def get_detection_history(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieves detection history with pagination."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM detection_logs
                    ORDER BY id DESC LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            except Exception as e:
                logger.error(f"Error fetching detection history: {e}")
                return []

    @staticmethod
    def get_detection_stats() -> Dict[str, Any]:
        """Calculates aggregated metrics for dashboard visualizations."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()

                # Total count
                cursor.execute("SELECT COUNT(*) as total FROM detection_logs")
                total = cursor.fetchone()["total"]

                if total == 0:
                    return {
                        "total_scans": 0,
                        "clean_count": 0,
                        "moderate_count": 0,
                        "heavy_count": 0,
                        "clean_percentage": 100.0,
                        "dusty_percentage": 0.0,
                        "average_soiling": 0.0,
                        "recent_trend": []
                    }

                # Condition counts
                cursor.execute("""
                    SELECT status, COUNT(*) as cnt
                    FROM detection_logs
                    GROUP BY status
                """)
                counts = {r["status"]: r["cnt"] for r in cursor.fetchall()}
                clean_count = counts.get("CLEAN", 0)
                mod_count = counts.get("MODERATELY DUSTY", 0)
                heavy_count = counts.get("HEAVILY DUSTY", 0)
                dusty_count = mod_count + heavy_count

                # Average soiling
                cursor.execute("SELECT AVG(soiling_index) as avg_soiling FROM detection_logs")
                avg_soiling = cursor.fetchone()["avg_soiling"] or 0.0

                # Recent trend (last 30 scans)
                cursor.execute("""
                    SELECT id, timestamp, soiling_index, status
                    FROM detection_logs
                    ORDER BY id DESC LIMIT 30
                """)
                trend = [dict(r) for r in cursor.fetchall()]
                trend.reverse()

                return {
                    "total_scans": total,
                    "clean_count": clean_count,
                    "moderate_count": mod_count,
                    "heavy_count": heavy_count,
                    "clean_percentage": round((clean_count / total) * 100, 1),
                    "dusty_percentage": round((dusty_count / total) * 100, 1),
                    "average_soiling": round(avg_soiling, 2),
                    "recent_trend": trend
                }
            except Exception as e:
                logger.error(f"Error computing detection stats: {e}")
                return {}

    @staticmethod
    def log_system_event(level: str, component: str, message: str):
        """Stores a system activity or error event."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO system_logs (timestamp, level, component, message)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now().isoformat(), level.upper(), component, message))
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to record system event: {e}")

    @staticmethod
    def get_system_logs(limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves recent system events for the UI log monitor."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM system_logs
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
                return [dict(r) for r in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Error fetching system logs: {e}")
                return []

    @staticmethod
    def get_setting(key: str, default: Any = None) -> Any:
        """Retrieves a stored setting value."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row["value"] if row else default
            except Exception as e:
                logger.error(f"Error getting setting {key}: {e}")
                return default

    @staticmethod
    def set_setting(key: str, value: Any):
        """Persists a setting key-value pair."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """, (key, str(value), now))
                conn.commit()
            except Exception as e:
                logger.error(f"Error setting {key}: {e}")

    @staticmethod
    def get_all_settings() -> Dict[str, str]:
        """Returns all persisted settings."""
        with _db_lock:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM settings")
                return {row["key"]: row["value"] for row in cursor.fetchall()}
            except Exception as e:
                logger.error(f"Error fetching all settings: {e}")
                return {}


# Auto-initialize database on import
Database.initialize()
