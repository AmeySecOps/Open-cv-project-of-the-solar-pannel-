"""
SolarGuard AI - Model Trainer & Dataset Calibration Tests
Verifies dataset organization, cell segmentation, debris blob detection,
and 100% classification accuracy on Chittoria Solar Panel images.
"""

import os
import glob
import unittest
import cv2
import numpy as np

from backend.config import Config
from backend.model_trainer import model_trainer, ModelTrainer
from backend.dust_detector import dust_detector
from backend.app import app


class TestModelTrainer(unittest.TestCase):
    """Test suite for ModelTrainer and trained Chittoria Solar dataset."""

    @classmethod
    def setUpClass(cls):
        cls.clean_paths = sorted(glob.glob(str(Config.BASE_DIR / "data" / "dataset" / "clean" / "*.jpg")))
        cls.dirty_paths = sorted(glob.glob(str(Config.BASE_DIR / "data" / "dataset" / "dirty" / "*.jpg")))
        ref_path = Config.BASE_DIR / "reference_images" / "clean_reference.jpg"
        cls.reference_frame = cv2.imread(str(ref_path))
        cls.client = app.test_client()

    def test_dataset_files_exist(self):
        """Verifies that all 12 dataset images are organized properly in clean/dirty folders."""
        self.assertEqual(len(self.clean_paths), 7, "Expected exactly 7 clean solar panel dataset images.")
        self.assertEqual(len(self.dirty_paths), 5, "Expected exactly 5 dirty solar panel dataset images.")
        self.assertIsNotNone(self.reference_frame, "Clean reference image must exist.")

    def test_cell_segmentation(self):
        """Tests that extract_panel_cell_region segments PV cells and excludes margins."""
        for p in self.clean_paths[:2] + self.dirty_paths[:2]:
            img = cv2.imread(p)
            self.assertIsNotNone(img, f"Failed to read {p}")
            cells, roi = model_trainer.extract_panel_cell_region(img)
            self.assertIsNotNone(cells)
            self.assertGreater(cells.size, 0)
            x1, y1, x2, y2 = roi
            self.assertGreater(x2, x1)
            self.assertGreater(y2, y1)

    def test_train_and_calibrate_100_percent_accuracy(self):
        """Verifies that model training achieves 100% accuracy and F1-score on the dataset."""
        result = model_trainer.train_and_calibrate()
        self.assertTrue(result["success"])
        self.assertEqual(result["accuracy"], 100.0, "Model accuracy must be 100.0% on calibrated dataset.")
        self.assertEqual(result["precision"], 100.0)
        self.assertEqual(result["recall"], 100.0)
        self.assertEqual(result["f1_score"], 100.0)
        self.assertEqual(result["clean_count"], 7)
        self.assertEqual(result["dirty_count"], 5)
        self.assertEqual(result["total_samples"], 12)

    def test_dust_detector_analyze_on_all_dataset_images(self):
        """Verifies that DustDetector.analyze yields 100% correct status and debris boxes on all samples."""
        # 1. Test all 7 clean samples
        for p in self.clean_paths:
            img = cv2.imread(p)
            res = dust_detector.analyze(img, self.reference_frame)
            self.assertEqual(res["status"], "CLEAN", f"Image {os.path.basename(p)} should be CLEAN, got {res['status']}")
            self.assertLess(res["soiling_index"], 22.0, f"Clean image {p} soiling index too high: {res['soiling_index']}%")
            self.assertLessEqual(res["debris_count"], 2)
            self.assertIn("debris_boxes", res)

        # 2. Test all 5 dirty samples
        for p in self.dirty_paths:
            img = cv2.imread(p)
            res = dust_detector.analyze(img, self.reference_frame)
            self.assertEqual(res["status"], "HEAVILY DUSTY", f"Image {os.path.basename(p)} should be HEAVILY DUSTY, got {res['status']}")
            self.assertGreaterEqual(res["soiling_index"], 48.0, f"Dirty image {p} soiling index too low: {res['soiling_index']}%")
            self.assertGreaterEqual(res["debris_count"], 8)
            self.assertGreater(len(res["debris_boxes"]), 0)
            # Ensure debris boxes have valid coordinates
            for b in res["debris_boxes"]:
                self.assertIn("x", b)
                self.assertIn("y", b)
                self.assertIn("w", b)
                self.assertIn("h", b)
                self.assertGreater(b["w"], 0)
                self.assertGreater(b["h"], 0)

    def test_api_model_status_endpoint(self):
        """Tests GET /api/model/status endpoint."""
        resp = self.client.get("/api/model/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        model = data["model"]
        self.assertEqual(model["accuracy"], 100.0)
        self.assertEqual(model["clean_samples"], 7)
        self.assertEqual(model["dirty_samples"], 5)

    def test_api_model_train_endpoint(self):
        """Tests POST /api/model/train endpoint."""
        resp = self.client.post("/api/model/train")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["accuracy"], 100.0)
        self.assertEqual(data["f1_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
