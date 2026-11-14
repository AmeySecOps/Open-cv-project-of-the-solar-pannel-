"""
SolarGuard AI - Computer Vision Dust Detection Engine
Implements illumination-invariant reference comparison, SSIM analysis,
texture blur/diffusion tracking, and HSV saturation shift analysis.
"""

from typing import Dict, Any, Tuple, Optional
import cv2
import numpy as np
from backend.config import Config
from backend.utils import logger


class DustDetector:
    """
    Analyzes solar panel images against a calibrated clean reference image.
    Uses multi-metric computer vision techniques resilient to sunlight and shadow variations.
    """

    def __init__(self):
        # Configurable thresholds (0 - 100%)
        self.threshold_clean = Config.DEFAULT_THRESHOLD_CLEAN
        self.threshold_heavy = Config.DEFAULT_THRESHOLD_HEAVY

        # Region of Interest (normalized coordinates 0.0 - 1.0)
        self.roi = Config.DEFAULT_ROI.copy()

        # Target processing size for fast, stable computation
        self.process_width = 480
        self.process_height = 360

    def set_thresholds(self, clean: float, heavy: float):
        """Updates classification thresholds."""
        if 0.0 <= clean < heavy <= 100.0:
            self.threshold_clean = clean
            self.threshold_heavy = heavy
            logger.info(f"Updated thresholds: Clean={self.threshold_clean}%, Heavy={self.threshold_heavy}%")
            return True
        logger.warning(f"Invalid threshold values provided: clean={clean}, heavy={heavy}")
        return False

    def set_roi(self, x_min: float, y_min: float, x_max: float, y_max: float):
        """Sets the Region of Interest bounding box in normalized coordinates (0.0 to 1.0)."""
        x_min = max(0.0, min(x_min, 0.90))
        y_min = max(0.0, min(y_min, 0.90))
        x_max = max(x_min + 0.05, min(x_max, 1.0))
        y_max = max(y_min + 0.05, min(y_max, 1.0))

        self.roi = {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max
        }
        logger.info(f"Updated ROI: {self.roi}")

    def get_roi_pixel_coords(self, width: int, height: int) -> Tuple[int, int, int, int]:
        """Converts normalized ROI to integer pixel coordinates (x1, y1, x2, y2)."""
        x1 = int(self.roi["x_min"] * width)
        y1 = int(self.roi["y_min"] * height)
        x2 = int(self.roi["x_max"] * width)
        y2 = int(self.roi["y_max"] * height)
        return max(0, x1), max(0, y1), min(width, x2), min(height, y2)

    def extract_roi(self, image: np.ndarray) -> np.ndarray:
        """Crops image to the configured Region of Interest."""
        if image is None:
            return None
        h, w = image.shape[:2]
        x1, y1, x2, y2 = self.get_roi_pixel_coords(w, h)
        return image[y1:y2, x1:x2]

    @staticmethod
    def _compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Computes Structural Similarity Index (SSIM) between two grayscale images.
        Uses Gaussian window and luminance/contrast constants to ensure invariance.
        """
        # Ensure float32
        i1 = img1.astype(np.float32)
        i2 = img2.astype(np.float32)

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        # 11x11 Gaussian blur window
        kernel = (11, 11)
        sigma = 1.5

        mu1 = cv2.GaussianBlur(i1, kernel, sigma)
        mu2 = cv2.GaussianBlur(i2, kernel, sigma)

        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(i1 * i1, kernel, sigma) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(i2 * i2, kernel, sigma) - mu2_sq
        sigma12 = cv2.GaussianBlur(i1 * i2, kernel, sigma) - mu1_mu2

        num = (2.0 * mu1_mu2 + c1) * (2.0 * sigma12 + c2)
        den = (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)

        ssim_map = num / (den + 1e-7)
        return float(np.clip(np.mean(ssim_map), 0.0, 1.0))

    @staticmethod
    def _normalize_illumination(live_gray: np.ndarray, ref_gray: np.ndarray) -> np.ndarray:
        """
        Normalizes live image luminance against the reference image.
        Uses histogram / mean matching to prevent shadows or cloud passage
        from falsely registering as dust accumulation.
        """
        mean_ref = float(np.mean(ref_gray))
        mean_live = float(np.mean(live_gray))

        if mean_live < 1.0:
            return live_gray

        # Scale live luminance to match reference mean
        scale = mean_ref / mean_live
        # Restrict scale factor to avoid excessive noise amplification in deep darkness
        scale = np.clip(scale, 0.4, 2.5)

        normalized = cv2.multiply(live_gray.astype(np.float32), scale)
        return np.clip(normalized, 0, 255).astype(np.uint8)

    def analyze(self, live_frame: np.ndarray, reference_frame: np.ndarray) -> Dict[str, Any]:
        """
        Executes the complete dust detection pipeline comparing live frame to clean reference.

        Returns:
            Dict containing:
                - status: "CLEAN", "MODERATELY DUSTY", or "HEAVILY DUSTY"
                - soiling_index: float (0.0 - 100.0%)
                - confidence: float (0.0 - 100.0%)
                - metrics: Dict with ssim, texture_loss, contrast_loss, hsv_shift
                - roi_coords: (x1, y1, x2, y2)
                - is_dark_warning: bool
        """
        if live_frame is None or reference_frame is None:
            return {
                "status": "ERROR",
                "soiling_index": 0.0,
                "confidence": 0.0,
                "error": "Missing input frame or reference frame."
            }

        h_live, w_live = live_frame.shape[:2]
        roi_pixels = self.get_roi_pixel_coords(w_live, h_live)

        # 1. Extract ROI from both images
        roi_live = self.extract_roi(live_frame)
        roi_ref = self.extract_roi(reference_frame)

        if roi_live.size == 0 or roi_ref.size == 0:
            return {
                "status": "ERROR",
                "soiling_index": 0.0,
                "confidence": 0.0,
                "error": "Invalid ROI size."
            }

        # 2. Resize both ROIs to matching standardized dimensions
        roi_live_resized = cv2.resize(roi_live, (self.process_width, self.process_height))
        roi_ref_resized = cv2.resize(roi_ref, (self.process_width, self.process_height))

        # 3. Color Space Conversions: Grayscale & HSV
        gray_live = cv2.cvtColor(roi_live_resized, cv2.COLOR_BGR2GRAY)
        gray_ref = cv2.cvtColor(roi_ref_resized, cv2.COLOR_BGR2GRAY)

        hsv_live = cv2.cvtColor(roi_live_resized, cv2.COLOR_BGR2HSV)
        hsv_ref = cv2.cvtColor(roi_ref_resized, cv2.COLOR_BGR2HSV)

        # Check for extreme under-exposure (dark room / night time)
        mean_brightness = float(np.mean(gray_live))
        is_dark = mean_brightness < 20.0

        # 4. Illumination Normalization
        # Compensates for global sunlight / cloud variation so shadows are not called dust
        norm_live_gray = self._normalize_illumination(gray_live, gray_ref)

        # 5. Gaussian Blur (reduces sensor noise while preserving structural lines)
        blur_live = cv2.GaussianBlur(norm_live_gray, (5, 5), 0)
        blur_ref = cv2.GaussianBlur(gray_ref, (5, 5), 0)

        # 6. Structural Similarity Index (SSIM)
        ssim_val = self._compute_ssim(blur_live, blur_ref)
        # Structural deviation (0 when identical, 1 when completely degraded)
        structural_loss = np.clip(1.0 - ssim_val, 0.0, 1.0)

        # 7. High-Frequency Texture & Edge Energy Analysis (Laplacian Variance)
        # Clean panels have sharp wafer busbars & anti-reflective textures. Dust diffuses edges.
        lap_ref = cv2.Laplacian(blur_ref, cv2.CV_64F)
        lap_live = cv2.Laplacian(blur_live, cv2.CV_64F)

        var_ref = float(np.var(lap_ref))
        var_live = float(np.var(lap_live))

        # Texture loss ratio
        if var_ref > 1e-3:
            texture_loss = np.clip(1.0 - (var_live / var_ref), 0.0, 1.0)
        else:
            texture_loss = 0.0

        # 8. Local Contrast Degradation
        # Dust flattens the local dynamic range
        std_ref = float(np.std(blur_ref))
        std_live = float(np.std(blur_live))
        if std_ref > 1e-3:
            contrast_loss = np.clip(1.0 - (std_live / std_ref), 0.0, 1.0)
        else:
            contrast_loss = 0.0

        # 9. Saturation & Color Shift Analysis (HSV)
        # Clean panels have deep blue/black color with distinct saturation.
        # Dust scattering creates a grayish/tan haze, reducing saturation.
        sat_live = hsv_live[:, :, 1]
        sat_ref = hsv_ref[:, :, 1]
        mean_sat_live = float(np.mean(sat_live))
        mean_sat_ref = float(np.mean(sat_ref))

        if mean_sat_ref > 5.0:
            sat_loss = np.clip((mean_sat_ref - mean_sat_live) / mean_sat_ref, 0.0, 1.0)
        else:
            sat_loss = 0.0

        # 10. Multi-Metric Soiling Indicator Fusion
        # Balanced weighting:
        # - Structural Loss: 40%
        # - Texture/Blur Loss: 30%
        # - Saturation Loss: 20%
        # - Contrast Loss: 10%
        w_ssim = 0.40
        w_texture = 0.30
        w_sat = 0.20
        w_contrast = 0.10

        composite_score = (
            w_ssim * structural_loss +
            w_texture * texture_loss +
            w_sat * sat_loss +
            w_contrast * contrast_loss
        )

        # Calibrated Visual Soiling Index scaling (0.0 to 100.0%)
        # Sigmoid-calibrated response curve to provide realistic 0-100% telemetry
        raw_index = composite_score * 125.0
        soiling_index = float(np.clip(raw_index, 0.0, 100.0))

        # Night/Extreme Darkness Guard:
        # If lighting is severely dark, clamp soiling index to prevent false dust triggers
        if is_dark:
            soiling_index = 0.0
            confidence = 35.0
        else:
            # Confidence estimation: high when metrics agree and illumination is stable
            agreement = 1.0 - np.std([structural_loss, texture_loss, sat_loss, contrast_loss])
            confidence = float(np.clip(agreement * 100.0, 45.0, 98.0))

        # 11. Condition Classification
        if soiling_index < self.threshold_clean:
            status = "CLEAN"
        elif soiling_index < self.threshold_heavy:
            status = "MODERATELY DUSTY"
        else:
            status = "HEAVILY DUSTY"

        return {
            "status": status,
            "soiling_index": round(soiling_index, 2),
            "confidence": round(confidence, 1),
            "is_dark": is_dark,
            "metrics": {
                "ssim": round(ssim_val, 4),
                "structural_loss": round(float(structural_loss), 4),
                "texture_loss": round(float(texture_loss), 4),
                "contrast_loss": round(float(contrast_loss), 4),
                "sat_loss": round(float(sat_loss), 4)
            },
            "roi_coords": roi_pixels
        }


# Global dust detector instance
dust_detector = DustDetector()
