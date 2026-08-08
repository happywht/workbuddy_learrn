from __future__ import annotations

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagators.textmap import CarrierT
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


TRACE_PROPAGATOR = TraceContextTextMapPropagator()


def create_tracer_provider(
    *,
    service_name: str,
    environment: str,
    sample_ratio: float,
    endpoint: str | None = None,
    timeout_seconds: float = 5.0,
    span_exporter: SpanExporter | None = None,
    synchronous_export: bool = False,
) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "deployment.environment.name": environment,
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
    )
    exporter = span_exporter
    if exporter is None and endpoint is not None:
        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=timeout_seconds)
    if exporter is not None:
        processor = (
            SimpleSpanProcessor(exporter)
            if synchronous_export
            else BatchSpanProcessor(exporter)
        )
        provider.add_span_processor(processor)
    return provider


def current_trace_fields() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def inject_trace_context(request: httpx.Request) -> None:
    carrier: CarrierT = {}
    TRACE_PROPAGATOR.inject(carrier)
    for name, value in carrier.items():
        request.headers[name] = value


def _request_headers(scope: Scope) -> dict[str, str]:
    return {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in scope.get("headers", [])
    }


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "unmatched"


class TracingMiddleware:
    def __init__(self, app: ASGIApp, tracer_provider: TracerProvider) -> None:
        self.app = app
        self.tracer = trace.get_tracer("hub_api.http", tracer_provider=tracer_provider)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "UNKNOWN")).upper()
        parent_context = TRACE_PROPAGATOR.extract(carrier=_request_headers(scope))
        status_code = 500
        with self.tracer.start_as_current_span(
            f"{method} HTTP",
            context=parent_context,
            kind=SpanKind.SERVER,
            attributes={"http.request.method": method},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            trace_fields = current_trace_fields()

            async def send_with_trace_id(message: Message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = int(message["status"])
                    if trace_fields:
                        headers = MutableHeaders(scope=message)
                        headers["X-Trace-Id"] = trace_fields["trace_id"]
                await send(message)

            try:
                await self.app(scope, receive, send_with_trace_id)
            except BaseException as exc:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", type(exc).__name__)
                raise
            finally:
                route = _route_template(scope)
                span.update_name(f"{method} {route}")
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status_code)
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
