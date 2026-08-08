from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
from urllib.request import urlopen
from uuid import uuid4

from backup import TABLES, compose_command, container_env, psql_scalar, run, sha256_file


def load_manifest(backup_path: Path, manifest_path: Path | None) -> dict:
    path = manifest_path or backup_path.with_suffix(".manifest.json")
    payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    if payload.get("backup_file") != backup_path.name:
        raise RuntimeError("backup_manifest_filename_mismatch")
    if payload.get("sha256") != sha256_file(backup_path):
        raise RuntimeError("backup_manifest_sha256_mismatch")
    if payload.get("size") != backup_path.stat().st_size:
        raise RuntimeError("backup_manifest_size_mismatch")
    return payload


def wait_ready(base_url: str, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/ready", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ready":
                    return
        except Exception as exc:  # noqa: BLE001 - preserve the last readiness error
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"restore_api_not_ready: {last_error}")


def restore_drill(
    *,
    backup_path: Path,
    compose_file: Path,
    project: str,
    restore_port: int,
    env_file: Path | None = None,
    manifest_path: Path | None = None,
) -> dict:
    backup_path = backup_path.resolve(strict=True)
    compose_file = compose_file.resolve(strict=True)
    if env_file is not None:
        env_file = env_file.resolve(strict=True)
    manifest = load_manifest(backup_path, manifest_path)
    compose = compose_command(compose_file, project, env_file)
    postgres_id = run([*compose, "ps", "-q", "postgres"]).stdout.strip()
    if not postgres_id:
        raise RuntimeError("postgres_container_not_running")
    user = container_env(postgres_id, "POSTGRES_USER")
    live_database = container_env(postgres_id, "POSTGRES_DB")
    postgres_auth_value = container_env(postgres_id, "POSTGRES_PASSWORD")
    suffix = uuid4().hex[:8]
    restore_database = f"workbuddy_hub_restore_{suffix}"
    if not re.fullmatch(r"workbuddy_hub_restore_[a-f0-9]{8}", restore_database):
        raise RuntimeError("restore_database_name_invalid")
    if restore_database == live_database:
        raise RuntimeError("restore_database_must_not_be_live_database")
    container_backup = f"/tmp/{restore_database}.dump"
    api_container = f"{project}-restore-api-{suffix}"
    env_path: Path | None = None
    database_created = False
    api_started = False
    try:
        run(["docker", "cp", str(backup_path), f"{postgres_id}:{container_backup}"])
        run(["docker", "exec", postgres_id, "createdb", "--username", user, restore_database])
        database_created = True
        run(
            [
                "docker",
                "exec",
                postgres_id,
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--username",
                user,
                "--dbname",
                restore_database,
                container_backup,
            ]
        )
        restored_counts = {
            table: int(psql_scalar(postgres_id, user, restore_database, f'SELECT count(*) FROM "{table}";'))
            for table in TABLES
        }
        expected_counts = manifest.get("table_counts")
        if not isinstance(expected_counts, dict) or restored_counts != expected_counts:
            raise RuntimeError(
                f"restore_table_counts_mismatch: expected={expected_counts} actual={restored_counts}"
            )
        restored_migration = psql_scalar(
            postgres_id, user, restore_database, "SELECT version_num FROM alembic_version;"
        )
        if restored_migration != manifest.get("migration"):
            raise RuntimeError("restore_migration_mismatch")
        title = psql_scalar(
            postgres_id,
            user,
            restore_database,
            "SELECT title FROM artifact WHERE id = 'case-capacity';",
        )
        if title != "项目资料交付检查":
            raise RuntimeError(f"restore_compatibility_title_mismatch: {title!r}")
        image = run([*compose, "images", "-q", "hub-api"]).stdout.strip().splitlines()
        if not image:
            raise RuntimeError("hub_api_image_missing")
        postgres_inspect = json.loads(run(["docker", "inspect", postgres_id]).stdout)[0]
        networks = list(postgres_inspect.get("NetworkSettings", {}).get("Networks", {}))
        if len(networks) != 1:
            raise RuntimeError(f"postgres_network_ambiguous: {networks}")
        postgres_host = postgres_inspect.get("Name", "").lstrip("/")
        if not postgres_host:
            raise RuntimeError("postgres_container_name_missing")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".env"
        ) as env_handle:
            env_handle.write("HUB_ENV=local\n")
            env_handle.write("HUB_AUTH_MODE=local_header\n")
            env_handle.write("HUB_SEED_DEMO_CASES=false\n")
            env_handle.write("HUB_REGISTRY_PATH=/app/workbuddy-hub/data/registry.json\n")
            env_handle.write(
                "HUB_DATABASE_URL="
                f"postgresql+psycopg://{quote(user, safe='')}:{quote(postgres_auth_value, safe='')}"
                f"@{postgres_host}:5432/{restore_database}\n"
            )
            env_path = Path(env_handle.name)
        run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                api_container,
                "--network",
                networks[0],
                "--publish",
                f"127.0.0.1:{restore_port}:8000",
                "--env-file",
                str(env_path),
                image[0],
                "uvicorn",
                "hub_api.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
        )
        api_started = True
        base_url = f"http://127.0.0.1:{restore_port}"
        wait_ready(base_url)
        smoke = run([sys.executable, str(Path(__file__).with_name("smoke.py")), base_url])
        return {
            "status": "passed",
            "backup": str(backup_path),
            "database": restore_database,
            "migration": restored_migration,
            "table_counts": restored_counts,
            "compatibility_title": title,
            "smoke": json.loads(smoke.stdout.strip().splitlines()[0]),
        }
    finally:
        if api_started:
            subprocess.run(
                ["docker", "rm", "--force", api_container],
                capture_output=True,
                check=False,
            )
        if database_created:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    postgres_id,
                    "dropdb",
                    "--if-exists",
                    "--username",
                    user,
                    restore_database,
                ],
                capture_output=True,
                check=False,
            )
        subprocess.run(
            ["docker", "exec", postgres_id, "rm", "-f", container_backup],
            capture_output=True,
            check=False,
        )
        if env_path is not None:
            env_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Restore a Hub PostgreSQL backup into an isolated database and run smoke tests."
    )
    parser.add_argument("backup", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--compose-file", type=Path, default=directory / "compose.yaml")
    parser.add_argument("--project", default="workbuddy-hub-poc")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--restore-port", type=int, default=18101)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1024 <= args.restore_port <= 65535:
        raise ValueError("restore_port_out_of_range")
    result = restore_drill(
        backup_path=args.backup,
        manifest_path=args.manifest,
        compose_file=args.compose_file,
        project=args.project,
        env_file=args.env_file,
        restore_port=args.restore_port,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"restore_drill_failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
