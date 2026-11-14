"""
SolarGuard AI - Automated Monitoring & Control Service
Coordinates continuous frame acquisition, computer vision dust analysis,
temporal debouncing, automated ESP32 hardware synchronization, and telemetry logging.
"""

import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from collections import deque
from backend.config import Config
from backend.utils import logger, draw_hud_overlay
from backend.database import Database
from backend.camera_manager import camera_manager
from backend.dust_detector import dust_detector
from backend.esp32_controller import esp32_controller


class MonitoringService:
    """Orchestrates automated computer vision scans and ESP32 hardware actions."""

    def __init__(self):
        self.is_monitoring = False
        self.auto_mode = True  # If True, automatically dispatches ESP32 commands on state change
        self.scan_interval = Config.SCAN_INTERVAL_SECONDS
        self.consecutive_required = Config.CONSECUTIVE_REQUIRED

        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        # Operational metrics & state
        self.start_time: Optional[float] = None
        self.total_scans = 0
        self.current_state = "IDLE"  # "CLEAN", "MODERATELY DUSTY", "HEAVILY DUSTY", "IDLE"
        self.debounced_state = "CLEAN"  # "CLEAN" or "DUSTY"
        self.latest_result: Dict[str, Any] = {}

        # Temporal smoothing deque
        self.state_history = deque(maxlen=self.consecutive_required)

        # Periodic health check timing
        self.last_esp_check_time = 0.0

    def start_monitoring(self) -> bool:
        """Starts automated continuous monitoring thread."""
        with self.lock:
            if self.is_monitoring:
                logger.info("Monitoring service is already active.")
                return True

            # Ensure camera is running
            if not camera_manager.is_running:
                camera_manager.start()

            self.is_monitoring = True
            if self.start_time is None:
                self.start_time = time.time()

            self.thread = threading.Thread(
                target=self._monitoring_loop, daemon=True, name="MonitoringWorker"
            )
            self.thread.start()
            logger.info("SolarGuard automated monitoring service started.")
            Database.log_system_event("INFO", "MONITOR", "Automated dust monitoring service started.")
            return True

    def stop_monitoring(self):
        """Stops the automated monitoring thread."""
        with self.lock:
            self.is_monitoring = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

        logger.info("SolarGuard automated monitoring service stopped.")
        Database.log_system_event("INFO", "MONITOR", "Automated dust monitoring service stopped.")

    def set_auto_mode(self, enabled: bool):
        """Enables or disables automatic hardware LED dispatching."""
        with self.lock:
            self.auto_mode = enabled
        logger.info(f"Automatic ESP32 dispatch set to: {enabled}")

    def execute_single_scan(self) -> Dict[str, Any]:
        """
        Executes a one-shot dust detection scan on the current frame.
        Can be invoked manually from the UI or periodically by the loop.
        """
        live_frame = camera_manager.get_latest_frame()
        ref_frame = camera_manager.get_reference_image()

        if live_frame is None or ref_frame is None:
            err = "Cannot scan: Live camera frame or reference image not available."
            logger.warning(err)
            return {"status": "ERROR", "error": err}

        # 1. Run Computer Vision Analysis
        analysis = dust_detector.analyze(live_frame, ref_frame)
        status = analysis.get("status", "UNKNOWN")
        soiling = analysis.get("soiling_index", 0.0)
        confidence = analysis.get("confidence", 0.0)
        metrics = analysis.get("metrics", {})
        roi_coords = analysis.get("roi_coords")

        # 2. Temporal Smoothing & Debouncing
        # Maps granular status to binary state for hardware LED triggering
        is_dusty = status in ("MODERATELY DUSTY", "HEAVILY DUSTY")
        current_condition = "DUSTY" if is_dusty else "CLEAN"

        self.state_history.append(current_condition)

        # Check if condition is stable over N consecutive readings
        command_sent = "NONE"
        if len(self.state_history) == self.consecutive_required and all(
            s == current_condition for s in self.state_history
        ):
            if current_condition != self.debounced_state:
                # State transition detected!
                self.debounced_state = current_condition
                logger.info(f"State transition confirmed -> {self.debounced_state}")
                Database.log_system_event(
                    "INFO", "DETECTION", f"Panel state transitioned to {self.debounced_state} (Soiling: {soiling}%)"
                )

                # 3. Synchronize with ESP32 Hardware (if in auto mode)
                if self.auto_mode:
                    if self.debounced_state == "DUSTY":
                        success, resp = esp32_controller.send_dust_alert()
                        command_sent = "ALERT_ON (RED)" if success else "ALERT_FAILED"
                    else:
                        success, resp = esp32_controller.send_clean_status()
                        command_sent = "CLEAN_OFF (GREEN)" if success else "CLEAN_FAILED"

        # 4. Draw HUD Overlay onto live stream
        annotated = draw_hud_overlay(
            frame=live_frame,
            status=status,
            soiling_index=soiling,
            confidence=confidence,
            roi_coords=roi_coords,
            fps=camera_manager.current_fps,
            esp32_connected=esp32_controller.is_connected
        )
        camera_manager.set_annotated_frame(annotated)

        # 5. Log to SQLite Database
        esp_status_str = "CONNECTED" if esp32_controller.is_connected else "DISCONNECTED"
        db_id = Database.log_detection(
            soiling_index=soiling,
            status=status,
            confidence=confidence,
            metric_ssim=metrics.get("ssim", 0.0),
            metric_texture=metrics.get("texture_loss", 0.0),
            metric_contrast=metrics.get("contrast_loss", 0.0),
            metric_hsv=metrics.get("sat_loss", 0.0),
            esp32_status=esp_status_str,
            esp32_command_sent=command_sent
        )

        with self.lock:
            self.total_scans += 1
            self.current_state = status
            self.latest_result = {
                "id": db_id,
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "debounced_state": self.debounced_state,
                "soiling_index": soiling,
                "confidence": confidence,
                "metrics": metrics,
                "esp32_status": esp_status_str,
                "command_sent": command_sent
            }

        return self.latest_result

    def _monitoring_loop(self):
        """Main background loop executing periodic computer vision scans."""
        while self.is_monitoring:
            loop_start = time.time()

            try:
                # 1. Periodic ESP32 connectivity check (every 6 seconds)
                if loop_start - self.last_esp_check_time > 6.0:
                    self.last_esp_check_time = loop_start
                    # Non-blocking ping in background or quick check
                    threading.Thread(
                        target=esp32_controller.test_connection, daemon=True, name="ESP32Watchdog"
                    ).start()

                # 2. Run Scan
                self.execute_single_scan()

            except Exception as e:
                logger.error(f"Error during automated monitoring cycle: {e}")
                Database.log_system_event("ERROR", "MONITOR", f"Cycle exception: {e}")

            # Sleep remaining time of scan interval
            elapsed = time.time() - loop_start
            sleep_duration = max(0.1, self.scan_interval - elapsed)
            time.sleep(sleep_duration)

    def get_service_status(self) -> Dict[str, Any]:
        """Provides status summary for monitoring service."""
        with self.lock:
            uptime_seconds = int(time.time() - self.start_time) if (self.is_monitoring and self.start_time) else 0
            return {
                "is_monitoring": self.is_monitoring,
                "auto_mode": self.auto_mode,
                "uptime_seconds": uptime_seconds,
                "total_scans": self.total_scans,
                "current_state": self.current_state,
                "debounced_state": self.debounced_state,
                "latest_result": self.latest_result,
                "scan_interval": self.scan_interval,
                "consecutive_required": self.consecutive_required
            }


# Global monitoring service instance
monitoring_service = MonitoringService()
