"""Tests for api.py — FastAPI REST endpoints."""

import io
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from trcc.api import _device_svc, app, configure_auth
from trcc.core.models import DeviceInfo


class TestHealthEndpoint(unittest.TestCase):
    """GET /health always returns 200."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)


class TestAuthMiddleware(unittest.TestCase):
    """Token auth middleware."""

    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        configure_auth(None)

    def test_no_token_required(self):
        configure_auth(None)
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)

    def test_token_required_rejects_missing(self):
        configure_auth("secret123")
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 401)

    def test_token_required_rejects_wrong(self):
        configure_auth("secret123")
        resp = self.client.get("/devices", headers={"X-API-Token": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_token_required_accepts_correct(self):
        configure_auth("secret123")
        resp = self.client.get("/devices", headers={"X-API-Token": "secret123"})
        self.assertEqual(resp.status_code, 200)

    def test_health_bypasses_auth(self):
        configure_auth("secret123")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)


class TestDeviceEndpoints(unittest.TestCase):
    """Device list/detect/select/get endpoints."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        # Clear device state
        _device_svc._devices = []
        _device_svc._selected = None

    def test_list_devices_empty(self):
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_devices_with_device(self):
        _device_svc._devices = [
            DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                       protocol="scsi", resolution=(320, 320)),
        ]
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "LCD1")
        self.assertEqual(data[0]["vid"], 0x0402)

    @patch.object(_device_svc, 'detect')
    def test_detect_devices(self, mock_detect):
        mock_detect.return_value = []
        resp = self.client.post("/devices/detect")
        self.assertEqual(resp.status_code, 200)
        mock_detect.assert_called_once()

    def test_select_device(self):
        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [dev]
        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["selected"], "LCD1")
        self.assertEqual(_device_svc.selected, dev)

    def test_select_device_not_found(self):
        resp = self.client.post("/devices/99/select")
        self.assertEqual(resp.status_code, 404)

    def test_get_device(self):
        _device_svc._devices = [
            DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                       protocol="scsi", resolution=(480, 480)),
        ]
        resp = self.client.get("/devices/0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "LCD1")
        self.assertEqual(data["resolution"], [480, 480])

    def test_get_device_not_found(self):
        resp = self.client.get("/devices/0")
        self.assertEqual(resp.status_code, 404)


class TestSendImage(unittest.TestCase):
    """POST /devices/{id}/send — image upload and processing."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        self.dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                              protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [self.dev]
        _device_svc._selected = None

    @patch.object(_device_svc, 'send_rgb565', return_value=True)
    def test_send_image_success(self, mock_send):
        img = Image.new('RGB', (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["sent"])
        mock_send.assert_called_once()

    @patch.object(_device_svc, 'send_rgb565', return_value=False)
    def test_send_image_failure(self, mock_send):
        img = Image.new('RGB', (100, 100), (0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 500)

    def test_send_image_invalid_format(self):
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_send_image_too_large(self):
        # 11 MB of zeros
        big = io.BytesIO(b'\x00' * (11 * 1024 * 1024))
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("big.bin", big, "image/png")},
        )
        self.assertEqual(resp.status_code, 413)

    def test_send_image_device_not_found(self):
        _device_svc._devices = []
        img = Image.new('RGB', (10, 10))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/99/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 404)

    @patch.object(_device_svc, 'send_rgb565', return_value=True)
    def test_send_with_rotation(self, mock_send):
        img = Image.new('RGB', (100, 100), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send?rotation=90",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 200)


class TestThemesEndpoint(unittest.TestCase):
    """GET /themes — list local themes."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    @patch('trcc.api.ThemeService.discover_local', return_value=[])
    @patch('trcc.paths.get_theme_dir', return_value='/tmp/themes')
    def test_list_themes_empty(self, mock_dir, mock_discover):
        resp = self.client.get("/themes?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    @patch('trcc.api.ThemeService.discover_local')
    @patch('trcc.paths.get_theme_dir', return_value='/tmp/themes')
    def test_list_themes_with_results(self, mock_dir, mock_discover):
        mock_theme = MagicMock()
        mock_theme.name = "Theme001"
        mock_theme.category = "a"
        mock_theme.is_animated = False
        mock_theme.config_path = None
        mock_discover.return_value = [mock_theme]

        resp = self.client.get("/themes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Theme001")

    def test_invalid_resolution_format(self):
        resp = self.client.get("/themes?resolution=invalid")
        self.assertEqual(resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
