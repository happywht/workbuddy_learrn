from __future__ import annotations

import json
import sys
from time import monotonic, sleep
from urllib.parse import urlencode
from urllib.request import urlopen


def get_json(url: str) -> dict:
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"{url}: Prometheus returned {payload.get('status')!r}")
    return payload


def wait_for_hub_target(base_url: str, timeout_seconds: int = 60) -> None:
    query = urlencode({"query": 'up{job="workbuddy-hub-api"}'})
    deadline = monotonic() + timeout_seconds
    last_value = None
    while monotonic() < deadline:
        try:
            result = get_json(f"{base_url}/api/v1/query?{query}")["data"]["result"]
            last_value = result[0]["value"][1] if result else None
            if last_value == "1":
                return
        except (KeyError, IndexError, OSError, RuntimeError):
            pass
        sleep(1)
    raise RuntimeError(f"Prometheus did not observe a healthy Hub target: {last_value!r}")


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:19090"
    wait_for_hub_target(base_url)
    groups = get_json(f"{base_url}/api/v1/rules")["data"]["groups"]
    group = next((item for item in groups if item.get("name") == "workbuddy-hub.rules"), None)
    if group is None:
        raise RuntimeError("WorkBuddy Hub alert group was not loaded")
    alert_names = {rule.get("name") for rule in group.get("rules", [])}
    expected = {
        "WorkBuddyHubTargetDown",
        "WorkBuddyHubElevated5xxRate",
        "WorkBuddyHubCatalogP95Slow",
    }
    if alert_names != expected:
        raise RuntimeError(f"Unexpected Hub alerts: {sorted(alert_names)}")
    print(json.dumps({"hub_target": "up", "alert_rules": len(alert_names)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
