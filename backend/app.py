"""
SolarGuard AI - Flask Web Application & REST API Server
Provides high-performance RESTful endpoints, live MJPEG video stream,
and IoT control telemetry.
"""

import os
import sys
import io
import re
import time
from pathlib import Path

# Add project root directory to sys.path so backend imports work regardless of launch method
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from flask import Flask, render_template, Response, request, jsonify, send_file
import cv2
import numpy as np

from backend.config import Config
from backend.utils import logger, decode_base64_to_image
from backend.database import Database
from backend.camera_manager import (
    camera_manager,
    probe_ip_webcam,
    control_ip_webcam,
    normalize_camera_source,
    get_network_diagnostics,
    scan_for_ip_webcams
)
from backend.dust_detector import dust_detector
from backend.model_trainer import model_trainer
from backend.esp32_controller import esp32_controller
from backend.monitoring_service import monitoring_service

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR)
)
app.config["SECRET_KEY"] = Config.SECRET_KEY


def is_valid_ip_or_host(ip_str: str) -> bool:
    """Validates IPv4 format or standard network hostname."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    ip_clean = ip_str.strip()
    # IPv4 regex: 0.0.0.0 to 255.255.255.255
    ip_regex = r"^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$"
    # Hostname regex or localhost
    host_regex = r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$|^localhost$"
    return bool(re.match(ip_regex, ip_clean) or re.match(host_regex, ip_clean))


# ---------------------------------------------------------
# Web Page Routes
# ---------------------------------------------------------
@app.route("/")
@app.route("/dashboard")
def index():
    """Renders the main SolarGuard AI industrial dashboard."""
    return render_template("dashboard.html")


# ---------------------------------------------------------
# Video Streaming Route (MJPEG)
# ---------------------------------------------------------
def generate_mjpeg_frames():
    """Generates JPEG frame byte stream for HTML5 <img src='/video_feed'>."""
    while True:
        frame = camera_manager.get_stream_frame()
        if frame is None:
            time.sleep(0.04)
            continue

        ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ret:
            time.sleep(0.04)
            continue

        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )
        time.sleep(0.033)  # ~30 FPS stream rate


@app.route("/video_feed")
def video_feed():
    """Live video stream endpoint."""
    return Response(
        generate_mjpeg_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ---------------------------------------------------------
# System Status API
# ---------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def get_system_status():
    """Returns top-level system health, state, and quick metrics."""
    mon_status = monitoring_service.get_service_status()
    cam_status = camera_manager.get_status()
    esp_status = esp32_controller.get_status()
    latest_det = monitoring_service.latest_result or Database.get_latest_detection() or {}

    return jsonify({
        "success": True,
        "timestamp": time.time(),
        "monitoring": mon_status,
        "camera": cam_status,
        "esp32": esp_status,
        "latest_detection": latest_det,
        "clean_threshold": dust_detector.threshold_clean,
        "heavy_threshold": dust_detector.threshold_heavy,
        "roi": dust_detector.roi
    })


# ---------------------------------------------------------
# Camera APIs
# ---------------------------------------------------------
@app.route("/api/camera/devices", methods=["GET"])
def get_camera_devices():
    """Scans and lists connected video devices."""
    devices = camera_manager.discover_cameras()
    return jsonify({"success": True, "devices": devices})


@app.route("/api/camera/status", methods=["GET"])
def get_camera_status():
    """Returns camera state, resolution, FPS, and status."""
    return jsonify({"success": True, "camera": camera_manager.get_status()})


@app.route("/api/camera/start", methods=["POST"])
def start_camera():
    """Starts camera frame capture with either USB index or Mobile IP Webcam URL."""
    data = request.get_json(silent=True) or {}
    source = data.get("camera_source") if data.get("camera_source") is not None else data.get("camera_index")
    if source is None:
        source = data.get("url")

    success = camera_manager.start(camera_source=source)
    return jsonify({
        "success": success,
        "message": "Camera started" if success else "Failed to start camera",
        "camera": camera_manager.get_status()
    })


@app.route("/api/camera/stop", methods=["POST"])
def stop_camera():
    """Stops camera frame capture."""
    camera_manager.stop()
    return jsonify({
        "success": True,
        "message": "Camera stopped",
        "camera": camera_manager.get_status()
    })


@app.route("/api/camera/select", methods=["POST"])
def select_camera():
    """Selects camera source (USB device index or Mobile IP Webcam URL) and restarts stream."""
    data = request.get_json(silent=True) or {}
    source = data.get("camera_source") if data.get("camera_source") is not None else data.get("camera_index")
    if source is None:
        source = data.get("url")

    if source is None:
        return jsonify({"success": False, "error": "Validation error: camera_source or camera_index is required."}), 400

    was_running = camera_manager.is_running
    camera_manager.stop()
    success = camera_manager.start(camera_source=source)
    Database.log_system_event("INFO", "CAMERA", f"Switched camera source to {camera_manager.camera_source}")

    return jsonify({
        "success": success,
        "camera_source": str(camera_manager.camera_source),
        "camera_index": camera_manager.camera_index,
        "camera": camera_manager.get_status()
    })


# ---------------------------------------------------------
# Mobile IP Webcam Dedicated APIs
# ---------------------------------------------------------
@app.route("/api/camera/ip-webcam/connect", methods=["POST"])
def connect_ip_webcam():
    """Connects to a mobile phone running IP Webcam by URL or IP:Port."""
    data = request.get_json(silent=True) or {}
    raw_url = data.get("url")
    ip = data.get("ip")
    port = data.get("port", 8080)

    if not raw_url and not ip:
        return jsonify({"success": False, "error": "Validation error: Mobile phone IP address or stream URL is required."}), 400

    target = raw_url.strip() if raw_url else f"{str(ip).strip()}:{port}"
    normalized_url, cam_type = normalize_camera_source(target)

    # Fast probe to check if mobile IP Webcam responds
    reachable, probe_msg, details = probe_ip_webcam(normalized_url, timeout=2.0)

    if not reachable:
        diag = get_network_diagnostics()
        gw = diag.get("gateway_ip")
        ssid = diag.get("ssid")
        tip = f" (Tip: Connected to Wi-Fi '{ssid}'. On phone hotspot, camera IP is http://{gw}:8080)" if gw else ""
        error_msg = f"{probe_msg}{tip}"
        Database.log_system_event("WARNING", "CAMERA", f"Mobile IP Webcam connection failed: {normalized_url} - {probe_msg}")
        return jsonify({
            "success": False,
            "reachable": False,
            "error": error_msg,
            "message": error_msg,
            "url": normalized_url,
            "diagnostics": diag
        }), 400

    # Switch camera stream to verified working URL
    camera_manager.stop()
    working_url = details.get("url", normalized_url)
    started = camera_manager.start(camera_source=working_url)
    Database.set_setting("ip_webcam_url", working_url)
    Database.set_setting("camera_source", working_url)
    Database.log_system_event("INFO", "CAMERA", f"Mobile IP Webcam connected to {working_url}")

    return jsonify({
        "success": started,
        "reachable": True,
        "message": probe_msg,
        "url": working_url,
        "details": details,
        "camera": camera_manager.get_status()
    })


@app.route("/api/camera/ip-webcam/test", methods=["POST"])
def test_ip_webcam():
    """Pings mobile phone IP Webcam server without disrupting active stream."""
    data = request.get_json(silent=True) or {}
    raw_url = data.get("url")
    ip = data.get("ip")
    port = data.get("port", 8080)

    if not raw_url and not ip:
        raw_url = camera_manager.ip_camera_url

    target = raw_url.strip() if raw_url else f"{str(ip).strip()}:{port}"
    normalized_url, cam_type = normalize_camera_source(target)

    reachable, probe_msg, details = probe_ip_webcam(normalized_url, timeout=2.0)
    return jsonify({
        "success": reachable,
        "message": probe_msg,
        "url": details.get("url", normalized_url),
        "details": details
    })


@app.route("/api/camera/ip-webcam/discover", methods=["GET"])
def discover_ip_webcam():
    """Scans local network / hotspot for active IP Webcam mobile cameras."""
    diag = get_network_diagnostics()
    discovered = scan_for_ip_webcams(timeout=0.4)
    return jsonify({
        "success": True,
        "diagnostics": diag,
        "discovered": discovered,
        "suggested_url": diag.get("suggested_url", "http://10.89.28.44:8080")
    })


@app.route("/api/camera/ip-webcam/diagnostics", methods=["GET"])
def get_ip_webcam_diagnostics():
    """Returns network diagnostics, hotspot status, and gateway IP suggestions."""
    diag = get_network_diagnostics()
    return jsonify({
        "success": True,
        "diagnostics": diag
    })


@app.route("/api/camera/ip-webcam/control", methods=["POST"])
def control_ip_webcam_endpoint():
    """Controls mobile phone camera features (Torch LED flashlight, Front/Rear camera flip, Autofocus)."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if not action:
        return jsonify({"success": False, "error": "Validation error: action parameter is required."}), 400

    if action in ("torch_toggle", "toggle_torch"):
        success, msg = camera_manager.toggle_torch()
    elif action in ("camera_flip", "flip_camera"):
        success, msg = camera_manager.flip_camera()
    elif action in ("focus", "autofocus"):
        success, msg = camera_manager.trigger_focus()
    elif action in ("torch_on", "torch_off", "camera_front", "camera_back"):
        success, msg = control_ip_webcam(camera_manager.ip_camera_url, action)
        if success and action == "torch_on":
            camera_manager.torch_active = True
        elif success and action == "torch_off":
            camera_manager.torch_active = False
        elif success and action == "camera_front":
            camera_manager.camera_facing = "front"
        elif success and action == "camera_back":
            camera_manager.camera_facing = "back"
    else:
        return jsonify({"success": False, "error": f"Validation error: Unknown action '{action}'."}), 400

    return jsonify({
        "success": success,
        "message": msg,
        "torch_active": camera_manager.torch_active,
        "camera_facing": camera_manager.camera_facing
    })


