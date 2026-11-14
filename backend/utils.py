"""
SolarGuard AI - Utility Functions
Provides structured logging, image formatting, base64 encoding, and HUD drawing.
"""

import base64
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import cv2
import numpy as np
from backend.config import Config


def setup_logger(name: str = "SolarGuard") -> logging.Logger:
    """Configures and returns a thread-safe rotating file and stream logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if Config.DEBUG else logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Rotating File Handler (Max 5MB per file, up to 3 backups)
    try:
        fh = RotatingFileHandler(
            Config.LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: Failed to initialize file handler for logs: {e}")

    return logger


logger = setup_logger("SolarGuardAI")


def encode_image_to_base64(image_np: np.ndarray, format_ext: str = ".jpg") -> str:
    """Encodes an OpenCV BGR numpy array to a base64 data URI string."""
    if image_np is None or image_np.size == 0:
        return ""
    success, buffer = cv2.imencode(format_ext, image_np)
    if not success:
        return ""
    encoded = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def decode_base64_to_image(base64_str: str) -> np.ndarray:
    """Decodes a base64 data URI string or raw base64 string to an OpenCV BGR numpy array."""
    try:
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]
        img_bytes = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        logger.error(f"Error decoding base64 image: {e}")
        return None


def draw_hud_overlay(
    frame: np.ndarray,
    status: str,
    soiling_index: float,
    confidence: float,
    roi_coords: tuple = None,
    fps: float = 0.0,
    esp32_connected: bool = False,
    debris_boxes: list = None
) -> np.ndarray:
    """
    Renders a professional industrial telemetry HUD overlay onto the camera frame.
    Includes bounding box for ROI, detected debris outlines, status badges, soiling indicator bar, and telemetry.
    """
    if frame is None or frame.size == 0:
        return frame

    h, w = frame.shape[:2]
    annotated = frame.copy()

    # Determine status color scheme (BGR)
    if status == "CLEAN":
        status_color = (60, 210, 80)     # Neon Green / Emerald
        status_bg = (20, 80, 30)
    elif status == "MODERATELY DUSTY":
        status_color = (30, 180, 250)    # Amber / Orange
        status_bg = (10, 60, 90)
    elif status == "HEAVILY DUSTY":
        status_color = (50, 50, 240)     # Bright Red / Crimson
        status_bg = (15, 15, 80)
    else:
        status_color = (200, 200, 200)   # Neutral Gray
        status_bg = (40, 40, 40)

    # 1. Draw ROI Box
    if roi_coords:
        x1, y1, x2, y2 = roi_coords
        # Semi-transparent darkened background outside ROI for clear solar panel focus
        overlay = annotated.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 255, 255), -1)
        cv2.addWeighted(overlay, 0.15, annotated, 0.85, 0, annotated)

        # Draw ROI target corner brackets and dashed/solid perimeter
        cv2.rectangle(annotated, (x1, y1), (x2, y2), status_color, 2)

        # Corner brackets for high-tech HUD look
        bracket_len = min(25, (x2 - x1) // 4, (y2 - y1) // 4)
        thickness = 3
        # Top-Left
        cv2.line(annotated, (x1, y1), (x1 + bracket_len, y1), (255, 255, 255), thickness)
        cv2.line(annotated, (x1, y1), (x1, y1 + bracket_len), (255, 255, 255), thickness)
        # Top-Right
        cv2.line(annotated, (x2, y1), (x2 - bracket_len, y1), (255, 255, 255), thickness)
        cv2.line(annotated, (x2, y1), (x2, y1 + bracket_len), (255, 255, 255), thickness)
        # Bottom-Left
        cv2.line(annotated, (x1, y2), (x1 + bracket_len, y2), (255, 255, 255), thickness)
        cv2.line(annotated, (x1, y2), (x1, y2 - bracket_len), (255, 255, 255), thickness)
        # Bottom-Right
        cv2.line(annotated, (x2, y2), (x2 - bracket_len, y2), (255, 255, 255), thickness)
        cv2.line(annotated, (x2, y2), (x2, y2 - bracket_len), (255, 255, 255), thickness)

        cv2.putText(annotated, "ROI: SOLAR PANEL TARGET", (x1 + 6, max(y1 - 8, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)

    # 1.5 Draw Detected Dirt & Debris Objects
    if debris_boxes:
        for idx, box in enumerate(debris_boxes):
            bx = int(box.get("x", 0))
            by = int(box.get("y", 0))
            bw = int(box.get("w", 0))
            bh = int(box.get("h", 0))
            box_col = (0, 215, 255)  # Bright amber/gold
            cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), box_col, 2)
            cv2.putText(annotated, f"DIRT #{idx+1}", (bx, max(by - 5, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, box_col, 1, cv2.LINE_AA)

    # 2. Top Header Bar (HUD overlay)
    bar_h = 44
    hud_bar = annotated[0:bar_h, 0:w].copy()
    cv2.rectangle(hud_bar, (0, 0), (w, bar_h), (12, 20, 36), -1)
    cv2.addWeighted(hud_bar, 0.75, annotated[0:bar_h, 0:w], 0.25, 0, annotated[0:bar_h, 0:w])
    cv2.line(annotated, (0, bar_h), (w, bar_h), (50, 70, 95), 1)

    # Title & FPS
    cv2.putText(annotated, "SOLARGUARD AI", (14, 28),
                cv2.FONT_HERSHEY_DUPLEX, 0.65, (6, 214, 160), 1, cv2.LINE_AA)

    time_str = datetime.now().strftime("%H:%M:%S")
    telemetry_str = f"FPS: {fps:.1f}  |  {time_str}"
    cv2.putText(annotated, telemetry_str, (w - 180, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 180, 200), 1, cv2.LINE_AA)

    # ESP32 Status Dot in Top Bar
    esp_dot_color = (60, 220, 80) if esp32_connected else (60, 60, 200)
    esp_text = "ESP32: ON" if esp32_connected else "ESP32: OFF"
    cv2.circle(annotated, (w - 280, 24), 5, esp_dot_color, -1)
    cv2.putText(annotated, esp_text, (w - 270, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (190, 205, 220), 1, cv2.LINE_AA)

    # 3. Bottom Status Overlay Card
    card_h = 60
    card_y = h - card_h - 10
    card_w = min(360, w - 20)
    card_x = 10

    card_region = annotated[card_y:card_y + card_h, card_x:card_x + card_w].copy()
    cv2.rectangle(card_region, (0, 0), (card_w, card_h), (10, 18, 32), -1)
    cv2.addWeighted(card_region, 0.85, annotated[card_y:card_y + card_h, card_x:card_x + card_w], 0.15, 0,
                    annotated[card_y:card_y + card_h, card_x:card_x + card_w])
    cv2.rectangle(annotated, (card_x, card_y), (card_x + card_w, card_y + card_h), status_color, 1)

    # Status Pill
    cv2.putText(annotated, f"STATUS: {status}", (card_x + 12, card_y + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, status_color, 2, cv2.LINE_AA)

    # Soiling Indicator & Confidence
    info_text = f"Soiling: {soiling_index:.1f}% | Conf: {confidence:.0f}%"
    cv2.putText(annotated, info_text, (card_x + 12, card_y + 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 230, 240), 1, cv2.LINE_AA)

    # Mini Progress Bar for Soiling
    bar_x = card_x + card_w - 110
    bar_y = card_y + 36
    bar_width = 95
    bar_height = 8
    cv2.rectangle(annotated, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (40, 50, 70), -1)
    filled_width = int(bar_width * max(0.0, min(1.0, soiling_index / 100.0)))
    if filled_width > 0:
        cv2.rectangle(annotated, (bar_x, bar_y), (bar_x + filled_width, bar_y + bar_height), status_color, -1)
    cv2.rectangle(annotated, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (120, 140, 160), 1)

    return annotated
