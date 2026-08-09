from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from sqlalchemy import create_engine, inspect

from hub_api.db import Base
from hub_api.models import Artifact, ArtifactVersion, AuditEvent, PublicationPreview


EXPECTED_TABLES = {
    "alembic_version",
    "artifact",
    "artifact_version",
    "audit_event",
    "collaboration_event",
    "collaboration_artifact_verification",
    "collaboration_task",
    "publication_preview",
    "agent",
    "marketplace_task",
    "marketplace_task_event",
}


def _run_migrate(database: Path) -> None:
    env = {**os.environ, "HUB_DATABASE_URL": f"sqlite:///{database.as_posix()}"}
    subprocess.run([sys.executable, "-m", "hub_api.migrate"], check=True, env=env)


def _upgrade_to(database: Path, revision: str) -> None:
    env = {**os.environ, "HUB_DATABASE_URL": f"sqlite:///{database.as_posix()}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=True,
        env=env,
        cwd=Path(__file__).parents[1],
    )


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_clean_database_upgrades_to_head(tmp_path: Path):
    database = tmp_path / "clean.db"
    _run_migrate(database)
    assert EXPECTED_TABLES <= _tables(database)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publication_preview)")}
    assert {"result_json", "idempotency_key", "scan_rules_version"} <= columns


def test_legacy_create_all_database_is_adopted(tmp_path: Path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(
        engine,
        tables=[Artifact.__table__, ArtifactVersion.__table__, PublicationPreview.__table__, AuditEvent.__table__],
    )
    assert "alembic_version" not in inspect(engine).get_table_names()
    _run_migrate(database)
    assert EXPECTED_TABLES <= _tables(database)


def test_versioned_0001_database_upgrades_without_losing_tasks(tmp_path: Path):
    database = tmp_path / "versioned.db"
    _upgrade_to(database, "0001_initial")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO collaboration_task (
                id, actor_id, team_id, goal, budget, output_contract, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "collab_00000000000000000000000000000000",
                "migration-user",
                "migration-team",
                "Preserve this task",
                "{}",
                "{}",
                "queued",
                "2026-08-08 00:00:00",
                "2026-08-08 00:00:00",
            ),
        )
    _run_migrate(database)
    assert "collaboration_artifact_verification" in _tables(database)
    with sqlite3.connect(database) as connection:
        preserved = connection.execute(
            "SELECT goal FROM collaboration_task WHERE actor_id = 'migration-user'"
        ).fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publication_preview)")}
    assert preserved == ("Preserve this task",)
    assert {"result_json", "idempotency_key", "scan_rules_version"} <= columns
