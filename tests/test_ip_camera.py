"""
Unit and Integration Tests for Mobile Phone IP Webcam Support in SolarGuard AI
Tests URL normalization, device discovery, connect/test/control endpoints,
and robust error handling.
"""

import unittest
from unittest.mock import patch, MagicMock
from backend.app import app
from backend.camera_manager import (
    normalize_camera_source,
    probe_ip_webcam,
    control_ip_webcam,
    camera_manager
)


class TestIPWebcamIntegration(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def tearDown(self):
        camera_manager.stop()

    def test_normalize_integer_usb_indices(self):
        """Validates that integers and numeric strings normalize to USB camera indices."""
        self.assertEqual(normalize_camera_source(0), (0, "usb"))
        self.assertEqual(normalize_camera_source("0"), (0, "usb"))
        self.assertEqual(normalize_camera_source(1), (1, "usb"))
        self.assertEqual(normalize_camera_source("2"), (2, "usb"))

    def test_normalize_simulation_modes(self):
        """Validates that -1, 'sim', and 'virtual' normalize to simulation mode."""
        self.assertEqual(normalize_camera_source(-1), (-1, "simulation"))
        self.assertEqual(normalize_camera_source("-1"), (-1, "simulation"))
        self.assertEqual(normalize_camera_source("sim"), (-1, "simulation"))
        self.assertEqual(normalize_camera_source("simulation"), (-1, "simulation"))
        self.assertEqual(normalize_camera_source("virtual"), (-1, "simulation"))

    def test_normalize_ip_webcam_urls(self):
        """Validates that IP addresses, ports, and incomplete URLs format to valid clean IP Webcam base endpoints."""
        # Bare IP defaults to port 8080 (without /video)
        self.assertEqual(
            normalize_camera_source("192.168.1.100"),
            ("http://192.168.1.100:8080", "ip_webcam")
        )
        # IP with port keeps clean base endpoint
        self.assertEqual(
            normalize_camera_source("192.168.1.100:8080"),
            ("http://192.168.1.100:8080", "ip_webcam")
        )
        # http:// without path stays clean base URL
        self.assertEqual(
            normalize_camera_source("http://192.168.1.100:8080"),
            ("http://192.168.1.100:8080", "ip_webcam")
        )
        # If /video is given, it normalizes to clean base URL so /video is not forced
        self.assertEqual(
            normalize_camera_source("http://192.168.1.100:8080/video"),
            ("http://192.168.1.100:8080", "ip_webcam")
        )
        # Snapshot path preserved
        self.assertEqual(
            normalize_camera_source("http://192.168.1.100:8080/shot.jpg"),
            ("http://192.168.1.100:8080/shot.jpg", "ip_webcam")
        )
        # RTSP stream preserved
        self.assertEqual(
            normalize_camera_source("rtsp://192.168.1.100:8080/h264_pcm.sdp"),
            ("rtsp://192.168.1.100:8080/h264_pcm.sdp", "ip_webcam")
        )

    def test_discover_cameras_contains_ip_and_virtual(self):
        """Validates that discover_cameras enumerates Mobile IP Webcam and Virtual Generator."""
        devices = camera_manager.discover_cameras(max_probes=1)
        indices = [d["index"] for d in devices]
        self.assertIn("ip_webcam", indices)
        self.assertIn(-1, indices)

    @patch("backend.camera_manager.cv2.VideoCapture")
    def test_select_camera_with_url_succeeds(self, mock_vcap):
        """POST /api/camera/select with an IP Webcam URL string should succeed (200)."""
        mock_cap_instance = MagicMock()
        mock_cap_instance.isOpened.return_value = True
        mock_cap_instance.read.return_value = (True, MagicMock(shape=(480, 640, 3)))
        mock_vcap.return_value = mock_cap_instance

        payload = {"camera_source": "http://192.168.1.105:8080/video"}
        response = self.client.post("/api/camera/select", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("camera", data)
        self.assertEqual(data["camera"]["is_ip_camera"], True)

    def test_select_camera_with_index_succeeds(self):
        """POST /api/camera/select with integer index 0 or -1 succeeds."""
        payload = {"camera_source": -1}
        response = self.client.post("/api/camera/select", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])

    def test_select_camera_missing_source_returns_400(self):
        """POST /api/camera/select with empty body returns 400 validation error."""
        response = self.client.post("/api/camera/select", json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_connect_ip_webcam_missing_params_returns_400(self):
        """POST /api/camera/ip-webcam/connect without IP or URL returns 400."""
        response = self.client.post("/api/camera/ip-webcam/connect", json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_test_ip_webcam_endpoint_unreachable_phone(self):
        """POST /api/camera/ip-webcam/test on unreachable IP returns 200 with reachable=False."""
        payload = {"ip": "192.0.2.1", "port": 8080}  # TEST-NET-1 unroutable IP
        response = self.client.post("/api/camera/ip-webcam/test", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("url", data)

    def test_control_ip_webcam_missing_action_returns_400(self):
        """POST /api/camera/ip-webcam/control without action returns 400."""
        response = self.client.post("/api/camera/ip-webcam/control", json={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    def test_control_ip_webcam_unknown_action_returns_400(self):
        """POST /api/camera/ip-webcam/control with invalid action returns 400."""
        response = self.client.post("/api/camera/ip-webcam/control", json={"action": "explode"})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Validation error", data["error"])

    @patch("backend.camera_manager.requests.get")
    def test_probe_ip_webcam_mocked_success(self, mock_get):
        """Tests probe_ip_webcam parsing status.json successfully."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"battery": 88, "curtime": 1700000000}
        mock_get.return_value = mock_resp

        reachable, msg, details = probe_ip_webcam("http://192.168.1.100:8080/video", timeout=1.0)
        self.assertTrue(reachable)
        self.assertEqual(details["battery"], 88)
        self.assertIn("Connected", msg)

    @patch("backend.camera_manager.requests.get")
    def test_control_ip_webcam_mocked_torch_on(self, mock_get):
        """Tests control_ip_webcam calling /enabletorch."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        success, msg = control_ip_webcam("http://192.168.1.100:8080/video", "torch_on")
        self.assertTrue(success)
        mock_get.assert_called_with("http://192.168.1.100:8080/enabletorch", timeout=2.5, verify=False)


if __name__ == "__main__":
    unittest.main()
