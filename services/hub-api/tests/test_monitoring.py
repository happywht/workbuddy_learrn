from __future__ import annotations

from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).parents[3]


def test_prometheus_scrapes_hub_over_the_internal_compose_network():
    config = yaml.safe_load(
        (REPOSITORY_ROOT / "deploy" / "monitoring" / "prometheus.yml").read_text(
            encoding="utf-8"
        )
    )
    scrape = config["scrape_configs"][0]
    assert scrape["job_name"] == "workbuddy-hub-api"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["static_configs"][0]["targets"] == ["hub-api:8000"]


def test_alert_rules_have_duration_and_bounded_labels():
    config = yaml.safe_load(
        (REPOSITORY_ROOT / "deploy" / "monitoring" / "hub-alerts.yml").read_text(
            encoding="utf-8"
        )
    )
    rules = config["groups"][0]["rules"]
    assert {rule["alert"] for rule in rules} == {
        "WorkBuddyHubTargetDown",
        "WorkBuddyHubElevated5xxRate",
        "WorkBuddyHubCatalogP95Slow",
    }
    assert all(rule.get("for") for rule in rules)
    expressions = "\n".join(rule["expr"] for rule in rules)
    assert 'route="/api/v1/artifacts"' in expressions
    for forbidden in ("artifact_id", "task_id", "actor_id", "department", "query"):
        assert forbidden not in expressions


def test_public_nginx_does_not_proxy_metrics():
    nginx = (REPOSITORY_ROOT / "deploy" / "nginx" / "workbuddy-hub.conf.example").read_text(
        encoding="utf-8"
    )
    assert "location = /metrics" not in nginx


def test_tracing_overlay_uses_pinned_collector_and_internal_otlp_endpoint():
    overlay = yaml.safe_load(
        (REPOSITORY_ROOT / "deploy" / "compose-poc" / "compose.tracing.yaml").read_text(
            encoding="utf-8"
        )
    )
    services = overlay["services"]
    image = services["otel-collector"]["image"]
    assert image.startswith("otel/opentelemetry-collector-contrib:0.130.1@sha256:")
    assert services["hub-api"]["environment"][
        "HUB_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    ] == "http://otel-collector:4318/v1/traces"
    assert "4318" not in services["otel-collector"]["ports"]
