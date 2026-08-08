#!/usr/bin/env python3
"""Scan repository text files for credential-shaped values without printing them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".playwright-mcp"}
SKIP_SUFFIXES = {
    ".7z", ".avi", ".db", ".gif", ".ico", ".jpeg", ".jpg", ".mov", ".mp3", ".mp4",
    ".pdf", ".png", ".ppt", ".pptx", ".sqlite", ".sqlite3", ".tar", ".webp", ".xls", ".xlsx", ".zip",
}
ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|client[_-]?secret|password|secret)\b\s*[:=]\s*(?P<value>[^\s,#;]+)"
)
PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----")
KNOWN_TOKEN_RE = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|sk-[A-Za-z0-9]{20,})\b")
PLACEHOLDER_RE = re.compile(
    r"(?i)^(?:''|\"\"|null|none|nil|empty|placeholder|changeme|change-me|example|dummy|"
    r"<[^>]+>|\$\{[^}]+\}|\$\([^)]+\)|your[-_].*|replace[-_].*|test[-_].*|local[-_].*|"
    r"do[-_]not[-_]publish|not[-_]a[-_]secret|redacted|no[-_]secret|safe[-_]value)$"
)
VARIABLE_VALUES = {
    "access_token",
    "agentteams_matrix_token",
    "settings.agentteams_matrix_token",
    "agentteams_token",
    "matrix_token",
    "skillhub_token",
    "token",
    "password",
    "PASSWORD",
}
ENV_LOOKUP_RE = re.compile(r"(?i)^(?:os\.environ(?:\.get)?|os\.getenv|process\.env|env)\(")


def _files_from_git(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [root / line for line in result.stdout.splitlines() if line.strip()]


def _files_from_walk(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        paths.append(path)
    return paths


def _is_placeholder(value: str) -> bool:
    value = value.strip().strip(",")
    if len(value) < 8 or PLACEHOLDER_RE.fullmatch(value):
        return True
    return False


def scan(root: Path, *, walk: bool = False) -> tuple[list[dict[str, object]], int]:
    paths = _files_from_walk(root) if walk else _files_from_git(root)
    findings: list[dict[str, object]] = []
    scanned = 0
    for path in paths:
        try:
            if path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), 1):
            if PEM_RE.search(line):
                findings.append({"path": relative, "line": line_number, "rule": "private_key"})
            if KNOWN_TOKEN_RE.search(line):
                findings.append({"path": relative, "line": line_number, "rule": "known_token_prefix"})
            for match in ASSIGNMENT_RE.finditer(line):
                key = match.group(1).lower()
                raw_value = match.group("value").strip()
                value = raw_value.strip("\"'()[]{}.,")
                if value in VARIABLE_VALUES:
                    continue
                if ENV_LOOKUP_RE.match(value):
                    continue
                if not _is_placeholder(value):
                    findings.append({
                        "path": relative,
                        "line": line_number,
                        "rule": f"credential_assignment:{match.group(1).lower()}",
                    })
    return findings, scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--walk", action="store_true", help="scan non-ignored files instead of Git file lists")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()
    root = args.root.resolve()
    findings, scanned = scan(root, walk=args.walk)
    report = {"root": str(root), "scanned_files": scanned, "finding_count": len(findings), "findings": findings}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif findings:
        print(f"secret_scan: {len(findings)} finding(s) in {scanned} text file(s)")
        for finding in findings:
            print(f"- {finding['path']}:{finding['line']} [{finding['rule']}]")
    else:
        print(f"secret_scan: clean ({scanned} text file(s) scanned)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
