from __future__ import annotations

import hashlib
import json
import mimetypes
import posixpath
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import PublicationPreview


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]"),
    re.compile(r"(?i)\b(sk-[a-z0-9]{12,}|gh[pousr]_[a-z0-9_]{20,})\b"),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]"),
    re.compile(r"(?<![A-Za-z])/(?:home|Users|var|etc|tmp|output)(?:/|$)"),
)
SCAN_RULES_VERSION = "2026-08-08.2"
MAX_MANIFEST_FILE_BYTES = 25 * 1024 * 1024
MAX_MANIFEST_TOTAL_BYTES = 100 * 1024 * 1024
SCRIPT_SUFFIXES = {".bat", ".cmd", ".js", ".mjs", ".ps1", ".py", ".sh", ".vbs"}
BINARY_SUFFIXES = {".bin", ".dll", ".dylib", ".exe", ".so"}
MACRO_SUFFIXES = {".docm", ".dotm", ".potm", ".ppsm", ".xlsm", ".xltm"}
EXPECTED_MIME_TYPES = {
    ".csv": {"text/csv", "application/csv"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".json": {"application/json", "text/json"},
    ".md": {"text/markdown", "text/plain"},
    ".pdf": {"application/pdf"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_sha256(package: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(package)).hexdigest()


def _manifest_entries(package: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw_files = package.get("files")
    if raw_files is None:
        return [], []
    if not isinstance(raw_files, list):
        return [], ["files_manifest_invalid"]
    entries: list[dict[str, Any]] = []
    for item in raw_files:
        if isinstance(item, str):
            entries.append({"path": item})
        elif isinstance(item, dict):
            entries.append(item)
        else:
            return [], ["files_manifest_invalid"]
    return entries, []


def _scan_manifest(package: dict[str, Any]) -> tuple[str, list[str]]:
    entries, errors = _manifest_entries(package)
    if errors:
        return "blocked", errors
    warnings: list[str] = []
    total_size = 0
    executable = binary = macro = False
    for entry in entries:
        raw_path = entry.get("path", entry.get("name"))
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            return "blocked", ["manifest_path_invalid"]
        normalized = raw_path.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if (
            normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized)
            or ".." in parts
            or posixpath.normpath(normalized).startswith("../")
        ):
            return "blocked", ["manifest_path_unsafe"]
        if entry.get("type") in {"symlink", "link"} or entry.get("symlink") is True:
            return "blocked", ["manifest_symlink_not_allowed"]
        size = entry.get("size")
        if size is not None and (not isinstance(size, int) or size < 0 or size > MAX_MANIFEST_FILE_BYTES):
            return "blocked", ["manifest_file_size_invalid"]
        if isinstance(size, int):
            total_size += size
        suffix = posixpath.splitext(normalized)[1].lower()
        declared_mime = entry.get("media_type", entry.get("mime_type"))
        if suffix in EXPECTED_MIME_TYPES:
            if declared_mime is None:
                warnings.append("manifest_mime_missing")
            elif str(declared_mime).split(";", 1)[0].strip().lower() not in EXPECTED_MIME_TYPES[suffix]:
                return "blocked", ["manifest_mime_extension_mismatch"]
        elif declared_mime is None:
            guessed, _ = mimetypes.guess_type(normalized)
            if guessed is None:
                warnings.append("manifest_mime_unknown")
        executable = executable or suffix in SCRIPT_SUFFIXES
        binary = binary or suffix in BINARY_SUFFIXES
        macro = macro or suffix in MACRO_SUFFIXES
    if total_size > MAX_MANIFEST_TOTAL_BYTES:
        return "blocked", ["manifest_total_size_invalid"]
    if executable:
        warnings.append("executable_script_present")
    if binary:
        warnings.append("binary_content_present")
    if macro:
        warnings.append("macro_document_present")
    return "needs_confirmation" if warnings else "passed", warnings


def _scan_dependencies(package: dict[str, Any]) -> tuple[str, list[str]]:
    dependencies = package.get("dependencies")
    if dependencies is None:
        return "passed", []
    if not isinstance(dependencies, list):
        return "blocked", ["dependencies_manifest_invalid"]
    warnings: list[str] = []
    for dependency in dependencies:
        if isinstance(dependency, str):
            if not re.search(r"(?:==|@|\b[vV]?\d+\.\d+)", dependency):
                warnings.append("dependency_unpinned")
        elif isinstance(dependency, dict):
            if not dependency.get("version") and not dependency.get("digest"):
                warnings.append("dependency_unpinned")
            if dependency.get("source_url") or dependency.get("url"):
                warnings.append("external_dependency_review_required")
        else:
            return "blocked", ["dependencies_manifest_invalid"]
    return "needs_confirmation" if warnings else "passed", warnings


def scan_package(kind: str, package: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    required = {"id", "name", "version", "kind", "summary"}
    missing = sorted(required - package.keys())
    if missing:
        return "blocked", [f"missing_required_fields:{','.join(missing)}"]
    if package.get("kind") != kind:
        return "blocked", ["package_kind_mismatch"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", str(package["id"])):
        warnings.append("id_not_registry_safe")
    text = canonical_json(package).decode("utf-8", errors="replace")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return "blocked", ["potential_secret_or_credential"]
    if any(pattern.search(text) for pattern in ABSOLUTE_PATH_PATTERNS):
        return "blocked", ["absolute_local_path"]
    license_value = package.get("license", package.get("licenses"))
    if license_value is None:
        warnings.append("license_not_declared")
    elif not isinstance(license_value, (str, list, dict)):
        return "blocked", ["license_manifest_invalid"]
    manifest_status, manifest_warnings = _scan_manifest(package)
    if manifest_status == "blocked":
        return "blocked", manifest_warnings
    warnings.extend(manifest_warnings)
    dependency_status, dependency_warnings = _scan_dependencies(package)
    if dependency_status == "blocked":
        return "blocked", dependency_warnings
    warnings.extend(dependency_warnings)
    sanitization = package.get("sanitization")
    if isinstance(sanitization, dict) and sanitization.get("status") == "blocked":
        return "blocked", ["package_sanitization_blocked"]
    if isinstance(sanitization, dict) and sanitization.get("status") == "needs_confirmation":
        warnings.append("sanitization_needs_confirmation")
    return ("needs_confirmation" if warnings else "passed"), warnings


def make_preview_id() -> str:
    return f"preview_{secrets.token_urlsafe(18)}"


def expires_at(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def is_expired(preview: PublicationPreview) -> bool:
    expires = preview.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)