# ---------------------------------------------------------
# Clean Reference Image APIs
# ---------------------------------------------------------
@app.route("/api/reference/capture", methods=["POST"])
def capture_reference():
    """Captures the current live frame and saves it as clean reference."""
    success, msg = camera_manager.capture_clean_reference()
    if success:
        Database.log_system_event("INFO", "REFERENCE", "Captured new clean solar panel reference image.")
        return jsonify({
            "success": True,
            "message": msg,
            "reference_base64": camera_manager.get_reference_base64()
        })
    return jsonify({"success": False, "error": msg}), 400


@app.route("/api/reference/view", methods=["GET"])
def view_reference():
    """Returns the clean reference image file or thumbnail base64."""
    if request.args.get("raw") == "1":
        if Config.REFERENCE_IMAGE_PATH.exists():
            return send_file(str(Config.REFERENCE_IMAGE_PATH), mimetype="image/jpeg")
        return "Reference image not found", 404

    b64 = camera_manager.get_reference_base64()
    return jsonify({
        "success": bool(b64),
        "reference_base64": b64,
        "path": str(Config.REFERENCE_IMAGE_PATH)
    })


@app.route("/api/reference/upload", methods=["POST"])
def upload_reference():
    """Allows uploading a custom image to serve as the clean reference."""
    if "file" in request.files:
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "Validation error: Empty filename provided."}), 400
        try:
            in_memory = file.read()
            if not in_memory:
                return jsonify({"success": False, "error": "Validation error: Uploaded file is empty."}), 400
            nparr = np.frombuffer(in_memory, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                camera_manager.set_reference_image(img)
                Database.log_system_event("INFO", "REFERENCE", f"Uploaded replacement reference image: {file.filename}")
                return jsonify({
                    "success": True,
                    "message": "Reference image uploaded successfully",
                    "reference_base64": camera_manager.get_reference_base64()
                })
            return jsonify({"success": False, "error": "Validation error: Invalid image file format."}), 400
        except Exception as e:
            return jsonify({"success": False, "error": f"Validation error: {str(e)}"}), 400

    # Handle JSON base64 upload
    data = request.get_json(silent=True) or {}
    b64_data = data.get("image_base64")
    if b64_data:
        img = decode_base64_to_image(b64_data)
        if img is not None:
            camera_manager.set_reference_image(img)
            Database.log_system_event("INFO", "REFERENCE", "Set new reference image from base64 upload.")
            return jsonify({"success": True, "message": "Reference image set successfully."})
        return jsonify({"success": False, "error": "Validation error: Invalid base64 image data."}), 400

    return jsonify({"success": False, "error": "Validation error: No file or image_base64 provided."}), 400


# ---------------------------------------------------------
# Model Training & Calibration APIs
# ---------------------------------------------------------
@app.route("/api/model/status", methods=["GET"])
def get_model_status():
    """Returns the current trained model state, accuracy, and dataset sample counts."""
    return jsonify({"success": True, "model": model_trainer.get_model_status()})


@app.route("/api/model/train", methods=["POST"])
def train_model():
    """Executes model training & calibration on the Chittoria solar panel dataset."""
    result = model_trainer.train_and_calibrate()
    return jsonify(result)


# ---------------------------------------------------------
# Detection & Monitoring APIs
# ---------------------------------------------------------
@app.route("/api/detection/start", methods=["POST"])
def start_detection():
    """Starts continuous background dust detection monitoring."""
    success = monitoring_service.start_monitoring()
    return jsonify({
        "success": success,
        "message": "Continuous dust monitoring started" if success else "Failed to start",
        "monitoring": monitoring_service.get_service_status()
    })


@app.route("/api/detection/stop", methods=["POST"])
def stop_detection():
    """Stops continuous background dust detection monitoring."""
    monitoring_service.stop_monitoring()
    return jsonify({
        "success": True,
        "message": "Continuous dust monitoring stopped",
        "monitoring": monitoring_service.get_service_status()
    })


@app.route("/api/detection/scan", methods=["POST"])
def single_detection_scan():
    """Triggers an instantaneous one-shot scan."""
    result = monitoring_service.execute_single_scan()
    return jsonify({"success": True, "result": result})


@app.route("/api/detection/latest", methods=["GET"])
def get_latest_detection():
    """Retrieves the latest detection score, metrics, and condition."""
    res = monitoring_service.latest_result or Database.get_latest_detection()
    if res:
        return jsonify({"success": True, "detection": res})
    return jsonify({"success": False, "message": "No detection records yet."})


@app.route("/api/detection/history", methods=["GET"])
def get_detection_history():
    """Returns paginated history of scans for tables and export."""
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    history = Database.get_detection_history(limit=limit, offset=offset)
    return jsonify({
        "success": True,
        "count": len(history),
        "history": history
    })


@app.route("/api/detection/stats", methods=["GET"])
def get_detection_stats():
    """Returns analytics data (clean vs dusty distribution, recent trends)."""
    stats = Database.get_detection_stats()
    return jsonify({"success": True, "stats": stats})


# ---------------------------------------------------------
# ESP32 Communication APIs
# ---------------------------------------------------------
@app.route("/api/esp32/status", methods=["GET"])
def get_esp32_status():
    """Returns connection status, IP, latency, and LED states."""
    return jsonify({"success": True, "esp32": esp32_controller.get_status()})


@app.route("/api/esp32/connect", methods=["POST"])
def connect_esp32():
    """Sets ESP32 target IP and tests connectivity."""
    data = request.get_json(silent=True) or {}
    ip = data.get("ip")
    if not ip or not isinstance(ip, str) or not ip.strip():
        return jsonify({"success": False, "error": "Validation error: IP address is required."}), 400

    ip = ip.strip()
    if not is_valid_ip_or_host(ip):
        return jsonify({"success": False, "error": "Validation error: Invalid IP address format (e.g. 192.168.1.150)."}), 400

    esp32_controller.set_ip(ip)
    connected, msg, latency = esp32_controller.test_connection()
    return jsonify({
        "success": connected,
        "message": msg,
        "latency_ms": latency,
        "esp32": esp32_controller.get_status()
    })


@app.route("/api/esp32/test-led", methods=["POST"])
def test_esp32_led():
    """Manually commands Red or Green LED on ESP32."""
    data = request.get_json(silent=True) or {}
    led = str(data.get("led", "red")).lower().strip()
    state = bool(data.get("state", True))

    if led not in ("red", "green"):
        return jsonify({"success": False, "error": "Validation error: Invalid LED type. Use 'red' or 'green'."}), 400

    success, msg = esp32_controller.manual_test_led(led_type=led, state=state)
    return jsonify({
        "success": success,
        "message": msg,
        "esp32": esp32_controller.get_status()
    })


@app.route("/api/esp32/test-servo", methods=["POST"])
def test_esp32_servo():
    """Manually commands Servo Motor on ESP32 GPIO 18 (angle 0..180 or action='wipe')."""
    data = request.get_json(silent=True) or {}
    angle = data.get("angle")
    action = data.get("action")

    if angle is None and not action:
        return jsonify({"success": False, "error": "Validation error: angle or action parameter is required."}), 400

    success, msg = esp32_controller.manual_test_servo(angle=angle, action=action)
    return jsonify({
        "success": success,
        "message": msg,
        "esp32": esp32_controller.get_status()
    })


# ---------------------------------------------------------
# Settings & Calibration APIs
# ---------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Returns current threshold, ROI, and mode settings."""
    return jsonify({
        "success": True,
        "thresholds": {
            "clean": dust_detector.threshold_clean,
            "heavy": dust_detector.threshold_heavy
        },
        "roi": dust_detector.roi,
        "auto_mode": monitoring_service.auto_mode,
        "consecutive_required": monitoring_service.consecutive_required,
        "scan_interval": monitoring_service.scan_interval,
        "esp32_ip": esp32_controller.ip
    })


@app.route("/api/settings/threshold", methods=["POST"])
def update_thresholds():
    """Updates dust detection thresholds."""
    data = request.get_json(silent=True) or {}
    clean_val = data.get("clean")
    heavy_val = data.get("heavy")

    if clean_val is None or heavy_val is None:
        return jsonify({
            "success": False,
            "error": "Validation error: Both clean and heavy thresholds are required."
        }), 400

    try:
        clean_val = float(clean_val)
        heavy_val = float(heavy_val)
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "Validation error: Threshold values must be numeric."
        }), 400

    if not (0.0 <= clean_val < heavy_val <= 100.0):
        return jsonify({
            "success": False,
            "error": "Validation error: Thresholds must satisfy 0.0 <= clean < heavy <= 100.0."
        }), 400

    success = dust_detector.set_thresholds(clean=clean_val, heavy=heavy_val)
    if success:
        Database.set_setting("threshold_clean", clean_val)
        Database.set_setting("threshold_heavy", heavy_val)
        Database.log_system_event("INFO", "CONFIG", f"Updated thresholds: Clean={clean_val}%, Heavy={heavy_val}%")
        return jsonify({
            "success": True,
            "message": "Thresholds updated successfully",
            "thresholds": {"clean": clean_val, "heavy": heavy_val}
        })

    return jsonify({
        "success": False,
        "error": "Validation error: Failed to update thresholds."
    }), 400


