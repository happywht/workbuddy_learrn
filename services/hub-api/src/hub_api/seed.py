from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, init_db
from .models import Artifact, ArtifactVersion


def _semver(value: str) -> str:
    value = value.strip().lstrip("v")
    match = re.fullmatch(r"(\d+)\.(\d+)", value)
    return f"{match.group(1)}.{match.group(2)}.0" if match else value


def _sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def import_cases(db: Session, registry_path: Path) -> tuple[int, int]:
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    created = updated = 0
    for case in cases:
        case_id = str(case["id"])
        version = _semver(str(case.get("version", "1.0.0")))
        artifact = db.scalar(select(Artifact).where(Artifact.id == case_id))
        fields = {
            "kind": "case",
            "provider": "hub-case",
            "provider_id": case_id,
            "title": case["title"],
            "summary": case.get("summary", ""),
            "category": case.get("category"),
            "audience": case.get("audience"),
            "duration": case.get("duration"),
            "output": case.get("output"),
            "tags": case.get("tags", []),
            # Existing demo cases are synthetic and intentionally public.
            "visibility": "public" if case.get("kind") == "示范案例" else "organization",
            "status": "published",
            "current_version": version,
            "source_url": case.get("learningPath"),
            "metadata_json": case,
        }
        if artifact is None:
            artifact = Artifact(id=case_id, **fields)
            db.add(artifact)
            created += 1
        else:
            for key, value in fields.items():
                setattr(artifact, key, value)
            updated += 1
        existing = db.scalar(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == case_id, ArtifactVersion.version == version
            )
        )
        if existing is None:
            db.add(
                ArtifactVersion(
                    artifact_id=case_id,
                    version=version,
                    payload=case,
                    content_sha256=_sha256(case),
                )
            )
    db.commit()
    return created, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Import WorkBuddy demo cases into Hub API")
    parser.add_argument("--registry", type=Path, default=get_settings().registry_path)
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        created, updated = import_cases(db, args.registry.resolve())
    print(f"Imported cases: created={created} updated={updated}")


if __name__ == "__main__":
    main()
