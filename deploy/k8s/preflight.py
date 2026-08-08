from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml


IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
PLACEHOLDER_MARKERS = (".example.invalid", "sha256:" + "0" * 64, "REPLACE_WITH_")


def render_kustomize(path: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]


def read_documents(path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def index_documents(documents: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        key = (str(document.get("kind", "")), str(document.get("metadata", {}).get("name", "")))
        if key in indexed:
            raise ValueError(f"duplicate resource: {key[0]}/{key[1]}")
        indexed[key] = document
    return indexed


def container(resource: dict[str, Any]) -> dict[str, Any]:
    return resource["spec"]["template"]["spec"]["containers"][0]


def validate(
    documents: list[dict[str, Any]], *, allow_placeholders: bool
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    placeholders: list[str] = []
    indexed = index_documents(documents)

    required = {
        ("Namespace", "workbuddy-hub"),
        ("ServiceAccount", "hub-api"),
        ("ConfigMap", "hub-api-config"),
        ("Deployment", "hub-api"),
        ("Service", "hub-api"),
        ("PodDisruptionBudget", "hub-api"),
        ("Ingress", "hub-api"),
        ("NetworkPolicy", "default-deny"),
        ("NetworkPolicy", "hub-api-allow"),
        ("Job", "hub-api-migrate"),
    }
    missing = sorted(required - set(indexed))
    errors.extend(f"missing resource: {kind}/{name}" for kind, name in missing)
    if missing:
        return errors, placeholders

    namespace = indexed[("Namespace", "workbuddy-hub")]
    namespace_labels = namespace["metadata"].get("labels", {})
    if namespace_labels.get("pod-security.kubernetes.io/enforce") != "restricted":
        errors.append("namespace must enforce the restricted Pod Security profile")

    account = indexed[("ServiceAccount", "hub-api")]
    if account.get("automountServiceAccountToken") is not False:
        errors.append("service account token automount must be disabled")

    config = indexed[("ConfigMap", "hub-api-config")]["data"]
    expected_config = {
        "HUB_ENV": "production",
        "HUB_AUTH_MODE": "oidc",
        "HUB_SEED_DEMO_CASES": "false",
    }
    for key, expected in expected_config.items():
        if config.get(key) != expected:
            errors.append(f"ConfigMap {key} must equal {expected!r}")

    deployment = indexed[("Deployment", "hub-api")]
    deployment_spec = deployment["spec"]
    if int(deployment_spec.get("replicas", 0)) < 2:
        errors.append("Deployment must use at least two replicas")
    rolling = deployment_spec.get("strategy", {}).get("rollingUpdate", {})
    if rolling.get("maxUnavailable") != 0:
        errors.append("Deployment maxUnavailable must be zero")
    app_container = container(deployment)
    command_text = " ".join(app_container.get("command", []) + app_container.get("args", []))
    if "hub_api.migrate" in command_text:
        errors.append("Deployment must not run database migrations")
    for probe, path in (("startupProbe", "/ready"), ("readinessProbe", "/ready"), ("livenessProbe", "/health")):
        if app_container.get(probe, {}).get("httpGet", {}).get("path") != path:
            errors.append(f"Deployment {probe} must target {path}")
    if not app_container.get("resources", {}).get("requests") or not app_container.get("resources", {}).get("limits"):
        errors.append("Deployment must define resource requests and limits")
    security = app_container.get("securityContext", {})
    if security.get("readOnlyRootFilesystem") is not True or security.get("allowPrivilegeEscalation") is not False:
        errors.append("Deployment container security context is incomplete")
    if security.get("capabilities", {}).get("drop") != ["ALL"]:
        errors.append("Deployment must drop all Linux capabilities")

    migration = indexed[("Job", "hub-api-migrate")]
    migration_container = container(migration)
    if migration_container.get("command") != ["python", "-m", "hub_api.migrate"]:
        errors.append("migration Job must run python -m hub_api.migrate")
    app_image = str(app_container.get("image", ""))
    migration_image = str(migration_container.get("image", ""))
    if app_image != migration_image:
        errors.append("Deployment and migration Job must use the same image")
    if not IMAGE_RE.fullmatch(app_image):
        errors.append("Hub image must be pinned by a sha256 digest")

    secret_resources = [key for key in indexed if key[0] == "Secret"]
    if secret_resources:
        errors.append("rendered manifests must not contain a Secret resource")
    for resource_name, workload_container in (
        ("Deployment", app_container),
        ("migration Job", migration_container),
    ):
        secret_refs = [
            item.get("secretRef", {}).get("name")
            for item in workload_container.get("envFrom", [])
            if "secretRef" in item
        ]
        if secret_refs != ["hub-api-secrets"]:
            errors.append(f"{resource_name} must reference only hub-api-secrets")

    service = indexed[("Service", "hub-api")]
    annotations = service["metadata"].get("annotations", {})
    if annotations.get("prometheus.io/path") != "/metrics":
        errors.append("Service must expose the internal metrics scrape annotation")

    ingress = indexed[("Ingress", "hub-api")]
    ingress_paths = {
        path.get("path")
        for rule in ingress["spec"].get("rules", [])
        for path in rule.get("http", {}).get("paths", [])
    }
    if ingress_paths != {"/api", "/health", "/ready"}:
        errors.append("Ingress paths must be exactly /api, /health and /ready")
    if not ingress["spec"].get("tls"):
        errors.append("Ingress must require TLS")

    deny = indexed[("NetworkPolicy", "default-deny")]
    if set(deny["spec"].get("policyTypes", [])) != {"Ingress", "Egress"}:
        errors.append("default-deny NetworkPolicy must cover ingress and egress")
    allowed = indexed[("NetworkPolicy", "hub-api-allow")]
    allowed_selector = allowed["spec"].get("podSelector", {}).get("matchLabels", {})
    migration_labels = migration["spec"]["template"]["metadata"].get("labels", {})
    if any(migration_labels.get(key) != value for key, value in allowed_selector.items()):
        errors.append("migration Job must be selected by the Hub egress NetworkPolicy")
    egress_ports = {
        int(port["port"])
        for rule in allowed["spec"].get("egress", [])
        for port in rule.get("ports", [])
    }
    if not {53, 443, 4318, 5432} <= egress_ports:
        errors.append("Hub NetworkPolicy is missing a required egress port")

    serialized = yaml.safe_dump_all(documents, sort_keys=True)
    placeholders = [marker for marker in PLACEHOLDER_MARKERS if marker in serialized]
    if IMAGE_RE.fullmatch(app_image) and len(set(app_image.rsplit(":", 1)[1])) == 1:
        placeholders.append("repeated sha256 digest")
    if placeholders and not allow_placeholders:
        errors.append("production preflight rejects placeholder image or host values")
    return errors, placeholders


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate rendered WorkBuddy Hub Kubernetes resources.")
    parser.add_argument("--base", type=Path, default=Path(__file__).parent / "base")
    parser.add_argument(
        "--migration", type=Path, default=Path(__file__).parent / "migration-job.yaml"
    )
    parser.add_argument("--allow-placeholders", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        documents = render_kustomize(args.base.resolve()) + read_documents(args.migration.resolve())
        errors, placeholders = validate(documents, allow_placeholders=args.allow_placeholders)
    except (OSError, subprocess.CalledProcessError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        errors = [f"preflight could not inspect manifests: {type(exc).__name__}"]
        placeholders = []
    report = {
        "resources": len(documents) if "documents" in locals() else 0,
        "placeholder_count": len(placeholders),
        "error_count": len(errors),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif errors:
        print("Kubernetes preflight failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print(
            f"Kubernetes preflight passed ({report['resources']} resources, "
            f"{report['placeholder_count']} placeholder markers)."
        )
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
