"""
Unit Tests for SolarGuard AI ESP32 Controller
Tests HTTP endpoint construction, connection status tracking,
redundant command suppression, and graceful error handling.
"""

import unittest
from unittest.mock import patch, MagicMock
from backend.esp32_controller import ESP32Controller


class TestESP32Controller(unittest.TestCase):

    def setUp(self):
        self.controller = ESP32Controller()
        self.controller.ip = "192.168.1.150"
        self.controller.port = 80
        self.controller.is_connected = False
        self.controller.last_commanded_state = None

    @patch("requests.Session.get")
    def test_health_check_success(self, mock_get):
        """Tests successful ping response marking controller as connected."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "uptime_ms": 12000}
        mock_get.return_value = mock_resp

        success, msg, latency = self.controller.test_connection()
        self.assertTrue(success)
        self.assertTrue(self.controller.is_connected)
        self.assertIsNotNone(latency)
        mock_get.assert_called_with("http://192.168.1.150:80/health", timeout=self.controller.timeout)

    @patch("requests.Session.get")
    def test_connection_failure_handling(self, mock_get):
        """Tests network timeout or connection refused properly marks controller disconnected."""
        mock_get.side_effect = Exception("Connection refused")

        success, msg, latency = self.controller.test_connection()
        self.assertFalse(success)
        self.assertFalse(self.controller.is_connected)
        self.assertIn("Connection refused", msg)

    @patch("requests.Session.post")
    def test_send_dust_alert_turns_red_on(self, mock_post):
        """Tests sending dust alert triggers /led/on and updates state."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, msg = self.controller.send_dust_alert(force=True)
        self.assertTrue(success)
        self.assertEqual(self.controller.last_commanded_state, "DUSTY")
        self.assertTrue(self.controller.current_led_states["red"])
        self.assertFalse(self.controller.current_led_states["green"])
        mock_post.assert_called_with("http://192.168.1.150:80/led/on", timeout=self.controller.timeout)

    @patch("requests.Session.post")
    def test_redundant_command_suppression(self, mock_post):
        """Sending dust alert twice when state is already DUSTY should skip redundant HTTP requests."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        # First call
        self.controller.send_dust_alert(force=False)
        self.assertEqual(mock_post.call_count, 1)

        # Second call with same state (should be suppressed)
        success, msg = self.controller.send_dust_alert(force=False)
        self.assertTrue(success)
        self.assertIn("already DUSTY", msg)
        self.assertEqual(mock_post.call_count, 1)  # Post count must still be 1!

    @patch("requests.Session.post")
    def test_send_clean_status_turns_green_on(self, mock_post):
        """Tests sending clean status triggers /led/off and updates state."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, msg = self.controller.send_clean_status(force=True)
        self.assertTrue(success)
        self.assertEqual(self.controller.last_commanded_state, "CLEAN")
        self.assertFalse(self.controller.current_led_states["red"])
        self.assertTrue(self.controller.current_led_states["green"])
        mock_post.assert_called_with("http://192.168.1.150:80/led/off", timeout=self.controller.timeout)

    @patch("requests.Session.post")
    def test_send_dust_alert_above_70_triggers_servo(self, mock_post):
        """Tests sending dust alert with dirt >= 70% includes dirt parameter and marks servo wiping."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, msg = self.controller.send_dust_alert(force=True, dirt_percentage=78.5)
        self.assertTrue(success)
        self.assertEqual(self.controller.last_dirt_percentage, 78.5)
        self.assertEqual(self.controller.current_servo_state["angle"], 180)
        self.assertEqual(self.controller.current_servo_state["wiper_state"], "HOLDING_180")
        mock_post.assert_called_with("http://192.168.1.150:80/led/on?dirt=78.5", timeout=self.controller.timeout)

    @patch("requests.Session.post")
    def test_send_clean_status_resets_servo_to_zero(self, mock_post):
        """Tests sending clean status with dirt < 70% resets servo to 0 degrees."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        # Trigger wiping first
        self.controller.current_servo_state["angle"] = 180
        self.controller.current_servo_state["wiper_state"] = "HOLDING_180"

        success, msg = self.controller.send_clean_status(force=True, dirt_percentage=15.0)
        self.assertTrue(success)
        self.assertEqual(self.controller.last_dirt_percentage, 15.0)
        self.assertEqual(self.controller.current_servo_state["angle"], 0)
        self.assertEqual(self.controller.current_servo_state["wiper_state"], "IDLE_0")
        mock_post.assert_called_with("http://192.168.1.150:80/led/off?dirt=15.0", timeout=self.controller.timeout)

    @patch("requests.Session.post")
    def test_manual_servo_command(self, mock_post):
        """Tests manual servo test command sends POST to /servo."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, msg = self.controller.manual_test_servo(angle=180)
        self.assertTrue(success)
        self.assertEqual(self.controller.current_servo_state["angle"], 180)
        mock_post.assert_called_with("http://192.168.1.150:80/servo", json={"angle": 180}, timeout=self.controller.timeout)


if __name__ == "__main__":
    unittest.main()
