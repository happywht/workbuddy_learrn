from __future__ import annotations

import re
import sys
from time import monotonic, sleep
from urllib.request import Request, urlopen


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"
ACCEPTED_SPANS = re.compile(
    r'^otelcol_receiver_accepted_spans(?:_total)?\{[^}]*receiver="otlp"[^}]*transport="http"[^}]*\}\s+([0-9.eE+-]+)$',
    re.MULTILINE,
)


def get_text(url: str, headers: dict[str, str] | None = None) -> tuple[str, object]:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read().decode("utf-8"), response.headers


def wait_for_collector(health_url: str, timeout_seconds: int = 45) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        try:
            get_text(health_url)
            return
        except OSError:
            sleep(1)
    raise RuntimeError("OpenTelemetry Collector did not become healthy")


def wait_for_span(metrics_url: str, timeout_seconds: int = 45) -> float:
    deadline = monotonic() + timeout_seconds
    last_value = 0.0
    while monotonic() < deadline:
        try:
            metrics, _ = get_text(metrics_url)
            values = [float(value) for value in ACCEPTED_SPANS.findall(metrics)]
            last_value = sum(values)
            if last_value >= 1:
                return last_value
        except (OSError, ValueError):
            pass
        sleep(1)
    raise RuntimeError(f"Collector did not report an accepted OTLP/HTTP span: {last_value}")


def main() -> int:
    hub_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8100"
    collector_url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:18889"
    health_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:13134"
    wait_for_collector(health_url)
    _, headers = get_text(
        f"{hub_url}/health",
        headers={
            "traceparent": f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01",
            "X-Request-Id": "tracing-smoke",
        },
    )
    if headers.get("X-Trace-Id") != TRACE_ID:
        raise RuntimeError("Hub did not preserve the incoming W3C trace ID")
    accepted = wait_for_span(f"{collector_url}/metrics")
    print(f'{{"trace_id":"{TRACE_ID}","accepted_spans":{accepted:g}}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
