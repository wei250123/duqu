import hmac
import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse


class GatewayApiServer:
    """Threaded read-only HTTP API for health, status and Prometheus metrics.

    The server is intentionally implemented with the standard library so the
    gateway can run in an offline factory environment without another runtime
    dependency.  It binds to localhost by default; remote binding requires a
    bearer token in ``IIOT_GATEWAY_API_TOKEN``.
    """

    VERSION = "1"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        device_status_provider: Optional[Callable[[], list]] = None,
        cache_status_provider: Optional[Callable[[], Dict[str, dict]]] = None,
        token: Optional[str] = None,
    ):
        self.host = host
        self.port = int(port)
        self._device_status_provider = device_status_provider or (lambda: [])
        self._cache_status_provider = cache_status_provider or (lambda: {})
        self._token = token if token is not None else os.getenv("IIOT_GATEWAY_API_TOKEN", "")
        self._started_at = time.time()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> bool:
        with self._lock:
            if self._httpd is not None:
                return True
            if self.host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::") and not self._token:
                raise ValueError("API remote binding requires IIOT_GATEWAY_API_TOKEN")
            if self.host in ("0.0.0.0", "::") and not self._token:
                raise ValueError("API wildcard binding requires IIOT_GATEWAY_API_TOKEN")
            handler = self._make_handler()
            self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
            self.port = self._httpd.server_port
            self._httpd.daemon_threads = True
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="GatewayApiServer",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0):
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _make_handler(self):
        gateway = self

        class RequestHandler(BaseHTTPRequestHandler):
            server_version = "DuquGateway/" + GatewayApiServer.VERSION

            def log_message(self, format: str, *args: Any):
                # Keep request logging out of stdout; the gateway logger owns
                # operational logs and can apply its configured retention.
                return

            def do_GET(self):  # noqa: N802 - stdlib handler API
                path = urlparse(self.path).path.rstrip("/") or "/"
                if path in ("/healthz", "/readyz"):
                    payload = gateway.health_payload(ready=path == "/readyz")
                    self._write_json(payload, HTTPStatus.OK)
                    return
                if path in ("/api/v1/status", "/api/v1/devices", "/metrics"):
                    if not gateway.authorized(self.headers.get("Authorization", "")):
                        self._write_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    if path == "/metrics":
                        self._write_metrics(gateway.metrics_text())
                    else:
                        self._write_json(gateway.status_payload(), HTTPStatus.OK)
                    return
                self._write_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def _write_json(self, payload: dict, status: HTTPStatus):
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _write_metrics(self, body_text: str):
                body = body_text.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return RequestHandler

    def authorized(self, authorization: str) -> bool:
        if not self._token:
            # Local-only operation is safe by default.  Remote binding is
            # rejected in start(), so an unset token cannot expose the API.
            return self.host in ("127.0.0.1", "localhost", "::1")
        scheme, _, supplied = authorization.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(supplied, self._token)

    def _snapshot(self) -> tuple[list, Dict[str, dict]]:
        try:
            devices = list(self._device_status_provider() or [])
        except Exception:
            devices = []
        try:
            cache = dict(self._cache_status_provider() or {})
        except Exception:
            cache = {}
        return devices, cache

    def health_payload(self, ready: bool = False) -> dict:
        devices, cache = self._snapshot()
        pending = sum(int(item.get("pending", 0)) for item in cache.values())
        dead_letter = sum(int(item.get("dead_letter", 0)) for item in cache.values())
        return {
            "status": "ready" if ready else "ok",
            "service": "duqu-gateway",
            "version": self.VERSION,
            "uptime_seconds": round(max(0.0, time.time() - self._started_at), 3),
            "timestamp": time.time(),
            "devices": len(devices),
            "cache_pending": pending,
            "cache_dead_letter": dead_letter,
        }

    def status_payload(self) -> dict:
        devices, cache = self._snapshot()
        return {
            **self.health_payload(ready=True),
            "device_status": devices,
            "cache_status": cache,
        }

    def metrics_text(self) -> str:
        devices, cache = self._snapshot()
        status_counts: Dict[str, int] = {}
        for device in devices:
            status = str(device.get("runtime_status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        lines = [
            "# HELP duqu_gateway_info Gateway build information.",
            "# TYPE duqu_gateway_info gauge",
            'duqu_gateway_info{version="1"} 1',
            "# HELP duqu_gateway_uptime_seconds Gateway process uptime.",
            "# TYPE duqu_gateway_uptime_seconds gauge",
            f"duqu_gateway_uptime_seconds {time.time() - self._started_at:.3f}",
            "# HELP duqu_gateway_devices_total Configured device count.",
            "# TYPE duqu_gateway_devices_total gauge",
            f"duqu_gateway_devices_total {len(devices)}",
            "# HELP duqu_gateway_devices_by_status Devices by runtime status.",
            "# TYPE duqu_gateway_devices_by_status gauge",
        ]
        for status, count in sorted(status_counts.items()):
            safe_status = status.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'duqu_gateway_devices_by_status{{status="{safe_status}"}} {count}')
        lines.extend([
            "# HELP duqu_gateway_cache_pending Pending offline uploads.",
            "# TYPE duqu_gateway_cache_pending gauge",
            f"duqu_gateway_cache_pending {sum(int(i.get('pending', 0)) for i in cache.values())}",
            "# HELP duqu_gateway_cache_dead_letter Dead-lettered offline uploads.",
            "# TYPE duqu_gateway_cache_dead_letter gauge",
            f"duqu_gateway_cache_dead_letter {sum(int(i.get('dead_letter', 0)) for i in cache.values())}",
        ])
        return "\n".join(lines) + "\n"
