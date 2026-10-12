import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.api.server import GatewayApiServer


class GatewayApiTests(unittest.TestCase):
    def setUp(self):
        self.server = GatewayApiServer(
            port=0,
            device_status_provider=lambda: [
                {"device_id": "line-1", "runtime_status": "collecting"}
            ],
            cache_status_provider=lambda: {
                "line-1": {"total": 3, "pending": 2, "dead_letter": 1}
            },
            token="test-token",
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def _get(self, path, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = Request(self.server.url + path, headers=headers)
        return urlopen(request, timeout=2)

    def test_health_is_public_and_status_requires_token(self):
        with self._get("/healthz") as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["cache_pending"], 2)

        with self.assertRaises(HTTPError) as error:
            self._get("/api/v1/status")
        self.assertEqual(error.exception.code, 401)

        with self._get("/api/v1/status", "test-token") as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["device_status"][0]["device_id"], "line-1")

    def test_metrics_expose_cache_and_device_status(self):
        with self._get("/metrics", "test-token") as response:
            metrics = response.read().decode("utf-8")
        self.assertIn("duqu_gateway_cache_pending 2", metrics)
        self.assertIn('duqu_gateway_devices_by_status{status="collecting"} 1', metrics)

    def test_dashboard_assets_are_served_with_security_headers(self):
        with self._get("/") as response:
            html = response.read().decode("utf-8")
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("/web/app.js", html)

        with self._get("/web/app.js") as response:
            script = response.read().decode("utf-8")
            self.assertIn("/api/v1/status", script)

        with self._get("/web/styles.css") as response:
            self.assertIn("text/css", response.headers["Content-Type"])

    def test_remote_binding_requires_token(self):
        with self.assertRaises(ValueError):
            GatewayApiServer(host="0.0.0.0", port=0).start()


if __name__ == "__main__":
    unittest.main()
