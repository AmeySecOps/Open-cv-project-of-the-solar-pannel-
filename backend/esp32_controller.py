"""
SolarGuard AI - ESP32 Wi-Fi HTTP Controller
Manages robust Wi-Fi REST communication with the ESP32 microcontroller,
controls Red/Green status LEDs, monitors link health, and prevents redundant command spam.
"""

import time
import threading
from typing import Dict, Any, Optional, Tuple
import requests
from backend.config import Config
from backend.utils import logger
from backend.database import Database


class ESP32Controller:
    """Controls the ESP32 Wi-Fi Node via HTTP REST endpoints."""

    def __init__(self):
        self.ip = Config.ESP32_DEFAULT_IP
        self.port = Config.ESP32_PORT
        self.timeout = Config.ESP32_TIMEOUT
        self.max_retries = Config.ESP32_MAX_RETRIES

        self.is_connected = False
        self.last_ping_time: Optional[float] = None
        self.last_ping_latency_ms: Optional[float] = None
        self.last_error: Optional[str] = None

        # Tracks last commanded state to avoid spamming the ESP32 over Wi-Fi
        # "CLEAN" (Green ON, Red OFF) or "DUSTY" (Red ON, Green OFF)
        self.last_commanded_state: Optional[str] = None
        self.current_led_states = {"red": False, "green": False}
        self.current_servo_state = {"pin": 18, "angle": 0, "wiper_state": "IDLE_0"}
        self.last_dirt_percentage: float = 0.0

        self.lock = threading.Lock()
        self.session = requests.Session()

        # Attempt to load saved ESP32 IP from database if available
        saved_ip = Database.get_setting("esp32_ip")
        if saved_ip:
            self.ip = saved_ip

    @property
    def base_url(self) -> str:
        """Constructs the base URL for the ESP32 server."""
        return f"http://{self.ip}:{self.port}"

    def set_ip(self, ip_address: str) -> bool:
        """Sets and persists the ESP32 IP address."""
        clean_ip = ip_address.strip()
        if not clean_ip:
            return False
        with self.lock:
            self.ip = clean_ip
            # Reset state on IP change
            self.is_connected = False
            self.last_commanded_state = None
        Database.set_setting("esp32_ip", clean_ip)
        logger.info(f"ESP32 target IP set to: {self.ip}")
        return True

    def test_connection(self) -> Tuple[bool, str, Optional[float]]:
        """
        Pings the ESP32 /health or /status endpoint.
        Returns: (success: bool, message: str, latency_ms: Optional[float])
        """
        start_t = time.time()
        url = f"{self.base_url}/health"

        try:
            response = self.session.get(url, timeout=self.timeout)
            latency_ms = round((time.time() - start_t) * 1000, 1)

            if response.status_code == 200:
                with self.lock:
                    self.is_connected = True
                    self.last_ping_time = time.time()
                    self.last_ping_latency_ms = latency_ms
                    self.last_error = None
                logger.info(f"ESP32 connected at {self.ip} ({latency_ms}ms).")
                return True, f"Connected to ESP32 at {self.ip} ({latency_ms}ms)", latency_ms
            else:
                err_msg = f"ESP32 returned HTTP status {response.status_code}"
                self._handle_disconnect(err_msg)
                return False, err_msg, None
        except requests.exceptions.Timeout:
            err_msg = f"Connection timed out reaching {self.ip}"
            self._handle_disconnect(err_msg)
            return False, err_msg, None
        except requests.exceptions.ConnectionError:
            err_msg = f"Connection refused by {self.ip}. Check Wi-Fi and power."
            self._handle_disconnect(err_msg)
            return False, err_msg, None
        except Exception as e:
            err_msg = f"ESP32 ping error: {str(e)}"
            self._handle_disconnect(err_msg)
            return False, err_msg, None

    def _handle_disconnect(self, error_message: str):
        """Internal helper to mark disconnected status."""
        with self.lock:
            was_connected = self.is_connected
            self.is_connected = False
            self.last_error = error_message
        if was_connected:
            logger.warning(f"ESP32 connection lost: {error_message}")
            Database.log_system_event("WARNING", "ESP32", f"Connection lost: {error_message}")

    def fetch_hardware_status(self) -> Optional[Dict[str, Any]]:
        """Queries /status on ESP32 to retrieve hardware state and pin readings."""
        url = f"{self.base_url}/status"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                with self.lock:
                    self.is_connected = True
                    self.current_led_states = {
                        "red": bool(data.get("red_led", 0)),
                        "green": bool(data.get("green_led", 0))
                    }
                    if "servo_angle" in data:
                        self.current_servo_state["angle"] = int(data["servo_angle"])
                    if "wiper_state" in data:
                        self.current_servo_state["wiper_state"] = str(data["wiper_state"])
                    if "dirt_percentage" in data:
                        self.last_dirt_percentage = float(data["dirt_percentage"])
                return data
        except Exception as e:
            self._handle_disconnect(str(e))
        return None

    def send_dust_alert(self, force: bool = False, dirt_percentage: Optional[float] = None) -> Tuple[bool, str]:
        """
        Sends ON command to ESP32: Turn RED LED ON, GREEN LED OFF.
        Passes dirt percentage to trigger servo wipe on GPIO 18 if >= 70%.
        Avoids redundant HTTP calls if already in DUSTY state unless force=True.
        """
        with self.lock:
            if not force and self.last_commanded_state == "DUSTY":
                return True, "State already DUSTY (skipped redundant command)"

        url = f"{self.base_url}/led/on"
        if dirt_percentage is not None:
            url += f"?dirt={round(float(dirt_percentage), 1)}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.post(url, timeout=self.timeout)
                if resp.status_code == 200:
                    with self.lock:
                        self.is_connected = True
                        self.last_commanded_state = "DUSTY"
                        self.current_led_states = {"red": True, "green": False}
                        if dirt_percentage is not None:
                            self.last_dirt_percentage = float(dirt_percentage)
                            if self.last_dirt_percentage >= 70.0:
                                self.current_servo_state["angle"] = 180
                                self.current_servo_state["wiper_state"] = "HOLDING_180"
                        self.last_error = None
                    logger.info(f"Sent DUST ALERT to ESP32 (dirt: {dirt_percentage}%): RED ON, GREEN OFF.")
                    Database.log_system_event("INFO", "ESP32", f"Dust alert sent (dirt: {dirt_percentage}%): RED ON")
                    return True, "RED LED ON, GREEN LED OFF"
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{self.max_retries} failed sending dust alert to ESP32: {e}")
                time.sleep(0.2)

        self._handle_disconnect("Failed to send dust alert after retries.")
        return False, "ESP32 unreachable"

    def send_clean_status(self, force: bool = False, dirt_percentage: Optional[float] = None) -> Tuple[bool, str]:
        """
        Sends OFF command to ESP32: Turn GREEN LED ON, RED LED OFF, Servo stays at 0%.
        Avoids redundant HTTP calls if already in CLEAN state unless force=True.
        """
        with self.lock:
            if not force and self.last_commanded_state == "CLEAN":
                return True, "State already CLEAN (skipped redundant command)"

        url = f"{self.base_url}/led/off"
        if dirt_percentage is not None:
            url += f"?dirt={round(float(dirt_percentage), 1)}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.post(url, timeout=self.timeout)
                if resp.status_code == 200:
                    with self.lock:
                        self.is_connected = True
                        self.last_commanded_state = "CLEAN"
                        self.current_led_states = {"red": False, "green": True}
                        self.current_servo_state["angle"] = 0
                        self.current_servo_state["wiper_state"] = "IDLE_0"
                        self.last_dirt_percentage = float(dirt_percentage or 0.0)
                        self.last_error = None
                    logger.info(f"Sent CLEAN STATUS to ESP32 (dirt: {dirt_percentage}%): GREEN ON, RED OFF, SERVO AT 0.")
                    Database.log_system_event("INFO", "ESP32", f"Clean status sent (dirt: {dirt_percentage}%): GREEN ON")
                    return True, "GREEN LED ON, RED LED OFF"
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{self.max_retries} failed sending clean status to ESP32: {e}")
                time.sleep(0.2)

        self._handle_disconnect("Failed to send clean status after retries.")
        return False, "ESP32 unreachable"

    def manual_test_servo(self, angle: Optional[int] = None, action: Optional[str] = None) -> Tuple[bool, str]:
        """
        Manually commands the servo on GPIO 18 (e.g. angle=0..180 or action='wipe').
        """
        url = f"{self.base_url}/servo"
        payload: Dict[str, Any] = {}
        if angle is not None:
            payload["angle"] = int(angle)
        if action:
            payload["action"] = str(action)
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                with self.lock:
                    self.is_connected = True
                    if angle is not None:
                        self.current_servo_state["angle"] = int(angle)
                        self.current_servo_state["wiper_state"] = "IDLE_0" if angle == 0 else "MANUAL"
                    elif action == "wipe":
                        self.current_servo_state["angle"] = 180
                        self.current_servo_state["wiper_state"] = "HOLDING_180"
                msg = f"Manual servo test successful: {payload}"
                logger.info(msg)
                return True, msg
            return False, f"ESP32 returned error: {resp.text}"
        except Exception as e:
            self._handle_disconnect(str(e))
            return False, f"Failed to test servo: {str(e)}"

    def manual_test_led(self, led_type: str, state: bool) -> Tuple[bool, str]:
        """
        Manually controls a specific LED for verification testing.
        led_type: 'red' or 'green' or 'both'
        state: True (ON) or False (OFF)
        """
        url = f"{self.base_url}/led/manual"
        payload = {
            "led": led_type.lower(),
            "state": 1 if state else 0
        }
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                with self.lock:
                    self.is_connected = True
                    if led_type == "red":
                        self.current_led_states["red"] = state
                    elif led_type == "green":
                        self.current_led_states["green"] = state
                    self.last_commanded_state = "MANUAL"
                msg = f"Manual LED test successful: {led_type.upper()} set to {'ON' if state else 'OFF'}"
                logger.info(msg)
                return True, msg
            return False, f"ESP32 returned error: {resp.text}"
        except Exception as e:
            self._handle_disconnect(str(e))
            return False, f"Failed to test LED: {str(e)}"

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive ESP32 connectivity, pin, and servo telemetry."""
        with self.lock:
            return {
                "ip": self.ip,
                "port": self.port,
                "is_connected": self.is_connected,
                "last_ping_time": self.last_ping_time,
                "latency_ms": self.last_ping_latency_ms,
                "last_commanded_state": self.last_commanded_state,
                "current_leds": self.current_led_states,
                "servo": self.current_servo_state,
                "dirt_percentage": self.last_dirt_percentage,
                "error": self.last_error
            }


# Global ESP32 controller instance
esp32_controller = ESP32Controller()
