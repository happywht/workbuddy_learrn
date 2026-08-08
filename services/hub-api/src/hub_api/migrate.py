from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .config import SERVICE_ROOT
from .db import Base, engine
from . import models  # noqa: F401


LEGACY_POC_TABLES = {"artifact", "artifact_version", "publication_preview", "audit_event"}


def main() -> None:
    runtime_root = Path.cwd() if (Path.cwd() / "alembic.ini").exists() else SERVICE_ROOT
    alembic = Config(str(runtime_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(runtime_root / "migrations"))
    existing = set(inspect(engine).get_table_names())
    if "alembic_version" not in existing and LEGACY_POC_TABLES.issubset(existing):
        preview_columns = {
            column["name"] for column in inspect(engine).get_columns("publication_preview")
        }
        # Adopt only the known create_all PoC schema, adding newly versioned
        # tables before stamping. Unknown partial schemas still fail normally.
        Base.metadata.create_all(bind=engine)
        if "scan_rules_version" in preview_columns:
            command.stamp(alembic, "head")
        elif "idempotency_key" in preview_columns:
            command.stamp(alembic, "0004_publication_idempotency_key")
            command.upgrade(alembic, "head")
        elif "result_json" in preview_columns:
            command.stamp(alembic, "0003_publication_result")
            command.upgrade(alembic, "head")
        else:
            command.stamp(alembic, "0002_collab_artifact_verify")
            command.upgrade(alembic, "head")
        return
    command.upgrade(alembic, "head")


if __name__ == "__main__":
    main()
