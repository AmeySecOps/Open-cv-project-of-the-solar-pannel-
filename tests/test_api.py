"""
Flask API Integration Tests for SolarGuard AI
Tests REST endpoints, status payloads, threshold updates, database queries,
and request validation error handling.
"""

import unittest
from unittest.mock import patch
from backend.app import app


class TestAPIEndpoints(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def test_status_endpoint(self):
        """GET /api/status returns 200 with system telemetry."""
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("monitoring", data)
        self.assertIn("camera", data)
        self.assertIn("esp32", data)

    def test_camera_status_endpoint(self):
        """GET /api/camera/status returns camera state."""
        response = self.client.get("/api/camera/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("resolution", data["camera"])

    def test_threshold_update_endpoint(self):
        """POST /api/settings/threshold updates detection limits."""
        payload = {"clean": 18.5, "heavy": 42.0}
        response = self.client.post("/api/settings/threshold", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["thresholds"]["clean"], 18.5)
        self.assertEqual(data["thresholds"]["heavy"], 42.0)

    def test_invalid_threshold_returns_400(self):
        """POST /api/settings/threshold with invalid bounds returns 400 with validation error."""
        payload = {"clean": 60.0, "heavy": 20.0}
        response = self.client.post("/api/settings/threshold", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_missing_threshold_returns_400(self):
        """POST /api/settings/threshold with missing clean/heavy keys returns 400."""
        payload = {"clean": 20.0}
        response = self.client.post("/api/settings/threshold", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_invalid_ip_format_returns_400(self):
        """POST /api/esp32/connect with invalid IP address returns 400."""
        payload = {"ip": "not_an_ip_address!!!"}
        response = self.client.post("/api/esp32/connect", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_missing_ip_returns_400(self):
        """POST /api/esp32/connect with empty IP returns 400."""
        payload = {"ip": ""}
        response = self.client.post("/api/esp32/connect", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_invalid_led_type_returns_400(self):
        """POST /api/esp32/test-led with invalid LED color returns 400."""
        payload = {"led": "blue", "state": True}
        response = self.client.post("/api/esp32/test-led", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_invalid_roi_bounds_returns_400(self):
        """POST /api/settings/roi with min >= max returns 400."""
        payload = {"x_min": 0.8, "y_min": 0.1, "x_max": 0.2, "y_max": 0.9}
        response = self.client.post("/api/settings/roi", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_single_scan_endpoint(self):
        """POST /api/detection/scan triggers an analysis run."""
        response = self.client.post("/api/detection/scan")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("status", data["result"])

    def test_logs_endpoint(self):
        """GET /api/logs retrieves system event entries."""
        response = self.client.get("/api/logs?limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["logs"], list)

    def test_test_servo_missing_params_returns_400(self):
        """POST /api/esp32/test-servo without angle or action returns 400."""
        response = self.client.post("/api/esp32/test-servo", json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    @patch("backend.esp32_controller.esp32_controller.manual_test_servo")
    def test_test_servo_success(self, mock_servo):
        """POST /api/esp32/test-servo triggers manual_test_servo."""
        mock_servo.return_value = (True, "Manual servo test successful")
        response = self.client.post("/api/esp32/test-servo", json={"angle": 180})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        mock_servo.assert_called_with(angle=180, action=None)


if __name__ == "__main__":
    unittest.main()
