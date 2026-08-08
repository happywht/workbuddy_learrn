from __future__ import annotations

from contextvars import ContextVar
import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .tracing import current_trace_fields


ACCESS_LOGGER = logging.getLogger("hub_api.access")
ACCESS_LOGGER.setLevel(logging.INFO)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

HTTP_REQUESTS = Counter(
    "workbuddy_hub_http_requests_total",
    "Completed HTTP requests.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "workbuddy_hub_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "workbuddy_hub_http_requests_in_progress",
    "HTTP requests currently being processed.",
    ("method",),
)


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            if REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
            break
    return str(uuid4())


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "unmatched"


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "UNKNOWN")).upper()
        request_id = _request_id(scope)
        status_code = 500
        started = perf_counter()
        context_token = request_id_context.set(request_id)
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = perf_counter() - started
            route = _route_template(scope)
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration)
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
            log_payload = {
                "event": "http_request",
                "request_id": request_id,
                "method": method,
                "route": route,
                "status": status_code,
                "duration_ms": round(duration * 1000, 3),
                **current_trace_fields(),
            }
            ACCESS_LOGGER.info(
                json.dumps(
                    log_payload,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            request_id_context.reset(context_token)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
