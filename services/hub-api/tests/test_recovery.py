from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


SCRIPT_ROOT = Path(__file__).parents[3] / "deploy" / "compose-poc"
sys.path.insert(0, str(SCRIPT_ROOT))

from backup import sha256_file  # noqa: E402
from restore_drill import load_manifest  # noqa: E402


def test_restore_manifest_detects_backup_tampering(tmp_path: Path):
    backup = tmp_path / "workbuddy-hub-test.dump"
    backup.write_bytes(b"synthetic-postgres-backup")
    manifest = backup.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "backup_file": backup.name,
                "size": backup.stat().st_size,
                "sha256": sha256_file(backup),
            }
        ),
        encoding="utf-8",
    )
    assert load_manifest(backup, None)["backup_file"] == backup.name
    backup.write_bytes(b"tampered-postgres-backup")
    with pytest.raises(RuntimeError, match="backup_manifest_sha256_mismatch"):
        load_manifest(backup, None)
