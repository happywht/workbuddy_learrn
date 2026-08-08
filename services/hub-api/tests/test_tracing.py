from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from hub_api.config import Settings
from hub_api.observability import ObservabilityMiddleware
from hub_api.tracing import TracingMiddleware, create_tracer_provider, inject_trace_context


PARENT_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"


def traced_app(exporter: InMemorySpanExporter) -> tuple[FastAPI, object]:
    provider = create_tracer_provider(
        service_name="workbuddy-hub-test",
        environment="test",
        sample_ratio=1,
        span_exporter=exporter,
        synchronous_export=True,
    )
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(TracingMiddleware, tracer_provider=provider)

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    return app, provider


def test_trace_context_links_response_span_and_access_log(caplog: pytest.LogCaptureFixture):
    exporter = InMemorySpanExporter()
    app, provider = traced_app(exporter)
    with caplog.at_level(logging.INFO, logger="hub_api.access"):
        with TestClient(app) as client:
            response = client.get(
                "/items/item-42?token=query-marker",
                headers={
                    "Authorization": "Bearer opaque-header-marker",
                    "traceparent": f"00-{PARENT_TRACE_ID}-{PARENT_SPAN_ID}-01",
                    "X-Request-Id": "trace-log-test",
                },
            )

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"] == PARENT_TRACE_ID
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET /items/{item_id}"
    assert format(span.context.trace_id, "032x") == PARENT_TRACE_ID
    assert span.parent is not None and format(span.parent.span_id, "016x") == PARENT_SPAN_ID
    assert span.attributes == {
        "http.request.method": "GET",
        "http.response.status_code": 200,
        "http.route": "/items/{item_id}",
    }
    access_record = next(record for record in caplog.records if record.name == "hub_api.access")
    log_payload = json.loads(access_record.message)
    assert log_payload["trace_id"] == PARENT_TRACE_ID
    assert log_payload["span_id"] == format(span.context.span_id, "016x")
    assert "opaque-header-marker" not in access_record.message
    assert "query-marker" not in access_record.message
    provider.shutdown()


def test_trace_does_not_export_exception_message():
    exporter = InMemorySpanExporter()
    provider = create_tracer_provider(
        service_name="workbuddy-hub-test",
        environment="test",
        sample_ratio=1,
        span_exporter=exporter,
        synchronous_export=True,
    )
    app = FastAPI()
    app.add_middleware(TracingMiddleware, tracer_provider=provider)

    @app.get("/failure")
    def failure() -> None:
        raise RuntimeError("private-exception-marker")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")

    assert response.status_code == 500
    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.events == ()
    assert "private-exception-marker" not in repr(span.attributes)
    provider.shutdown()


def test_outbound_httpx_hook_injects_current_traceparent():
    exporter = InMemorySpanExporter()
    provider = create_tracer_provider(
        service_name="workbuddy-hub-test",
        environment="test",
        sample_ratio=1,
        span_exporter=exporter,
        synchronous_export=True,
    )
    tracer = trace.get_tracer("test", tracer_provider=provider)
    with tracer.start_as_current_span("parent") as span:
        request = httpx.Request("GET", "https://provider.example/resource")
        inject_trace_context(request)
        expected_trace_id = format(span.get_span_context().trace_id, "032x")

    assert request.headers["traceparent"].split("-")[1] == expected_trace_id
    assert "baggage" not in request.headers
    provider.shutdown()


def test_otlp_exporter_posts_protobuf_to_configured_trace_endpoint():
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received.update(
                path=self.path,
                content_type=self.headers.get("Content-Type"),
                body=self.rfile.read(length),
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/traces"
    provider = create_tracer_provider(
        service_name="workbuddy-hub-test",
        environment="test",
        sample_ratio=1,
        endpoint=endpoint,
    )
    try:
        tracer = trace.get_tracer("test", tracer_provider=provider)
        with tracer.start_as_current_span("otlp-export-test"):
            pass
        assert provider.force_flush(timeout_millis=5_000)
    finally:
        provider.shutdown()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert received["path"] == "/v1/traces"
    assert received["content_type"] == "application/x-protobuf"
    assert isinstance(received["body"], bytes) and received["body"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:pass@collector.example/v1/traces",
        "https://collector.example/v1/traces?token=value",
        "https://collector.example/v1/metrics",
        "file:///tmp/v1/traces",
    ],
)
def test_otel_endpoint_rejects_unsafe_or_wrong_urls(endpoint: str):
    with pytest.raises(ValidationError):
        Settings(otel_exporter_otlp_traces_endpoint=endpoint)


def test_otel_endpoint_accepts_explicit_trace_receiver():
    settings = Settings(
        otel_exporter_otlp_traces_endpoint="https://collector.example/v1/traces"
    )
    assert settings.otel_exporter_otlp_traces_endpoint == "https://collector.example/v1/traces"
