from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import platform
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
READ_ONLY_PATHS = {"/health", "/ready", "/api/v1/artifacts"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Sample:
    duration_ms: float
    status: int | None
    response_bytes: int
    error_type: str | None = None


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def validate_target(url: str, *, allow_remote: bool) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("target must not contain credentials or a fragment")
    if parsed.path not in READ_ONLY_PATHS:
        raise ValueError(f"target path must be one of {sorted(READ_ONLY_PATHS)}")
    if parsed.hostname not in LOCAL_HOSTS and not allow_remote:
        raise ValueError("remote targets require --allow-remote")


def request_once(url: str, *, timeout_seconds: float, request_number: int) -> Sample:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "workbuddy-hub-load-probe/1",
            "X-Request-Id": f"load-probe-{request_number}",
        },
    )
    started = perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            duration_ms = (perf_counter() - started) * 1000
            if len(body) > MAX_RESPONSE_BYTES:
                return Sample(duration_ms, response.status, len(body), "ResponseTooLarge")
            return Sample(duration_ms, response.status, len(body))
    except HTTPError as exc:
        return Sample((perf_counter() - started) * 1000, exc.code, 0, "HTTPError")
    except (TimeoutError, URLError, OSError) as exc:
        return Sample((perf_counter() - started) * 1000, None, 0, type(exc).__name__)


def run_probe(
    url: str,
    *,
    request_count: int,
    concurrency: int,
    warmup_count: int,
    timeout_seconds: float,
) -> dict[str, object]:
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        list(
            executor.map(
                lambda number: request_once(
                    url, timeout_seconds=timeout_seconds, request_number=-number - 1
                ),
                range(warmup_count),
            )
        )
        started = perf_counter()
        samples = list(
            executor.map(
                lambda number: request_once(
                    url, timeout_seconds=timeout_seconds, request_number=number
                ),
                range(request_count),
            )
        )
        elapsed_seconds = perf_counter() - started

    latencies = [sample.duration_ms for sample in samples]
    status_counts = Counter(
        str(sample.status) if sample.status is not None else "transport_error" for sample in samples
    )
    error_counts = Counter(sample.error_type for sample in samples if sample.error_type)
    successful = sum(1 for sample in samples if sample.status and 200 <= sample.status < 300)
    errors = request_count - successful
    return {
        "requests": request_count,
        "successful": successful,
        "errors": errors,
        "error_rate": errors / request_count,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "requests_per_second": round(request_count / elapsed_seconds, 3),
        "latency_ms": {
            "min": round(min(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "error_types": dict(sorted((str(key), value) for key, value in error_counts.items())),
        "response_bytes": sum(sample.response_bytes for sample in samples),
    }


def thresholds_pass(
    result: dict[str, object], *, max_error_rate: float, max_p95_ms: float
) -> bool:
    latency = result.get("latency_ms")
    if not isinstance(latency, dict):
        return False
    return (
        float(result.get("error_rate", 1.0)) <= max_error_rate
        and float(latency.get("p95", float("inf"))) <= max_p95_ms
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded read-only Hub API load probe.")
    parser.add_argument("url")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=1000.0)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not 1 <= args.requests <= 100_000:
        parser.error("--requests must be between 1 and 100000")
    if not 1 <= args.concurrency <= 200:
        parser.error("--concurrency must be between 1 and 200")
    if not 0 <= args.warmup <= 10_000:
        parser.error("--warmup must be between 0 and 10000")
    if args.timeout <= 0 or not 0 <= args.max_error_rate <= 1 or args.max_p95_ms <= 0:
        parser.error("timeout and p95 threshold must be positive; error rate must be 0..1")
    try:
        validate_target(args.url, allow_remote=args.allow_remote)
    except ValueError as exc:
        parser.error(str(exc))

    result = run_probe(
        args.url,
        request_count=args.requests,
        concurrency=args.concurrency,
        warmup_count=args.warmup,
        timeout_seconds=args.timeout,
    )
    passed = thresholds_pass(
        result,
        max_error_rate=args.max_error_rate,
        max_p95_ms=args.max_p95_ms,
    )
    report = {
        "schema_version": 1,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local read-only probe; not a production capacity commitment",
        "target": {
            "scheme": urlsplit(args.url).scheme,
            "host": urlsplit(args.url).hostname,
            "port": urlsplit(args.url).port,
            "path": urlsplit(args.url).path,
        },
        "profile": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "timeout_seconds": args.timeout,
        },
        "thresholds": {
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "result": result,
        "passed": passed,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
