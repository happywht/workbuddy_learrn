#!/usr/bin/env python3
"""Verify the Hub dependency lock, audit it, scan its image, and emit an SBOM."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4


PYTHON_IMAGE = (
    "python:3.12-alpine@sha256:"
    "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
)
TRIVY_IMAGE = (
    "aquasec/trivy:0.66.0@sha256:"
    "086971aaf400beebd94e8300fd8ea623774419597169156cec56eec5b00dfb1e"
)
PIP_AUDIT_VERSION = "2.9.0"
LOCK_EXPORT_ARGS = [
    "uv",
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "postgres",
    "--no-emit-project",
    "--no-header",
    "--format",
    "requirements.txt",
]
IMAGE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]*$")


class ScanError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    print(f"supply_chain: running {command[0]} {command[1] if len(command) > 1 else ''}".rstrip(), file=sys.stderr)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
        encoding="utf-8",
    )
    if result.returncode not in allowed_returncodes:
        raise ScanError(f"command_failed:{command[0]}:exit_{result.returncode}")
    return result


def normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip() + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_lock(repository_root: Path) -> dict[str, Any]:
    service_root = repository_root / "services" / "hub-api"
    lock_path = service_root / "requirements.lock"
    if not lock_path.is_file():
        raise ScanError("requirements_lock_missing")
    if shutil.which("uv") is None:
        raise ScanError("uv_not_found")
    exported = run(LOCK_EXPORT_ARGS, cwd=service_root, capture=True).stdout
    checked_in = lock_path.read_text(encoding="utf-8")
    if normalized_text(exported) != normalized_text(checked_in):
        raise ScanError(
            "requirements_lock_drift: regenerate with "
            "uv export --frozen --no-dev --extra postgres --no-emit-project "
            "--no-header --format requirements.txt --output-file requirements.lock"
        )
    return {"path": lock_path.relative_to(repository_root).as_posix(), "sha256": sha256_file(lock_path)}


def load_exceptions(path: Path, *, today: date | None = None) -> dict[tuple[str, str], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("exceptions"), list):
        raise ScanError("vulnerability_exceptions_schema_invalid")
    current_date = today or date.today()
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for item in payload["exceptions"]:
        if not isinstance(item, dict):
            raise ScanError("vulnerability_exception_invalid")
        required = ("id", "package", "expires_on", "owner", "reason")
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required):
            raise ScanError("vulnerability_exception_fields_invalid")
        try:
            expires_on = date.fromisoformat(item["expires_on"])
        except ValueError as exc:
            raise ScanError("vulnerability_exception_expiry_invalid") from exc
        if expires_on < current_date:
            raise ScanError(f"vulnerability_exception_expired:{item['id']}:{item['package']}")
        key = (item["id"].upper(), item["package"].lower())
        if key in indexed:
            raise ScanError(f"vulnerability_exception_duplicate:{item['id']}:{item['package']}")
        indexed[key] = {key: item[key] for key in required}
    return indexed


def is_excepted(
    vulnerability_id: str,
    package: str,
    exceptions: dict[tuple[str, str], dict[str, str]],
) -> bool:
    return (vulnerability_id.upper(), package.lower()) in exceptions


def summarize_pip_audit(
    payload: dict[str, Any],
    exceptions: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list):
        raise ScanError("pip_audit_report_invalid")
    findings: list[dict[str, str | bool]] = []
    for dependency in dependencies:
        package = str(dependency.get("name", "unknown"))
        version = str(dependency.get("version", "unknown"))
        vulnerabilities = dependency.get("vulns") or []
        if not isinstance(vulnerabilities, list):
            raise ScanError("pip_audit_vulnerabilities_invalid")
        for vulnerability in vulnerabilities:
            vulnerability_id = str(vulnerability.get("id", "unknown"))
            findings.append(
                {
                    "id": vulnerability_id,
                    "package": package,
                    "version": version,
                    "excepted": is_excepted(vulnerability_id, package, exceptions),
                }
            )
    return {
        "dependencies": len(dependencies),
        "vulnerabilities": len(findings),
        "excepted": sum(1 for finding in findings if finding["excepted"]),
        "blocking": sum(1 for finding in findings if not finding["excepted"]),
        "findings": findings,
    }


def summarize_trivy(
    payload: dict[str, Any],
    exceptions: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    results = payload.get("Results") or []
    if not isinstance(results, list):
        raise ScanError("trivy_report_invalid")
    severity_counts: Counter[str] = Counter()
    findings: list[dict[str, str | bool]] = []
    for result in results:
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise ScanError("trivy_vulnerabilities_invalid")
        for vulnerability in vulnerabilities:
            vulnerability_id = str(vulnerability.get("VulnerabilityID", "unknown"))
            package = str(vulnerability.get("PkgName", "unknown"))
            severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()
            severity_counts[severity] += 1
            excepted = is_excepted(vulnerability_id, package, exceptions)
            findings.append(
                {
                    "id": vulnerability_id,
                    "package": package,
                    "severity": severity,
                    "excepted": excepted,
                }
            )
    blocking = [
        finding
        for finding in findings
        if finding["severity"] in {"HIGH", "CRITICAL"} and not finding["excepted"]
    ]
    return {
        "vulnerabilities": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "excepted": sum(1 for finding in findings if finding["excepted"]),
        "blocking": len(blocking),
        "blocking_findings": blocking,
    }


def summarize_sbom(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("bomFormat") != "CycloneDX" or not isinstance(payload.get("components"), list):
        raise ScanError("cyclonedx_sbom_invalid")
    components = payload["components"]
    types = Counter(str(component.get("type", "unknown")) for component in components)
    return {
        "format": payload["bomFormat"],
        "spec_version": payload.get("specVersion"),
        "serial_number": payload.get("serialNumber"),
        "components": len(components),
        "component_types": dict(sorted(types.items())),
    }


def docker_mount(path: Path, container_path: str, *, read_only: bool = False) -> str:
    suffix = ":ro" if read_only else ""
    return f"{path.resolve()}:{container_path}{suffix}"


def parse_json_report(raw: str, report_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScanError(f"{report_name}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ScanError(f"{report_name}_json_invalid")
    return payload


def audit_dependencies(lock_path: Path, scan_dir: Path) -> tuple[dict[str, Any], int]:
    shutil.copy2(lock_path, scan_dir / "requirements.lock")
    command = [
        "docker",
        "run",
        "--rm",
        "--volume",
        docker_mount(scan_dir, "/scan", read_only=True),
        "--entrypoint",
        "sh",
        PYTHON_IMAGE,
        "-ec",
        (
            f"python -m pip install --no-cache-dir pip-audit=={PIP_AUDIT_VERSION} 1>&2; "
            "python -m pip_audit --disable-pip --strict --format json "
            "--requirement /scan/requirements.lock"
        ),
    ]
    result = run(command, capture=True, allowed_returncodes=(0, 1))
    (scan_dir / "pip-audit.json").write_text(normalized_text(result.stdout), encoding="utf-8")
    return parse_json_report(result.stdout, "pip_audit"), result.returncode


def scan_image(image_tag: str, image_tar: Path, cache_dir: Path, scan_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    mounts = [
        "--volume",
        docker_mount(image_tar.parent, "/scan", read_only=True),
        "--volume",
        docker_mount(cache_dir, "/root/.cache/trivy"),
    ]
    common = [
        "docker",
        "run",
        "--rm",
        *mounts,
        TRIVY_IMAGE,
        "image",
        "--quiet",
        "--input",
        f"/scan/{image_tar.name}",
    ]
    vulnerability_result = run(
        [*common, "--scanners", "vuln", "--format", "json"],
        capture=True,
    )
    (scan_dir / "trivy-vulnerabilities.json").write_text(
        normalized_text(vulnerability_result.stdout), encoding="utf-8"
    )
    sbom_result = run([*common, "--format", "cyclonedx"], capture=True)
    (scan_dir / "hub-api.cdx.json").write_text(
        normalized_text(sbom_result.stdout), encoding="utf-8"
    )
    return (
        parse_json_report(vulnerability_result.stdout, "trivy"),
        parse_json_report(sbom_result.stdout, "cyclonedx"),
    )


def validate_image_tag(image_tag: str) -> None:
    if not IMAGE_TAG_RE.fullmatch(image_tag):
        raise ScanError("image_tag_invalid")
    result = subprocess.run(
        ["docker", "image", "inspect", image_tag],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode == 0:
        raise ScanError("image_tag_already_exists")


def full_scan(
    repository_root: Path,
    output_dir: Path,
    image_tag: str,
    exceptions_path: Path,
    *,
    keep_image: bool,
) -> dict[str, Any]:
    if shutil.which("docker") is None:
        raise ScanError("docker_not_found")
    validate_image_tag(image_tag)
    lock_summary = check_lock(repository_root)
    exceptions = load_exceptions(exceptions_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "summary.json",
        "pip-audit.json",
        "trivy-vulnerabilities.json",
        "hub-api.cdx.json",
    ):
        (output_dir / filename).unlink(missing_ok=True)
    image_created = False
    with tempfile.TemporaryDirectory(prefix="workbuddy-supply-chain-") as temporary:
        temporary_root = Path(temporary)
        scan_dir = temporary_root / "scan"
        cache_dir = temporary_root / "trivy-cache"
        scan_dir.mkdir()
        cache_dir.mkdir()
        pip_payload, pip_returncode = audit_dependencies(
            repository_root / lock_summary["path"], scan_dir
        )
        shutil.copy2(scan_dir / "pip-audit.json", output_dir / "pip-audit.json")
        try:
            run(
                [
                    "docker",
                    "build",
                    "--pull",
                    "--file",
                    str(repository_root / "services" / "hub-api" / "Dockerfile"),
                    "--tag",
                    image_tag,
                    str(repository_root),
                ]
            )
            image_created = True
            image_id = run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image_tag],
                capture=True,
            ).stdout.strip()
            image_tar = scan_dir / "hub-api-image.tar"
            run(["docker", "image", "save", "--output", str(image_tar), image_tag])
            trivy_payload, sbom_payload = scan_image(
                image_tag, image_tar, cache_dir, output_dir
            )
        finally:
            if image_created and not keep_image:
                run(["docker", "image", "rm", image_tag])

    pip_summary = summarize_pip_audit(pip_payload, exceptions)
    trivy_summary = summarize_trivy(trivy_payload, exceptions)
    sbom_summary = summarize_sbom(sbom_payload)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "pip_audit": "all unexcepted findings block",
            "trivy": "unexcepted HIGH or CRITICAL findings block",
            "expired_exceptions": "block before scanning",
        },
        "tools": {
            "pip_audit": PIP_AUDIT_VERSION,
            "pip_audit_runtime": PYTHON_IMAGE,
            "trivy": TRIVY_IMAGE,
        },
        "lock": lock_summary,
        "image": {"tag": image_tag, "id": image_id, "retained": keep_image},
        "pip_audit": pip_summary,
        "trivy": trivy_summary,
        "sbom": sbom_summary,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if pip_returncode == 1 and not pip_summary["vulnerabilities"]:
        raise ScanError("pip_audit_strict_check_failed_without_reported_vulnerability")
    if pip_summary["blocking"] or trivy_summary["blocking"]:
        raise ScanError(
            f"vulnerability_policy_failed:pip_audit={pip_summary['blocking']}:"
            f"trivy_high_critical={trivy_summary['blocking']}"
        )
    return summary


def main() -> int:
    repository_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=repository_default)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repository_default / "artifacts" / "supply-chain",
    )
    parser.add_argument("--exceptions", type=Path)
    parser.add_argument("--image-tag")
    parser.add_argument("--keep-image", action="store_true")
    parser.add_argument("--lock-only", action="store_true")
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    exceptions_path = (
        args.exceptions.resolve()
        if args.exceptions
        else repository_root / "deploy" / "supply-chain" / "vulnerability-exceptions.json"
    )
    try:
        if args.lock_only:
            summary = {"lock": check_lock(repository_root)}
        else:
            image_tag = args.image_tag or f"workbuddy-hub-api:supply-chain-{uuid4().hex[:12]}"
            summary = full_scan(
                repository_root,
                args.output_dir.resolve(),
                image_tag,
                exceptions_path,
                keep_image=args.keep_image,
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ScanError, json.JSONDecodeError) as exc:
        print(f"supply_chain: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