@app.route("/api/settings/roi", methods=["POST"])
def update_roi():
    """Updates Region of Interest coordinates (normalized 0.0 to 1.0)."""
    data = request.get_json(silent=True) or {}
    try:
        x_min = float(data.get("x_min", 0.05))
        y_min = float(data.get("y_min", 0.05))
        x_max = float(data.get("x_max", 0.95))
        y_max = float(data.get("y_max", 0.95))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Validation error: ROI coordinates must be numeric."}), 400

    if not (0.0 <= x_min < x_max <= 1.0 and 0.0 <= y_min < y_max <= 1.0):
        return jsonify({
            "success": False,
            "error": "Validation error: ROI coordinates must satisfy 0.0 <= min < max <= 1.0."
        }), 400

    dust_detector.set_roi(x_min, y_min, x_max, y_max)
    Database.set_setting("roi_x_min", x_min)
    Database.set_setting("roi_y_min", y_min)
    Database.set_setting("roi_x_max", x_max)
    Database.set_setting("roi_y_max", y_max)
    return jsonify({"success": True, "roi": dust_detector.roi})


@app.route("/api/settings/auto-mode", methods=["POST"])
def toggle_auto_mode():
    """Toggles automatic ESP32 synchronization on state change."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    monitoring_service.set_auto_mode(enabled)
    return jsonify({"success": True, "auto_mode": monitoring_service.auto_mode})


# ---------------------------------------------------------
# Simulation APIs (Test mode without hardware)
# ---------------------------------------------------------
@app.route("/api/simulation/toggle", methods=["POST"])
def toggle_simulation():
    """Enables or disables synthetic test generator."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", not camera_manager.simulation_mode))
    camera_manager.simulation_mode = enabled
    return jsonify({
        "success": True,
        "simulation_mode": camera_manager.simulation_mode,
        "simulated_dust_level": camera_manager.simulated_dust_level
    })


