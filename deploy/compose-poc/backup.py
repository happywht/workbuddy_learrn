from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


TABLES = (
    "artifact",
    "artifact_version",
    "publication_preview",
    "audit_event",
    "collaboration_task",
    "collaboration_event",
    "collaboration_artifact_verification",
)


def run(command: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
    )


def compose_command(compose_file: Path, project: str, env_file: Path | None) -> list[str]:
    command = ["docker", "compose", "-f", str(compose_file), "-p", project]
    if env_file is not None:
        command.extend(["--env-file", str(env_file)])
    return command


def container_env(container_id: str, name: str) -> str:
    return run(["docker", "exec", container_id, "printenv", name]).stdout.strip()


def psql_scalar(container_id: str, user: str, database: str, sql: str) -> str:
    return run(
        [
            "docker",
            "exec",
            container_id,
            "psql",
            "--username",
            user,
            "--dbname",
            database,
            "--tuples-only",
            "--no-align",
            "--command",
            sql,
        ]
    ).stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(
    *,
    compose_file: Path,
    project: str,
    output_dir: Path,
    env_file: Path | None = None,
) -> dict:
    compose_file = compose_file.resolve(strict=True)
    if env_file is not None:
        env_file = env_file.resolve(strict=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    compose = compose_command(compose_file, project, env_file)
    container_id = run([*compose, "ps", "-q", "postgres"]).stdout.strip()
    if not container_id:
        raise RuntimeError("postgres_container_not_running")
    user = container_env(container_id, "POSTGRES_USER")
    database = container_env(container_id, "POSTGRES_DB")
    if not user or not database:
        raise RuntimeError("postgres_identity_missing")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_dir / f"workbuddy-hub-{timestamp}.dump"
    manifest_path = output_dir / f"workbuddy-hub-{timestamp}.manifest.json"
    container_backup = "/tmp/workbuddy-hub-backup.dump"
    try:
        run(
            [
                "docker",
                "exec",
                container_id,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--username",
                user,
                "--dbname",
                database,
                "--file",
                container_backup,
            ]
        )
        run(["docker", "cp", f"{container_id}:{container_backup}", str(backup_path)])
    finally:
        subprocess.run(
            ["docker", "exec", container_id, "rm", "-f", container_backup],
            capture_output=True,
            check=False,
        )
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise RuntimeError("backup_file_empty")
    counts = {
        table: int(psql_scalar(container_id, user, database, f'SELECT count(*) FROM "{table}";'))
        for table in TABLES
    }
    migration = psql_scalar(container_id, user, database, "SELECT version_num FROM alembic_version;")
    manifest = {
        "format": "postgresql-custom",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "database": database,
        "migration": migration,
        "backup_file": backup_path.name,
        "size": backup_path.stat().st_size,
        "sha256": sha256_file(backup_path),
        "table_counts": counts,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"backup": str(backup_path), "manifest": str(manifest_path), **manifest}


def parse_args() -> argparse.Namespace:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Create a verified WorkBuddy Hub PostgreSQL backup.")
    parser.add_argument("--compose-file", type=Path, default=directory / "compose.yaml")
    parser.add_argument("--project", default="workbuddy-hub-poc")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = create_backup(
        compose_file=args.compose_file,
        project=args.project,
        output_dir=args.output_dir,
        env_file=args.env_file,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"backup_failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
