"""
SolarGuard AI - Camera Manager
Handles webcam discovery, multi-threaded frame acquisition, resolution configuration,
reference image management, and MJPEG video streaming.
"""

import time
import threading
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple, Union, Any
from urllib.parse import urlparse, urlunparse
import cv2
import numpy as np
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from backend.config import Config
from backend.database import Database
from backend.utils import logger, encode_image_to_base64


def normalize_camera_source(source: Any) -> Tuple[Any, str]:
    """
    Normalizes a camera source input into either an integer index or a valid HTTP/RTSP stream URL.
    Handles IPv4, IPv6 (bracketed or unbracketed), http/https normalization,
    and automatic default port (:8080) and path (/video).
    """
    if source is None:
        return 0, "usb"

    if isinstance(source, int):
        if source < 0:
            return -1, "simulation"
        return source, "usb"

    s = str(source).strip().strip("'\"")
    if not s:
        return 0, "usb"

    # Simulation keywords
    if s.lower() in ("-1", "sim", "simulation", "virtual"):
        return -1, "simulation"

    # Pure positive integer string: "0", "1", "2"
    if s.isdigit():
        return int(s), "usb"

    # Negative integer string
    if s.startswith("-") and s[1:].isdigit():
        return -1, "simulation"

    # Special keyword for saved ip_webcam
    if s.lower() in ("ip_webcam", "mobile", "phone"):
        saved = Database.get_setting("ip_webcam_url", Config.DEFAULT_IP_WEBCAM_URL)
        return normalize_camera_source(saved)

    # Detect scheme: IP Webcam uses plain HTTP by default.
    # If user typed https://, convert to http:// so OpenCV & requests don't fail on TLS.
    scheme = "http"
    if s.startswith("rtsp://"):
        scheme = "rtsp"
        s = s[7:]
    elif s.startswith("http://"):
        s = s[7:]
    elif s.startswith("https://"):
        scheme = "http"
        s = s[8:]

    # Separate host:port and path
    # Mobile IP Webcam IDs are addressed as base URLs like http://10.89.28.44:8080.
    # Do NOT append /video to the clean camera ID. If /video or /videofeed is present, strip it.
    path = ""
    if "/" in s:
        parts = s.split("/", 1)
        host_port = parts[0]
        remainder = "/" + parts[1].lstrip("/")
        if remainder.rstrip("/") in ("/video", "/videofeed", ""):
            path = ""
        else:
            path = remainder.rstrip("/")
    else:
        host_port = s
        path = ""

    # Parse host and port:
    # 1. Bracketed IPv6: e.g. [2401:4900:ad53:6f77::77]:8080 or [2401:...]
    if host_port.startswith("["):
        bracket_end = host_port.find("]")
        if bracket_end != -1:
            ip_part = host_port[1:bracket_end]
            port_part = host_port[bracket_end + 1:]
            port = port_part[1:] if port_part.startswith(":") else "8080"
            netloc = f"[{ip_part}]:{port}"
        else:
            netloc = f"{host_port}:8080"
    # 2. Unbracketed IPv6 (contains '::' or 2+ colons)
    elif host_port.count(":") >= 2:
        tokens = host_port.rsplit(":", 1)
        if len(tokens) == 2 and tokens[1] in ("8080", "8081", "4747", "8000", "80", "443", "8888"):
            ip_part = tokens[0]
            port = tokens[1]
        else:
            ip_part = host_port
            port = "8080"
        netloc = f"[{ip_part}]:{port}"
    # 3. IPv4 or hostname
    else:
        netloc = host_port if ":" in host_port else f"{host_port}:8080"

    normalized_url = f"{scheme}://{netloc}{path}"
    return normalized_url, "ip_webcam"


