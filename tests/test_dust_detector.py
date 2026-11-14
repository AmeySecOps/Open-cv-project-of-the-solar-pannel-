"""
Unit Tests for SolarGuard AI Dust Detection Engine
Verifies computer vision algorithms, illumination invariance,
SSIM calculation, and threshold classification.
"""

import unittest
import numpy as np
import cv2
from backend.dust_detector import DustDetector


class TestDustDetector(unittest.TestCase):

    def setUp(self):
        self.detector = DustDetector()
        self.detector.set_thresholds(clean=20.0, heavy=50.0)

        # Create a synthetic baseline clean solar panel test pattern
        self.clean_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Deep blue background
        self.clean_frame[:, :] = [70, 35, 15]
        # Draw high-contrast busbars and grid
        for x in (160, 320, 480):
            cv2.line(self.clean_frame, (x, 0), (x, 480), (220, 220, 220), 3)
        for y in range(30, 480, 30):
            cv2.line(self.clean_frame, (0, y), (640, y), (170, 170, 170), 1)

    def test_identical_images_yield_clean(self):
        """Comparing identical clean images must yield 0% soiling and CLEAN status."""
        result = self.detector.analyze(self.clean_frame, self.clean_frame)
        self.assertEqual(result["status"], "CLEAN")
        self.assertLess(result["soiling_index"], 5.0)
        self.assertGreaterEqual(result["confidence"], 60.0)
        self.assertAlmostEqual(result["metrics"]["ssim"], 1.0, places=2)

    def test_dusty_layer_yields_dusty_status(self):
        """Applying heavy blur, contrast reduction, and gray haze must trigger DUSTY status."""
        dusty_frame = self.clean_frame.copy()
        # Add diffuse dust haze (blend gray-tan color)
        haze = np.full_like(dusty_frame, 150)
        dusty_frame = cv2.addWeighted(dusty_frame, 0.4, haze, 0.6, 0)
        # Heavy blur representing scattering
        dusty_frame = cv2.GaussianBlur(dusty_frame, (21, 21), 0)

        result = self.detector.analyze(dusty_frame, self.clean_frame)
        self.assertIn(result["status"], ("MODERATELY DUSTY", "HEAVILY DUSTY"))
        self.assertGreater(result["soiling_index"], self.detector.threshold_clean)

    def test_illumination_resilience(self):
        """
        Global brightness reduction (passing cloud / shadow) should NOT cause
        a false positive dust alert because illumination normalization aligns luminance.
        """
        # Dim the entire clean frame by 35% without adding dust blur or color haze
        dimmed_frame = (self.clean_frame.astype(np.float32) * 0.65).astype(np.uint8)

        result = self.detector.analyze(dimmed_frame, self.clean_frame)
        # Should remain CLEAN
        self.assertEqual(result["status"], "CLEAN",
                         f"Dimmed image triggered false positive: {result}")
        self.assertLess(result["soiling_index"], self.detector.threshold_clean)

    def test_threshold_update_validation(self):
        """Tests threshold updater rejecting invalid values and accepting valid ranges."""
        self.assertTrue(self.detector.set_thresholds(15.0, 45.0))
        self.assertEqual(self.detector.threshold_clean, 15.0)
        self.assertEqual(self.detector.threshold_heavy, 45.0)

        # Invalid: clean >= heavy
        self.assertFalse(self.detector.set_thresholds(50.0, 30.0))
        # Invalid: out of bounds
        self.assertFalse(self.detector.set_thresholds(-5.0, 50.0))

    def test_roi_configuration(self):
        """Tests Region of Interest clipping and coordinate conversion."""
        self.detector.set_roi(0.1, 0.1, 0.9, 0.9)
        x1, y1, x2, y2 = self.detector.get_roi_pixel_coords(640, 480)
        self.assertEqual(x1, 64)
        self.assertEqual(y1, 48)
        self.assertEqual(x2, 576)
        self.assertEqual(y2, 432)


if __name__ == "__main__":
    unittest.main()