@app.route("/api/simulation/dust-level", methods=["POST"])
def set_simulated_dust_level():
    """Sets the synthetic dust accumulation level (0 to 100%) for testing."""
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level is None:
        return jsonify({"success": False, "error": "Validation error: level parameter is required."}), 400
    try:
        level = float(level)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Validation error: level must be numeric."}), 400

    level = max(0.0, min(100.0, level))
    camera_manager.simulated_dust_level = level
    camera_manager.simulation_mode = True
    return jsonify({"success": True, "simulated_dust_level": level})


# ---------------------------------------------------------
# System Logs API
# ---------------------------------------------------------
@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Retrieves recent system events for the web terminal."""
    limit = int(request.args.get("limit", 100))
    logs = Database.get_system_logs(limit=limit)
    return jsonify({"success": True, "logs": logs})


# ---------------------------------------------------------
# Application Factory / Entrypoint
# ---------------------------------------------------------
def create_app():
    """Initializes default subsystems and returns the Flask app."""
    # Ensure camera starts in default state
    camera_manager.start()
    # Start automated monitoring by default
    monitoring_service.start_monitoring()
    return app


if __name__ == "__main__":
    logger.info(f"Starting SolarGuard AI on {Config.HOST}:{Config.PORT}")
    app_instance = create_app()
    app_instance.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
