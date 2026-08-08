from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).parents[3]
SCAN_PATH = REPOSITORY_ROOT / "tools" / "supply_chain_scan.py"
SPEC = importlib.util.spec_from_file_location("supply_chain_scan", SCAN_PATH)
assert SPEC and SPEC.loader
scanner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner
SPEC.loader.exec_module(scanner)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required for lock verification")
def test_production_requirements_match_uv_lock():
    summary = scanner.check_lock(REPOSITORY_ROOT)
    assert summary["path"] == "services/hub-api/requirements.lock"
    assert len(summary["sha256"]) == 64


def test_container_uses_pinned_base_and_hashed_runtime_lock():
    dockerfile = (REPOSITORY_ROOT / "services" / "hub-api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert scanner.PYTHON_IMAGE in dockerfile
    assert "pip install --require-hashes --only-binary=:all: -r requirements.lock" in dockerfile
    assert 'pip install --no-cache-dir ".[postgres]"' not in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_vulnerability_summaries_enforce_policy():
    pip_summary = scanner.summarize_pip_audit(
        {
            "dependencies": [
                {"name": "alpha", "version": "1.0", "vulns": [{"id": "CVE-1"}]},
                {"name": "clean", "version": "2.0", "vulns": []},
            ]
        },
        {},
    )
    assert pip_summary["dependencies"] == 2
    assert pip_summary["blocking"] == 1

    trivy_summary = scanner.summarize_trivy(
        {
            "Results": [
                {
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-2", "PkgName": "beta", "Severity": "HIGH"},
                        {"VulnerabilityID": "CVE-3", "PkgName": "gamma", "Severity": "LOW"},
                    ]
                }
            ]
        },
        {("CVE-2", "beta"): {"id": "CVE-2"}},
    )
    assert trivy_summary["severity_counts"] == {"HIGH": 1, "LOW": 1}
    assert trivy_summary["blocking"] == 0


def test_expired_vulnerability_exception_is_rejected(tmp_path: Path):
    exception_path = tmp_path / "exceptions.json"
    exception_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "exceptions": [
                    {
                        "id": "CVE-1",
                        "package": "alpha",
                        "expires_on": "2026-01-01",
                        "owner": "security",
                        "reason": "temporary",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(scanner.ScanError, match="vulnerability_exception_expired"):
        scanner.load_exceptions(exception_path, today=date(2026, 1, 2))


def test_cyclonedx_summary_requires_components():
    summary = scanner.summarize_sbom(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "components": [{"type": "library"}, {"type": "operating-system"}],
        }
    )
    assert summary["components"] == 2
    assert summary["component_types"] == {"library": 1, "operating-system": 1}


def test_checked_in_exception_file_is_empty_and_valid():
    exceptions = scanner.load_exceptions(
        REPOSITORY_ROOT / "deploy" / "supply-chain" / "vulnerability-exceptions.json"
    )
    assert exceptions == {}
