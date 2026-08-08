from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import sys
from threading import Thread

import pytest


REPOSITORY_ROOT = Path(__file__).parents[3]
PROBE_PATH = REPOSITORY_ROOT / "deploy" / "performance" / "hub_load_probe.py"
SPEC = importlib.util.spec_from_file_location("hub_load_probe", PROBE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def test_percentile_uses_nearest_rank():
    assert probe.percentile([4, 1, 3, 2], 0.5) == 2
    assert probe.percentile([4, 1, 3, 2], 0.95) == 4
    assert probe.percentile([], 0.95) == 0


@pytest.mark.parametrize(
    "url,allow_remote",
    [
        ("https://hub.example.test/api/v1/artifacts", False),
        ("http://127.0.0.1:8000/api/v1/collaboration/tasks", False),
        ("http://user:pass@127.0.0.1:8000/health", False),
    ],
)
def test_probe_rejects_remote_write_or_credential_targets(url: str, allow_remote: bool):
    with pytest.raises(ValueError):
        probe.validate_target(url, allow_remote=allow_remote)


def test_probe_collects_success_latency_and_status_counts():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = probe.run_probe(
            f"http://127.0.0.1:{server.server_port}/health",
            request_count=30,
            concurrency=5,
            warmup_count=3,
            timeout_seconds=2,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result["requests"] == 30
    assert result["successful"] == 30
    assert result["errors"] == 0
    assert result["status_counts"] == {"200": 30}
    assert result["requests_per_second"] > 0
    assert result["latency_ms"]["p95"] >= result["latency_ms"]["p50"]


def test_threshold_gate_fails_on_errors_or_slow_p95():
    passing = {"error_rate": 0.0, "latency_ms": {"p95": 100.0}}
    assert probe.thresholds_pass(passing, max_error_rate=0, max_p95_ms=1000)
    assert not probe.thresholds_pass(
        {"error_rate": 0.01, "latency_ms": {"p95": 100.0}},
        max_error_rate=0,
        max_p95_ms=1000,
    )
    assert not probe.thresholds_pass(
        {"error_rate": 0.0, "latency_ms": {"p95": 1001.0}},
        max_error_rate=0,
        max_p95_ms=1000,
    )