def get_network_diagnostics() -> Dict[str, Any]:
    """
    Retrieves network context: host IP, default router/hotspot gateway IP, and Wi-Fi SSID.
    Enables automatic identification of mobile phone hotspot IP (e.g. 10.89.28.44).
    """
    host_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    gateway_ip = None
    try:
        out = subprocess.check_output(["route", "print", "0.0.0.0"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                gateway_ip = parts[2]
                break
    except Exception:
        pass

    ssid = None
    try:
        wlan_out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], text=True, stderr=subprocess.DEVNULL)
        for line in wlan_out.splitlines():
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    break
    except Exception:
        pass

    suggested_url = f"http://{gateway_ip}:8080" if gateway_ip else "http://192.168.1.100:8080"
    is_hotspot = False
    if ssid and any(w in ssid.lower() for w in ("phone", "hotspot", "amey", "galaxy", "iphone", "pixel", "oneplus")):
        is_hotspot = True

    return {
        "host_ip": host_ip,
        "gateway_ip": gateway_ip,
        "ssid": ssid or "Connected Wi-Fi",
        "is_hotspot": is_hotspot,
        "suggested_url": suggested_url
    }


def scan_for_ip_webcams(timeout: float = 0.4) -> List[Dict[str, Any]]:
    """
    Rapidly scans the local network and hotspot gateway for active IP Webcam servers.
    Checks ports 8080, 8081, 4747 on the gateway and local subnet.
    """
    candidates = []
    diag = get_network_diagnostics()
    gw = diag.get("gateway_ip")
    if gw:
        candidates.append(gw)

    candidates.extend(["10.89.28.44", "192.168.43.1", "192.168.1.100", "192.168.1.105"])

    host_ip = diag.get("host_ip", "")
    if host_ip and host_ip.count(".") == 3:
        prefix = host_ip.rsplit(".", 1)[0]
        for i in (1, 2, 44, 100, 101, 105, 118, 150):
            candidates.append(f"{prefix}.{i}")

    # Remove duplicates preserving order
    seen = set()
    unique_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    discovered = []
    ports = [8080, 8081, 4747]

    def test_endpoint(ip, port):
        url = f"http://{ip}:{port}"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if s.connect_ex((ip, port)) == 0:
                s.close()
                ok, msg, details = probe_ip_webcam(url, timeout=0.8)
                if ok:
                    discovered.append({
                        "ip": ip,
                        "port": port,
                        "url": details.get("url", f"http://{ip}:{port}"),
                        "battery": details.get("battery"),
                        "resolution": details.get("resolution"),
                        "latency_ms": details.get("latency_ms"),
                        "device_name": f"📱 Mobile Phone ({ip}:{port})"
                    })
            else:
                s.close()
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=30) as ex:
        for ip in unique_candidates:
            for port in ports:
                ex.submit(test_endpoint, ip, port)

    return discovered


