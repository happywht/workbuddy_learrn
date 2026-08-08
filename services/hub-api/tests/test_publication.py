from __future__ import annotations

from hub_api.publication import SCAN_RULES_VERSION, scan_package


def _package(**overrides):
    package = {
        "id": "safe-package",
        "name": "Safe package",
        "version": "1.0.0",
        "kind": "skill",
        "summary": "A package manifest.",
        "license": "MIT",
        "files": [
            {"path": "SKILL.md", "size": 120, "media_type": "text/markdown"},
            {"path": "config.json", "size": 80, "media_type": "application/json"},
        ],
        "dependencies": [{"name": "safe-lib", "version": "1.2.3"}],
    }
    package.update(overrides)
    return package


def test_manifest_scan_accepts_pinned_safe_package():
    status, warnings = scan_package("skill", _package())
    assert status == "passed"
    assert warnings == []
    assert SCAN_RULES_VERSION == "2026-08-08.2"


def test_manifest_scan_blocks_path_symlink_and_mime_escape():
    status, warnings = scan_package("skill", _package(files=[{"path": "../escape.txt"}]))
    assert status == "blocked"
    assert warnings == ["manifest_path_unsafe"]

    status, warnings = scan_package("skill", _package(files=[{"path": "run.sh", "symlink": True}]))
    assert status == "blocked"
    assert warnings == ["manifest_symlink_not_allowed"]

    status, warnings = scan_package(
        "skill",
        _package(files=[{"path": "report.pdf", "media_type": "text/plain"}]),
    )
    assert status == "blocked"
    assert warnings == ["manifest_mime_extension_mismatch"]


def test_manifest_scan_marks_scripts_binaries_macros_and_unpinned_dependencies():
    status, warnings = scan_package(
        "skill",
        _package(
            license=None,
            files=[
                {"path": "run.ps1", "media_type": "text/plain"},
                {"path": "helper.dll", "media_type": "application/octet-stream"},
                {"path": "template.xlsm", "media_type": "application/octet-stream"},
            ],
            dependencies=[{"name": "unreviewed", "source_url": "https://example.test/pkg"}],
        ),
    )
    assert status == "needs_confirmation"
    assert {
        "license_not_declared",
        "executable_script_present",
        "binary_content_present",
        "macro_document_present",
        "dependency_unpinned",
        "external_dependency_review_required",
    } <= set(warnings)
