from __future__ import annotations

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read().decode("utf-8")


def check_request_id(url: str) -> None:
    expected = "smoke-request-id"
    request = Request(url, headers={"X-Request-Id": expected})
    with urlopen(request, timeout=10) as response:
        if response.headers.get("X-Request-Id") != expected:
            raise RuntimeError("Hub did not propagate the request ID")


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def expect_error(url: str, status: int, detail: str, headers: dict[str, str] | None = None) -> None:
    try:
        get_json(url, headers=headers)
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        if exc.code != status or payload.get("detail") != detail:
            raise RuntimeError(f"{url}: expected {status} {detail}, got {exc.code} {payload}") from exc
    else:
        raise RuntimeError(f"{url}: expected HTTP {status}")


def check_optional_provider(
    url: str,
    *,
    unavailable_detail: str,
    headers: dict[str, str],
    result_key: str,
) -> str:
    try:
        payload = get_json(url, headers=headers)
    except HTTPError as exc:
        error = json.loads(exc.read().decode("utf-8"))
        if exc.code == 503 and error.get("detail") == unavailable_detail:
            return "not_configured"
        raise RuntimeError(f"{url}: unexpected provider response {exc.code} {error}") from exc
    if not isinstance(payload.get(result_key), list):
        raise RuntimeError(f"{url}: provider response missing {result_key}")
    return "connected"


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8100"
    health = get_json(f"{base_url}/health")
    if health.get("status") != "ok":
        raise RuntimeError("Hub health failed")
    catalog = get_json(f"{base_url}/api/v1/artifacts?kind=case")
    if catalog.get("total") != 4:
        raise RuntimeError(f"Expected 4 seeded cases, got {catalog.get('total')}")
    detail = get_json(f"{base_url}/api/v1/artifacts/case-capacity")
    if detail.get("title") != "项目资料交付检查":
        raise RuntimeError(f"Compatibility case title mismatch: {detail.get('title')!r}")
    check_request_id(f"{base_url}/health")
    metrics = get_text(f"{base_url}/metrics")
    required_metrics = {
        "workbuddy_hub_http_requests_total",
        "workbuddy_hub_http_request_duration_seconds",
        "workbuddy_hub_http_requests_in_progress",
    }
    missing_metrics = {name for name in required_metrics if name not in metrics}
    if missing_metrics:
        raise RuntimeError(f"Hub metrics missing: {sorted(missing_metrics)}")
    if 'route="/api/v1/artifacts/{artifact_id:path}"' not in metrics:
        raise RuntimeError("Hub metrics do not use the artifact route template")
    if 'route="/api/v1/artifacts/case-capacity"' in metrics:
        raise RuntimeError("Hub metrics include a concrete artifact ID")
    mcp = post_json(
        f"{base_url}/api/v1/mcp",
        {"jsonrpc": "2.0", "id": "smoke-tools", "method": "tools/list"},
    )
    tool_names = {item.get("name") for item in mcp.get("result", {}).get("tools", [])}
    required_tools = {"registry.search", "registry.get", "collab.wait", "collab.send"}
    if not required_tools <= tool_names:
        raise RuntimeError(f"MCP tool contract incomplete: missing {sorted(required_tools - tool_names)}")
    provider_headers = {"X-Actor-Id": "smoke-user"}
    skillhub = check_optional_provider(
        f"{base_url}/api/v1/skills?q=skill&limit=5",
        unavailable_detail="skillhub_adapter_not_configured",
        headers=provider_headers,
        result_key="items",
    )
    agentteams = check_optional_provider(
        f"{base_url}/api/v1/collaboration/teams",
        unavailable_detail="agentteams_controller_not_configured",
        headers=provider_headers,
        result_key="teams",
    )
    print(
        json.dumps(
            {
                "health": health["status"],
                "cases": catalog["total"],
                "compatibility_case": detail["id"],
                "compatibility_title": detail["title"],
                "mcp_tools": len(tool_names),
                "observability": "request-id+metrics",
                "skillhub": skillhub,
                "agentteams": agentteams,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