def probe_ip_webcam(url: str, timeout: float = 2.0) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Tests connectivity to a mobile phone running IP Webcam.
    Checks candidate endpoints (/status.json, /shot.jpg, /video) with verify=False for self-signed certificates.
    Returns (is_reachable, message, info_dict).
    """
    try:
        normalized_url, cam_type = normalize_camera_source(url)
        if cam_type != "ip_webcam":
            return False, f"Specified source '{url}' is not a valid network camera URL.", {}

        parsed = urlparse(normalized_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        details: Dict[str, Any] = {
            "url": normalized_url,
            "base_url": base_url,
            "stream_url": f"{base_url}/video",
            "snapshot_url": f"{base_url}/shot.jpg",
            "host": parsed.netloc,
            "latency_ms": None,
            "stream_mode": "video"
        }

        t0 = time.time()

        # 1. First probe status.json (instant JSON response from IP Webcam)
        for scheme in ("http", "https"):
            probe_base = f"{scheme}://{parsed.netloc}"
            try:
                resp = requests.get(f"{probe_base}/status.json", timeout=timeout, verify=False)
                if resp.status_code == 200:
                    details["latency_ms"] = round((time.time() - t0) * 1000, 1)
                    details["base_url"] = probe_base
                    details["url"] = normalized_url
                    try:
                        data = resp.json()
                        details["status_json"] = data
                        if "battery" in data:
                            details["battery"] = data.get("battery")
                        if "curvideo" in data:
                            details["resolution"] = data.get("curvideo")
                    except Exception:
                        pass
                    return True, f"Connected to Mobile IP Webcam at {parsed.netloc} ({details['latency_ms']}ms).", details
            except Exception:
                pass

        # 2. Probe shot.jpg (snapshot endpoint supported by all versions of IP Webcam)
        try:
            resp = requests.get(f"{base_url}/shot.jpg", timeout=timeout, verify=False, stream=True)
            if resp.status_code == 200:
                details["latency_ms"] = round((time.time() - t0) * 1000, 1)
                details["stream_mode"] = "snapshot"
                details["url"] = normalized_url
                resp.close()
                return True, f"Connected to IP Webcam snapshot feed at {parsed.netloc} ({details['latency_ms']}ms).", details
        except Exception:
            pass

        # 3. Probe video stream endpoint directly
        stream_probe_url = f"{base_url}/video" if not parsed.path else normalized_url
        try:
            resp = requests.get(stream_probe_url, stream=True, timeout=timeout, verify=False)
            if resp.status_code == 200:
                details["latency_ms"] = round((time.time() - t0) * 1000, 1)
                details["stream_mode"] = "mjpeg"
                details["url"] = normalized_url
                resp.close()
                return True, f"Connected to camera stream at {parsed.netloc} ({details['latency_ms']}ms).", details
        except Exception:
            pass

        return False, (
            f"Could not connect to IP Webcam at {parsed.netloc}. "
            "Please ensure 'Start server' is running in the IP Webcam app on your phone, "
            "and your laptop is connected to the same Wi-Fi/Hotspot."
        ), details

    except Exception as e:
        return False, f"Failed to reach IP Webcam: {str(e)}", {}


def control_ip_webcam(url: str, command: str) -> Tuple[bool, str]:
    """
    Sends hardware control commands to mobile phone via IP Webcam REST API.
    Supported commands:
    - 'torch_on': Turn on mobile flashlight LED
    - 'torch_off': Turn off mobile flashlight LED
    - 'camera_front': Switch to front-facing camera
    - 'camera_back': Switch to rear/main camera
    - 'focus': Trigger phone autofocus
    """
    try:
        normalized_url, cam_type = normalize_camera_source(url)
        if cam_type != "ip_webcam":
            return False, "Not an IP Webcam stream."

        parsed = urlparse(normalized_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        endpoint = None
        if command == "torch_on":
            endpoint = f"{base_url}/enabletorch"
        elif command == "torch_off":
            endpoint = f"{base_url}/disabletorch"
        elif command == "camera_front":
            endpoint = f"{base_url}/settings/ffc?set=on"
        elif command == "camera_back":
            endpoint = f"{base_url}/settings/ffc?set=off"
        elif command == "focus":
            endpoint = f"{base_url}/focus"
        else:
            return False, f"Unsupported command '{command}'"

        resp = requests.get(endpoint, timeout=2.5, verify=False)
        if resp.status_code in (200, 204):
            return True, f"Command '{command}' executed successfully."
        return False, f"Phone returned HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Command execution failed: {e}"


class CameraManager:
    """Manages video capture hardware, threading, Mobile IP Webcam, and reference image storage."""

    def __init__(self):
        self.width = Config.DEFAULT_WIDTH
        self.height = Config.DEFAULT_HEIGHT
        self.fps_target = Config.DEFAULT_FPS

        # Persistent / configured source
        raw_source = Database.get_setting("camera_source", Config.DEFAULT_CAMERA_SOURCE)
        self.camera_source, self.camera_type = normalize_camera_source(raw_source)
        self.camera_index = self.camera_source if self.camera_type == "usb" else "ip_webcam"

        # Mobile IP Webcam properties
        self.ip_camera_url = Database.get_setting("ip_webcam_url", Config.DEFAULT_IP_WEBCAM_URL)
        self.is_ip_camera = (self.camera_type == "ip_webcam")
        self.stream_url: Optional[str] = None
        self.snapshot_url: Optional[str] = None
        self.is_snapshot_mode = False
        self.torch_active = False
        self.camera_facing = "back"

        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        self.latest_frame: Optional[np.ndarray] = None
        self.annotated_frame: Optional[np.ndarray] = None
        self.last_frame_time = 0.0
        self.current_fps = 0.0
        self.frame_count = 0
        self.error_message: Optional[str] = None

        # Simulation mode toggle (creates realistic synthetic solar panel frames when no camera is attached)
        self.simulation_mode = (self.camera_type == "simulation")
        self.simulated_dust_level = 0.0  # 0 to 100

        # Cached reference image
        self._reference_image: Optional[np.ndarray] = None
        self.load_reference_image()

    def discover_cameras(self, max_probes: int = 4) -> List[Dict[str, Any]]:
        """
        Scans available camera devices: USB webcams, configured Mobile IP Webcam,
        and the synthetic virtual test generator.
        """
        available = []

        # 1. Probed physical USB cameras
        for index in range(max_probes):
            try:
                cap = cv2.VideoCapture(index)
                if cap.isOpened():
                    ret, frame = cap.read()
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    if ret and frame is not None:
                        available.append({
                            "index": index,
                            "name": f"USB Video Camera {index}",
                            "resolution": f"{w}x{h}",
                            "status": "Available",
                            "type": "usb"
                        })
                else:
                    cap.release()
            except Exception as e:
                logger.debug(f"Camera probe index {index} failed: {e}")

        # 2. Configured / saved Mobile IP Webcam
        ip_url = self.ip_camera_url or Database.get_setting("ip_webcam_url", Config.DEFAULT_IP_WEBCAM_URL)
        parsed_ip = urlparse(ip_url).netloc or "Wi-Fi Phone"
        is_active_ip = (self.is_ip_camera and not self.simulation_mode and self.is_running)
        available.append({
            "index": "ip_webcam",
            "name": f"📱 Mobile IP Webcam ({parsed_ip})",
            "resolution": f"{self.width}x{self.height}",
            "status": "Active" if is_active_ip else "Configured",
            "type": "ip_webcam",
            "url": ip_url
        })

        # 3. Virtual Solar Test Generator
        available.append({
            "index": -1,
            "name": "Virtual Solar Test Generator (Simulation)",
            "resolution": f"{self.width}x{self.height}",
            "status": "Active" if (self.simulation_mode and self.is_running) else "Virtual",
            "type": "simulation"
        })

        logger.info(f"Discovered {len(available)} camera device option(s).")
        return available

    def start(self, camera_source: Optional[Union[int, str]] = None, camera_index: Optional[Union[int, str]] = None) -> bool:
        """
        Starts the background camera acquisition thread.
        Supports:
        - USB camera index (int >= 0)
        - Mobile IP Webcam stream URL (str e.g. 'http://192.168.1.100:8080/video')
        - Virtual simulation (-1)
        """
        with self.lock:
            if self.is_running:
                logger.info("Camera stream already running.")
                return True

            arg = camera_source if camera_source is not None else camera_index
            if arg is not None:
                self.camera_source, self.camera_type = normalize_camera_source(arg)
                self.is_ip_camera = (self.camera_type == "ip_webcam")
                self.camera_index = self.camera_source if self.camera_type == "usb" else "ip_webcam"
                if self.is_ip_camera:
                    self.ip_camera_url = str(self.camera_source)
                    Database.set_setting("ip_webcam_url", self.ip_camera_url)
                Database.set_setting("camera_source", str(self.camera_source))

            self.error_message = None

            # Simulation mode explicitly requested or source is -1
            if self.camera_type == "simulation" or self.camera_source == -1:
                self.simulation_mode = True
                self.is_running = True
                self.thread = threading.Thread(target=self._capture_loop, daemon=True, name="SimulatedCameraWorker")
                self.thread.start()
                logger.info("Started virtual camera stream in simulation mode.")
                return True

            # Open physical camera or IP Webcam network stream
            self.simulation_mode = False
            self.is_snapshot_mode = False
            self.annotated_frame = None

            try:
                logger.info(f"Connecting to camera source: {self.camera_source} (type: {self.camera_type})")
                
                # Setup snapshot and stream URLs for IP Webcam
                if self.is_ip_camera:
                    parsed = urlparse(str(self.camera_source))
                    base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
                    path = parsed.path.rstrip("/")
                    if path.endswith(".jpg"):
                        self.stream_url = str(self.camera_source)
                        self.is_snapshot_mode = True
                    elif path in ("/video", "/videofeed") or path.endswith(".mjpg"):
                        self.stream_url = str(self.camera_source)
                    else:
                        self.stream_url = f"{base_url}/video"

                    self.snapshot_url = f"{base_url}/shot.jpg"
                    reachable, probe_msg, details = probe_ip_webcam(str(self.camera_source), timeout=2.5)
                    if not reachable:
                        logger.warning(f"Mobile IP Webcam unreachable: {probe_msg}. Falling back to virtual simulation.")
                        self.error_message = probe_msg
                        self.simulation_mode = True
                        self.cap = None

                if not self.simulation_mode:
                    capture_endpoint = self.stream_url if (self.is_ip_camera and self.stream_url) else self.camera_source
                    self.cap = cv2.VideoCapture(capture_endpoint)

                    if not self.cap.isOpened():
                        # Before falling back to simulation, check if snapshot mode works
                        if self.is_ip_camera and self.snapshot_url:
                            ok, _, _ = probe_ip_webcam(self.snapshot_url, timeout=1.5)
                            if ok:
                                self.is_snapshot_mode = True
                                self.simulation_mode = False
                                self.cap = None
                                logger.info(f"Stream endpoint failed, but snapshot endpoint is available. Using snapshot feed: {self.snapshot_url}")

                        if not self.is_snapshot_mode:
                            msg = (
                                f"Could not connect to Mobile IP Webcam at {self.camera_source}. Ensure 'Start server' is running in IP Webcam on your phone and on same Wi-Fi."
                                if self.is_ip_camera else
                                f"Could not open physical camera device {self.camera_source}."
                            )
                            logger.warning(f"{msg} Falling back to virtual simulation generator.")
                            self.error_message = msg
                            self.simulation_mode = True
                            self.cap = None
                    else:
                        self.simulation_mode = False
                        self.is_snapshot_mode = False
                        # Minimize buffer lag for live network streams
                        try:
                            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        except Exception:
                            pass
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                        self.cap.set(cv2.CAP_PROP_FPS, self.fps_target)

                        # Verify read
                        ret, test_frame = self.cap.read()
                        if not ret or test_frame is None:
                            logger.warning("Camera opened but failed to capture initial frame.")
                            if self.is_ip_camera and self.snapshot_url:
                                self.is_snapshot_mode = True
                                self.simulation_mode = False
                            else:
                                self.simulation_mode = True
                            self.cap.release()
                            self.cap = None
                        else:
                            self.latest_frame = test_frame

                self.is_running = True
                self.thread = threading.Thread(target=self._capture_loop, daemon=True, name="CameraCaptureWorker")
                self.thread.start()
                logger.info(f"Camera manager started on source {self.camera_source} (Simulation={self.simulation_mode}, IP={self.is_ip_camera}, SnapshotMode={self.is_snapshot_mode}).")
                return True
            except Exception as e:
                self.error_message = f"Failed to start camera: {e}"
                logger.error(self.error_message)
                self.simulation_mode = True
                self.is_running = True
                self.thread = threading.Thread(target=self._capture_loop, daemon=True, name="CameraSimFallback")
                self.thread.start()
                return True

    def stop(self):
        """Stops the camera capture thread and releases hardware resources."""
        with self.lock:
            self.is_running = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception as e:
                    logger.error(f"Error releasing camera: {e}")
                self.cap = None
            self.annotated_frame = None
            logger.info("Camera stream stopped.")

    def _capture_loop(self):
        """Dedicated background thread to continuously fetch frames, prevent buffer lag, and auto-recover network streams."""
        prev_time = time.time()
        consecutive_failures = 0
        last_reconnect_attempt = 0.0
        reconnect_interval = 3.0
        session = requests.Session()
        session.trust_env = False

        while self.is_running:
            loop_start = time.time()

            if not self.simulation_mode:
                frame = None
                # 1. Attempt read from cv2.VideoCapture stream
                if self.cap is not None:
                    try:
                        if self.cap.isOpened():
                            ret, cap_frame = self.cap.read()
                            if ret and cap_frame is not None and cap_frame.size > 0:
                                frame = cap_frame
                    except Exception as e:
                        logger.debug(f"Frame read exception: {e}")

                # 2. Seamless fallback to HTTP snapshot polling if cv2.VideoCapture drops or fails on IP camera
                if frame is None and self.is_ip_camera and self.snapshot_url:
                    try:
                        resp = session.get(self.snapshot_url, timeout=0.8, verify=False)
                        if resp.status_code == 200 and resp.content:
                            arr = np.frombuffer(resp.content, np.uint8)
                            s_frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if s_frame is not None and s_frame.size > 0:
                                frame = s_frame
                    except Exception:
                        pass

                if frame is not None and frame.size > 0:
                    consecutive_failures = 0
                    if frame.shape[1] != self.width or frame.shape[0] != self.height:
                        frame = cv2.resize(frame, (self.width, self.height))
                    with self.lock:
                        self.latest_frame = frame
                        self.frame_count += 1
                        self.error_message = None
                else:
                    consecutive_failures += 1

                # Automatic reconnection for IP Webcam network streams
                if self.is_ip_camera and consecutive_failures >= 15:
                    now = time.time()
                    if now - last_reconnect_attempt >= reconnect_interval:
                        last_reconnect_attempt = now
                        logger.warning(f"IP camera stream stalled ({consecutive_failures} failures). Reconnecting to {self.camera_source}...")
                        try:
                            if self.cap is not None:
                                self.cap.release()
                        except Exception:
                            pass
                        try:
                            reconnect_endpoint = self.stream_url if (self.is_ip_camera and self.stream_url) else self.camera_source
                            new_cap = cv2.VideoCapture(reconnect_endpoint)
                            if new_cap.isOpened():
                                try:
                                    new_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                except Exception:
                                    pass
                                self.cap = new_cap
                                consecutive_failures = 0
                                logger.info(f"Successfully reconnected to IP camera: {self.camera_source}")
                            else:
                                self.cap = None
                        except Exception as re_err:
                            logger.debug(f"Stream reconnection failed: {re_err}")
            else:
                # Simulation mode generator
                with self.lock:
                    self.latest_frame = self._generate_synthetic_solar_frame(self.simulated_dust_level)
                    self.frame_count += 1

            # FPS calculation
            curr_time = time.time()
            dt = curr_time - prev_time
            if dt > 0.0:
                self.current_fps = 0.9 * self.current_fps + 0.1 * (1.0 / dt)
            prev_time = curr_time

            # Regulate frame rate to ~30 FPS
            elapsed = time.time() - loop_start
            sleep_time = max(0.001, (1.0 / self.fps_target) - elapsed)
            time.sleep(sleep_time)

    def _generate_synthetic_solar_frame(self, dust_level: float = 0.0) -> np.ndarray:
        """
        Generates a realistic synthetic solar panel test frame.
        Simulates silicon wafer dark-blue crystalline texture, silver busbars, gridlines,
        and configurable dust accumulation (matte grayish-tan particles, contrast reduction).
        """
        w, h = self.width, self.height
        # Base panel background: Dark monocrystalline blue-black
        frame = np.zeros((h, w, 3), dtype=np.uint8)

        # Panel frame border
        pad_x, pad_y = int(w * 0.06), int(h * 0.08)
        cv2.rectangle(frame, (pad_x, pad_y), (w - pad_x, h - pad_y), (40, 45, 50), -1)  # Aluminum frame

        # Solar cell area
        inner_x1, inner_y1 = pad_x + 8, pad_y + 8
        inner_x2, inner_y2 = w - pad_x - 8, h - pad_y - 8
        # Deep blue/indigo solar cell color (BGR: 70, 35, 15)
        cv2.rectangle(frame, (inner_x1, inner_y1), (inner_x2, inner_y2), (75, 40, 18), -1)

        # Add subtle crystalline wafer texture
        noise = np.random.normal(0, 4, (inner_y2 - inner_y1, inner_x2 - inner_x1, 3)).astype(np.int16)
        cell_area = frame[inner_y1:inner_y2, inner_x1:inner_x2].astype(np.int16) + noise
        frame[inner_y1:inner_y2, inner_x1:inner_x2] = np.clip(cell_area, 0, 255).astype(np.uint8)

        # Draw silver busbars (vertical thick conducting ribbons)
        busbar_color = (210, 215, 220)
        num_busbars = 3
        cell_w = inner_x2 - inner_x1
        for i in range(1, num_busbars + 1):
            bx = inner_x1 + int(cell_w * (i / (num_busbars + 1)))
            cv2.line(frame, (bx, inner_y1), (bx, inner_y2), busbar_color, 3)

        # Draw fine grid fingers (horizontal thin lines)
        cell_h = inner_y2 - inner_y1
        finger_color = (170, 180, 190)
        num_fingers = 18
        for j in range(1, num_fingers + 1):
            fy = inner_y1 + int(cell_h * (j / (num_fingers + 1)))
            cv2.line(frame, (inner_x1, fy), (inner_x2, fy), finger_color, 1)

        # Solar cell wafer borders (4x2 cell matrix)
        cols, rows = 4, 2
        for c in range(1, cols):
            cx = inner_x1 + int(cell_w * (c / cols))
            cv2.line(frame, (cx, inner_y1), (cx, inner_y2), (25, 25, 30), 2)
        for r in range(1, rows):
            ry = inner_y1 + int(cell_h * (r / rows))
            cv2.line(frame, (inner_x1, ry), (inner_x2, ry), (25, 25, 30), 2)

        # Apply simulated dust layer if dust_level > 0
        if dust_level > 1.0:
            alpha = min(0.85, (dust_level / 100.0) * 0.80)
            dust_layer = np.zeros_like(frame)
            # Sandy/yellowish-tan dust tone (BGR: 110, 150, 180)
            dust_color = np.array([120, 155, 185], dtype=np.uint8)
            dust_layer[inner_y1:inner_y2, inner_x1:inner_x2] = dust_color

            # Add graininess and clump distribution to dust
            grain = np.random.normal(0, 18, (inner_y2 - inner_y1, inner_x2 - inner_x1, 3)).astype(np.int16)
            dust_grainy = dust_layer[inner_y1:inner_y2, inner_x1:inner_x2].astype(np.int16) + grain
            dust_layer[inner_y1:inner_y2, inner_x1:inner_x2] = np.clip(dust_grainy, 0, 255).astype(np.uint8)

            # Blend dust over solar cell
            blended = cv2.addWeighted(
                frame[inner_y1:inner_y2, inner_x1:inner_x2],
                1.0 - alpha,
                dust_layer[inner_y1:inner_y2, inner_x1:inner_x2],
                alpha,
                0
            )
            # Dust blurs high frequencies (soiling scatter effect)
            ksize = int(max(1, int((dust_level / 100.0) * 9)))
            if ksize % 2 == 0:
                ksize += 1
            if ksize >= 3:
                blended = cv2.GaussianBlur(blended, (ksize, ksize), 0)

            frame[inner_y1:inner_y2, inner_x1:inner_x2] = blended

        # Watermark/badge indicating synthetic source when active
        if self.simulation_mode:
            cv2.putText(
                frame, "[SIMULATED TEST GENERATOR]", (pad_x + 10, h - pad_y - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 215, 255), 1, cv2.LINE_AA
            )

        return frame

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Returns a copy of the latest raw video frame."""
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            # If camera started but no frame yet, generate placeholder
            return self._generate_synthetic_solar_frame(0.0)

    def set_annotated_frame(self, frame: np.ndarray):
        """Updates the annotated frame to be streamed to web clients."""
        with self.lock:
            self.annotated_frame = frame

    def get_stream_frame(self) -> np.ndarray:
        """Returns the frame for live web stream (annotated if available, else raw)."""
        with self.lock:
            if self.annotated_frame is not None:
                return self.annotated_frame
            if self.latest_frame is not None:
                return self.latest_frame
            return self._generate_synthetic_solar_frame(0.0)

    # Reference Image Management
    def capture_clean_reference(self) -> Tuple[bool, str]:
        """
        Captures the current camera frame and saves it as clean reference.
        Saves to Config.REFERENCE_IMAGE_PATH.
        """
        frame = self.get_latest_frame()
        if frame is None or frame.size == 0:
            return False, "No valid camera frame available to capture reference."

        try:
            Config.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
            success = cv2.imwrite(str(Config.REFERENCE_IMAGE_PATH), frame)
            if success:
                self._reference_image = frame.copy()
                logger.info(f"Clean reference image saved to {Config.REFERENCE_IMAGE_PATH}")
                return True, "Clean reference image captured and saved successfully."
            else:
                return False, "Failed to write reference image file to disk."
        except Exception as e:
            logger.error(f"Error saving clean reference image: {e}")
            return False, str(e)

    def load_reference_image(self) -> Optional[np.ndarray]:
        """Loads the saved clean reference image from disk if available."""
        if Config.REFERENCE_IMAGE_PATH.exists():
            try:
                img = cv2.imread(str(Config.REFERENCE_IMAGE_PATH))
                if img is not None:
                    self._reference_image = img
                    logger.info("Clean reference image loaded from disk.")
                    return self._reference_image
            except Exception as e:
                logger.error(f"Failed to load reference image: {e}")

        # If no reference image exists yet, create an initial synthetic clean reference
        logger.info("No saved clean reference found on disk. Generating default clean reference.")
        clean_img = self._generate_synthetic_solar_frame(dust_level=0.0)
        try:
            Config.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(Config.REFERENCE_IMAGE_PATH), clean_img)
            self._reference_image = clean_img
        except Exception as e:
            logger.error(f"Failed to write default clean reference: {e}")
        return self._reference_image

    def set_reference_image(self, image: np.ndarray) -> bool:
        """Saves a custom uploaded image as clean reference."""
        if image is None or image.size == 0:
            return False
        try:
            Config.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(Config.REFERENCE_IMAGE_PATH), image)
            self._reference_image = image.copy()
            logger.info("Custom reference image set and saved successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to set custom reference image: {e}")
            return False

    def get_reference_image(self) -> Optional[np.ndarray]:
        """Returns the loaded clean reference image."""
        if self._reference_image is None:
            return self.load_reference_image()
        return self._reference_image.copy()

    def get_reference_base64(self) -> str:
        """Returns the clean reference image as a base64 string for UI display."""
        ref = self.get_reference_image()
        if ref is not None:
            return encode_image_to_base64(ref)
        return ""

    def toggle_torch(self) -> Tuple[bool, str]:
        """Toggles the mobile phone flashlight LED on/off via IP Webcam."""
        if not self.is_ip_camera:
            return False, "Torch control is only available on Mobile IP Webcam."
        target_cmd = "torch_off" if self.torch_active else "torch_on"
        success, msg = control_ip_webcam(self.ip_camera_url, target_cmd)
        if success:
            self.torch_active = not self.torch_active
            return True, f"Mobile flashlight turned {'ON' if self.torch_active else 'OFF'}."
        return False, msg

    def flip_camera(self) -> Tuple[bool, str]:
        """Flips mobile camera between front and rear cameras via IP Webcam."""
        if not self.is_ip_camera:
            return False, "Camera flipping is only available on Mobile IP Webcam."
        target_cmd = "camera_front" if self.camera_facing == "back" else "camera_back"
        success, msg = control_ip_webcam(self.ip_camera_url, target_cmd)
        if success:
            self.camera_facing = "front" if self.camera_facing == "back" else "back"
            return True, f"Switched to mobile {self.camera_facing} camera."
        return False, msg

    def trigger_focus(self) -> Tuple[bool, str]:
        """Triggers mobile phone autofocus via IP Webcam."""
        if not self.is_ip_camera:
            return False, "Autofocus trigger is only available on Mobile IP Webcam."
        return control_ip_webcam(self.ip_camera_url, "focus")

    def get_status(self) -> Dict[str, Any]:
        """Returns status payload for the camera subsystem."""
        with self.lock:
            return {
                "is_running": self.is_running,
                "camera_index": self.camera_index,
                "camera_source": str(self.camera_source),
                "camera_type": self.camera_type,
                "is_ip_camera": self.is_ip_camera,
                "ip_camera_url": self.ip_camera_url,
                "torch_active": self.torch_active,
                "camera_facing": self.camera_facing,
                "simulation_mode": self.simulation_mode,
                "simulated_dust_level": self.simulated_dust_level,
                "resolution": f"{self.width}x{self.height}",
                "fps": round(self.current_fps, 1),
                "frame_count": self.frame_count,
                "has_reference": self._reference_image is not None,
                "error": self.error_message
            }


# Global camera manager instance
camera_manager = CameraManager()
