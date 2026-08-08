from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'hub.db'}"
    monkeypatch.setenv("HUB_DATABASE_URL", database_url)
    monkeypatch.setenv("HUB_SEED_DEMO_CASES", "false")
    from hub_api import config, db

    config.get_settings.cache_clear()
    db.settings = config.get_settings()
    db.engine = create_engine(database_url, connect_args={"check_same_thread": False})
    db.SessionLocal = sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)
    from hub_api.main import app

    db.init_db()
    fixture = Path(__file__).parents[3] / "workbuddy-hub" / "data" / "registry.json"
    from hub_api.seed import import_cases

    with db.SessionLocal() as session:
        import_cases(session, fixture.resolve())
    with TestClient(app) as test_client:
        yield test_client
    config.get_settings.cache_clear()


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_id_is_propagated_or_replaced(client: TestClient):
    propagated = client.get(
        "/health",
        headers={"X-Request-Id": "trace-123", "Origin": "http://127.0.0.1:4173"},
    )
    assert propagated.headers["X-Request-Id"] == "trace-123"
    assert "x-request-id" in propagated.headers["Access-Control-Expose-Headers"].lower()

    replaced = client.get("/health", headers={"X-Request-Id": "invalid request id"})
    assert replaced.headers["X-Request-Id"] != "invalid request id"
    assert len(replaced.headers["X-Request-Id"]) == 36


def test_metrics_use_route_templates(client: TestClient):
    response = client.get("/api/v1/artifacts/case-capacity")
    assert response.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "workbuddy_hub_http_requests_total" in metrics.text
    assert 'route="/api/v1/artifacts/{artifact_id:path}"' in metrics.text
    assert 'route="/api/v1/artifacts/case-capacity"' not in metrics.text
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_access_log_is_structured_and_omits_secrets(client: TestClient, caplog: pytest.LogCaptureFixture):
    header_sentinel = "opaque-header-marker"
    with caplog.at_level(logging.INFO, logger="hub_api.access"):
        response = client.get(
            "/health?token=query-secret",
            headers={"Authorization": f"Bearer {header_sentinel}", "X-Request-Id": "log-test"},
        )

    access_record = next(record for record in caplog.records if record.name == "hub_api.access")
    payload = json.loads(access_record.message)
    assert payload == {
        "duration_ms": payload["duration_ms"],
        "event": "http_request",
        "method": "GET",
        "request_id": "log-test",
        "route": "/health",
        "status": response.status_code,
    }
    assert header_sentinel not in access_record.message
    assert "query-secret" not in access_record.message


def test_mcp_initialize_list_and_catalog_search(client: TestClient):
    initialized = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "workbuddy-hub"
    tools = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["result"]["tools"]}
    assert {"registry.search", "collab.wait", "collab.send", "collab.cancel"} <= names
    searched = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "registry.search", "arguments": {"query": "资料"}},
        },
    )
    assert searched.status_code == 200
    result = searched.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["items"][0]["id"] == "case-capacity"


def test_mcp_enforces_identity_and_idempotency(client: TestClient):
    unauthenticated = client.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "status",
            "method": "tools/call",
            "params": {"name": "collab.status", "arguments": {"task_id": "collab_missing"}},
        },
    )
    assert unauthenticated.status_code == 200
    assert unauthenticated.json()["result"]["isError"] is True
    assert unauthenticated.json()["result"]["structuredContent"]["status_code"] == 401
    missing_key = client.post(
        "/api/v1/mcp",
        headers={"X-Actor-Id": "local-user"},
        json={
            "jsonrpc": "2.0",
            "id": "preview",
            "method": "tools/call",
            "params": {
                "name": "registry.publish_preview",
                "arguments": {"kind": "case", "requested_scope": "personal", "package": _package()},
            },
        },
    )
    assert missing_key.status_code == 200
    assert missing_key.json()["result"]["isError"] is True
    assert "missing_required_arguments:idempotency_key" in missing_key.json()["result"]["content"][0]["text"]
    preview = client.post(
        "/api/v1/mcp",
        headers={"X-Actor-Id": "local-user"},
        json={
            "jsonrpc": "2.0",
            "id": "preview-ok",
            "method": "tools/call",
            "params": {
                "name": "registry.publish_preview",
                "arguments": {
                    "kind": "case",
                    "requested_scope": "personal",
                    "package": _package(id="mcp-published-case"),
                    "idempotency_key": "mcp-preview-once",
                },
            },
        },
    )
    assert preview.json()["result"]["isError"] is False
    preview_id = preview.json()["result"]["structuredContent"]["preview_id"]
    publish_payload = {
        "jsonrpc": "2.0",
        "id": "publish-ok",
        "method": "tools/call",
        "params": {
            "name": "registry.publish",
            "arguments": {
                "preview_id": preview_id,
                "confirmed_scope": "personal",
                "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
                "idempotency_key": "mcp-publish-once",
            },
        },
    }
    published = client.post("/api/v1/mcp", headers={"X-Actor-Id": "local-user"}, json=publish_payload)
    repeated = client.post("/api/v1/mcp", headers={"X-Actor-Id": "local-user"}, json=publish_payload)
    assert published.json()["result"]["isError"] is False
    assert repeated.json()["result"]["structuredContent"] == published.json()["result"]["structuredContent"]
    notification = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notification.status_code == 204


def test_catalog_import_preserves_four_cases(client: TestClient):
    response = client.get("/api/v1/artifacts?kind=case")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert {item["id"] for item in payload["items"]} == {
        "case-contract-warning",
        "case-project-status",
        "case-capacity",
        "case-report-deck",
    }


def test_catalog_search_includes_tags(client: TestClient):
    response = client.get("/api/v1/artifacts?q=资料")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["case-capacity"]


def test_case_detail_keeps_original_payload(client: TestClient):
    response = client.get("/api/v1/artifacts/case-capacity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "项目资料交付检查"
    assert payload["metadata"]["id"] == "case-capacity"
    assert payload["versions"][0]["version"] == "1.0.0"


def test_missing_artifact_is_not_found(client: TestClient):
    response = client.get("/api/v1/artifacts/not-present")
    assert response.status_code == 404


def _package(kind: str = "case", **overrides):
    package = {
        "id": "local-published-case",
        "name": "Local Published Case",
        "version": "1.0.0",
        "kind": kind,
        "summary": "A synthetic case for publication contract tests.",
        "scope": "personal",
        "inputs": [],
        "outputs": [],
        "permissions": [],
        "human_review": ["Confirm the result before reuse."],
        "sanitization": {"status": "passed", "changes": []},
    }
    package.update(overrides)
    return package


def test_preview_requires_identity(client: TestClient):
    response = client.post(
        "/api/v1/publication-previews",
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert response.status_code == 401


def test_non_local_auth_mode_rejects_spoofable_actor_header(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from hub_api import main

    monkeypatch.setattr(main.settings, "auth_mode", "oidc")
    response = client.post(
        "/api/v1/publication-previews",
        headers={"X-Actor-Id": "spoofed"},
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "identity_required"


def test_oidc_identity_controls_owner_department_and_organization_visibility(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from hub_api import db, main
    from hub_api.identity import ActorIdentity, IdentityError
    from hub_api.models import Artifact

    class StubOIDCVerifier:
        def verify(self, token: str) -> ActorIdentity:
            if token != "valid-token":
                raise IdentityError("oidc_token_invalid")
            return ActorIdentity(
                subject="oidc-user",
                auth_mode="oidc",
                groups=frozenset({"department:design"}),
                departments=frozenset({"design"}),
            )

        def close(self):
            pass

    monkeypatch.setattr(main.settings, "auth_mode", "oidc")
    monkeypatch.setattr(main, "oidc_verifier", StubOIDCVerifier())
    with db.SessionLocal() as session:
        session.add_all(
            [
                Artifact(
                    id="private-owner",
                    title="Owner only",
                    summary="owner",
                    visibility="personal",
                    owner_id="oidc-user",
                ),
                Artifact(
                    id="private-other",
                    title="Other owner",
                    summary="other",
                    visibility="personal",
                    owner_id="other-user",
                ),
                Artifact(
                    id="department-design",
                    title="Design department",
                    summary="design",
                    visibility="department",
                    department_id="design",
                ),
                Artifact(
                    id="department-finance",
                    title="Finance department",
                    summary="finance",
                    visibility="department",
                    department_id="finance",
                ),
                Artifact(
                    id="organization-wide",
                    title="Organization",
                    summary="organization",
                    visibility="organization",
                ),
            ]
        )
        session.commit()

    spoofed = client.get("/api/v1/artifacts", headers={"X-Actor-Id": "oidc-user"})
    assert spoofed.status_code == 200
    assert all(item["visibility"] == "public" for item in spoofed.json()["items"])

    headers = {
        "Authorization": "Bearer valid-token",
        "X-Actor-Id": "spoofed-user",
        "Idempotency-Key": "oidc-preview-1",
    }
    visible = client.get("/api/v1/artifacts", headers=headers).json()["items"]
    visible_ids = {item["id"] for item in visible}
    assert {"private-owner", "department-design", "organization-wide"} <= visible_ids
    assert {"private-other", "department-finance"}.isdisjoint(visible_ids)

    preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "department",
            "target_department_id": "design",
            "package": _package(id="oidc-department-case"),
        },
    )
    assert preview.status_code == 200
    assert preview.json()["allowed_scopes"] == ["personal", "department", "organization"]
    retry = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "department",
            "target_department_id": "design",
            "package": _package(id="oidc-department-case"),
        },
    )
    assert retry.status_code == 200
    assert retry.json()["preview_id"] == preview.json()["preview_id"]
    with db.SessionLocal() as session:
        stored = session.get(main.PublicationPreview, preview.json()["preview_id"])
        assert stored.actor_id == "oidc-user"


def test_oidc_rejects_invalid_token_and_unauthorized_department_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from hub_api import main
    from hub_api.identity import ActorIdentity, IdentityError

    class StubOIDCVerifier:
        def verify(self, token: str) -> ActorIdentity:
            if token == "valid-token":
                return ActorIdentity(
                    subject="oidc-user",
                    auth_mode="oidc",
                    departments=frozenset({"design"}),
                )
            raise IdentityError("oidc_token_invalid")

        def close(self):
            pass

    monkeypatch.setattr(main.settings, "auth_mode", "oidc")
    monkeypatch.setattr(main, "oidc_verifier", StubOIDCVerifier())
    invalid = client.post(
        "/api/v1/publication-previews",
        headers={"Authorization": "Bearer invalid-token"},
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "oidc_token_invalid"

    missing_key = client.post(
        "/api/v1/publication-previews",
        headers={"Authorization": "Bearer valid-token"},
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["detail"] == "idempotency_key_required"

    headers = {"Authorization": "Bearer valid-token", "Idempotency-Key": "oidc-preview-2"}
    preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "department",
            "target_department_id": "finance",
            "package": _package(id="unauthorized-department-case"),
        },
    )
    assert preview.status_code == 200
    assert "department" not in preview.json()["allowed_scopes"]
    assert "target_department_not_authorized" in preview.json()["validation"]["warnings"]
    published = client.post(
        "/api/v1/publications",
        headers=headers,
        json={
            "preview_id": preview.json()["preview_id"],
            "confirmed_scope": "department",
            "target_department_id": "finance",
            "confirmation": {
                "confirmed": True,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )
    assert published.status_code == 403
    assert published.json()["detail"] == "scope_denied"

    missing_target = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "department",
            "package": _package(id="missing-department-case"),
        },
    )
    assert missing_target.status_code == 422
    assert missing_target.json()["detail"] == "target_department_required"

    unexpected_target = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "organization",
            "target_department_id": "design",
            "package": _package(id="unexpected-department-case"),
        },
    )
    assert unexpected_target.status_code == 422
    assert unexpected_target.json()["detail"] == "target_department_not_allowed"


def test_preview_blocks_credentials(client: TestClient):
    response = client.post(
        "/api/v1/publication-previews",
        headers={"X-Actor-Id": "local-user"},
        json={
            "kind": "case",
            "requested_scope": "personal",
            "package": _package(prompt="password: do-not-publish"),
        },
    )
    assert response.status_code == 200
    assert response.json()["validation"]["status"] == "blocked"
    assert response.json()["validation"]["rules_version"] != "legacy-unknown"


def test_case_publish_requires_preview_and_confirmation(client: TestClient):
    headers = {"X-Actor-Id": "local-user"}
    preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert preview.status_code == 200
    preview_id = preview.json()["preview_id"]
    published = client.post(
        "/api/v1/publications",
        headers=headers,
        json={
            "preview_id": preview_id,
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert published.status_code == 200
    assert published.json()["artifact_id"] == "local-published-case"
    detail = client.get("/api/v1/artifacts/local-published-case", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["visibility"] == "personal"
    retry = client.post(
        "/api/v1/publications",
        headers=headers,
        json={
            "preview_id": preview_id,
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert retry.status_code == 200
    assert retry.json() == published.json()
    from hub_api import db
    from hub_api.models import ArtifactVersion, AuditEvent
    with db.SessionLocal() as session:
        assert session.query(ArtifactVersion).filter_by(artifact_id="local-published-case").count() == 1
        assert session.query(AuditEvent).filter_by(event_type="publication_created").count() == 1


def test_skill_publish_retry_reuses_persisted_result(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from hub_api import main

    class StubSkillHub:
        configured = True
        calls = 0

        def publish(self, package, actor_id, grant, publish_path, *, idempotency_key):
            self.calls += 1
            assert (actor_id, grant, publish_path, idempotency_key) == (
                "local-user",
                "grant-1",
                "/trusted",
                "preview-idempotency",
            )
            return {"slug": "team/excel", "version": "1.0.0", "status": "published"}

        def close(self):
            pass

    provider = StubSkillHub()
    monkeypatch.setattr(main, "skillhub_client", provider)
    monkeypatch.setattr(main.settings, "skillhub_publish_path", "/trusted")
    preview = client.post(
        "/api/v1/publication-previews",
        headers={"X-Actor-Id": "local-user"},
        json={
            "kind": "skill",
            "requested_scope": "personal",
            "package": _package("skill", id="skill-idempotent"),
        },
    )
    assert preview.status_code == 200
    from hub_api import db
    from hub_api.models import PublicationPreview
    with db.SessionLocal() as session:
        stored = session.get(PublicationPreview, preview.json()["preview_id"])
        stored.id = "preview-idempotency"
        session.commit()
    headers = {
        "X-Actor-Id": "local-user",
        "X-WorkBuddy-Publication-Grant": "grant-1",
    }
    body = {
        "preview_id": "preview-idempotency",
        "confirmed_scope": "personal",
        "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
    }
    first = client.post("/api/v1/publications", headers=headers, json=body)
    second = client.post("/api/v1/publications", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert provider.calls == 1


def test_version_report_rate_and_rollback_are_audited(client: TestClient):
    from hub_api import db
    from hub_api.models import ArtifactVersion, AuditEvent

    headers = {"X-Actor-Id": "local-user"}
    first_preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={"kind": "case", "requested_scope": "personal", "package": _package()},
    )
    assert first_preview.status_code == 200
    published = client.post(
        "/api/v1/publications",
        headers=headers,
        json={
            "preview_id": first_preview.json()["preview_id"],
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert published.status_code == 200

    update_preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={
            "kind": "case",
            "requested_scope": "personal",
            "package": _package(version="1.1.0", summary="Updated package"),
        },
    )
    assert update_preview.status_code == 200
    updated = client.post(
        "/api/v1/artifacts/local-published-case/versions",
        headers={**headers, "Idempotency-Key": "version-once"},
        json={
            "preview_id": update_preview.json()["preview_id"],
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == "1.1.0"
    repeated_update = client.post(
        "/api/v1/artifacts/local-published-case/versions",
        headers={**headers, "Idempotency-Key": "version-once"},
        json={
            "preview_id": update_preview.json()["preview_id"],
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert repeated_update.status_code == 200
    assert repeated_update.json() == updated.json()

    report_headers = {**headers, "Idempotency-Key": "report-once"}
    report = client.post(
        "/api/v1/artifacts/local-published-case/reports",
        headers=report_headers,
        json={"category": "unsafe", "reason": "Synthetic report for governance test."},
    )
    assert report.status_code == 200
    assert report.json()["status"] == "reported"
    repeated_report = client.post(
        "/api/v1/artifacts/local-published-case/reports",
        headers=report_headers,
        json={"category": "unsafe", "reason": "Same idempotent report."},
    )
    assert repeated_report.status_code == 200
    assert repeated_report.json() == report.json()
    assert client.get("/api/v1/artifacts/local-published-case", headers=headers).status_code == 404

    rollback = client.post(
        "/api/v1/artifacts/local-published-case/rollback",
        headers={**headers, "Idempotency-Key": "rollback-once"},
        json={
            "version": "1.0.0",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert rollback.status_code == 200
    assert rollback.json()["version"] == "1.0.0"
    detail = client.get("/api/v1/artifacts/local-published-case", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["current_version"] == "1.0.0"

    rating_headers = {**headers, "Idempotency-Key": "rating-once"}
    rating = client.post(
        "/api/v1/artifacts/local-published-case/ratings",
        headers=rating_headers,
        json={"score": 5, "comment": "Useful."},
    )
    assert rating.status_code == 200
    repeated_rating = client.post(
        "/api/v1/artifacts/local-published-case/ratings",
        headers=rating_headers,
        json={"score": 1},
    )
    assert repeated_rating.status_code == 200
    assert repeated_rating.json() == rating.json()
    with db.SessionLocal() as session:
        assert session.query(ArtifactVersion).filter_by(artifact_id="local-published-case").count() == 2
        assert session.query(AuditEvent).filter_by(event_type="artifact_version_created").count() == 1
        assert session.query(AuditEvent).filter_by(event_type="artifact_reported").count() == 1
        assert session.query(AuditEvent).filter_by(event_type="artifact_rolled_back").count() == 1
        assert session.query(AuditEvent).filter_by(event_type="artifact_rated").count() == 1


def test_skill_publish_is_explicitly_unavailable_without_skillhub(client: TestClient):
    headers = {"X-Actor-Id": "local-user"}
    preview = client.post(
        "/api/v1/publication-previews",
        headers=headers,
        json={"kind": "skill", "requested_scope": "personal", "package": _package("skill")},
    )
    assert preview.status_code == 200
    response = client.post(
        "/api/v1/publications",
        headers=headers,
        json={
            "preview_id": preview.json()["preview_id"],
            "confirmed_scope": "personal",
            "confirmation": {"confirmed": True, "confirmed_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "skillhub_adapter_not_configured"


def test_skill_search_reports_unconfigured_provider(client: TestClient):
    response = client.get("/api/v1/skills", params={"q": "excel"})
    assert response.status_code == 503
    assert response.json()["detail"] == "skillhub_adapter_not_configured"


def test_collaboration_requires_identity_and_reports_unconfigured_provider(client: TestClient):
    assert client.get("/api/v1/collaboration/teams").status_code == 401
    response = client.get("/api/v1/collaboration/teams", headers={"X-Actor-Id": "local-user"})
    assert response.status_code == 503
    assert response.json()["detail"] == "agentteams_controller_not_configured"


def test_unified_catalog_includes_skillhub_projection(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from hub_api import main
    from hub_api.integrations.skillhub import SkillRecord

    class StubSkillHub:
        def search(self, query: str, limit: int = 20, actor_id: str | None = None):
            assert query == "excel"
            return [SkillRecord("team/excel", "Excel", "Workbook checks", "1.2.0", tags=["spreadsheet"])]

        def close(self):
            pass

    monkeypatch.setattr(main, "skillhub_client", StubSkillHub())
    response = client.get("/api/v1/artifacts", params={"q": "excel"})
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "skillhub:team/excel"
    assert response.json()["items"][0]["current_version"] == "1.2.0"


def test_install_plan_pins_version_and_requires_execution_confirmation(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from hub_api import main

    class StubSkillHub:
        def get(self, slug: str, actor_id: str | None = None):
            assert slug == "team/excel"
            return {"latestVersion": "1.2.0", "permissions": ["filesystem:read"]}

        def resolve(self, slug: str, version: str, actor_id: str | None = None):
            assert (slug, version) == ("team/excel", "latest")
            return {"match": {"version": "1.2.0"}, "latestVersion": {"version": "1.2.0"}}

        def download_location(self, slug: str, version: str, actor_id: str | None = None):
            assert (slug, version) == ("team/excel", "1.2.0")
            return "https://objects.test/team-excel.zip"

        def download_sha256(self, slug: str, version: str, actor_id: str | None = None, *, max_bytes: int, download_url: str | None = None):
            assert (slug, version) == ("team/excel", "1.2.0")
            assert max_bytes > 0
            assert download_url == "https://objects.test/team-excel.zip"
            return "a" * 64

        def close(self):
            pass

    monkeypatch.setattr(main, "skillhub_client", StubSkillHub())
    response = client.post(
        "/api/v1/artifacts/skillhub:team/excel/install-plans",
        json={"slug": "team/excel", "target_agent": "workbuddy"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.2.0"
    assert payload["sha256"] == "a" * 64
    assert payload["requires_execution_confirmation"] is True


def test_collaboration_task_lifecycle_is_idempotent_and_audited(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from hub_api import main
    from hub_api.integrations.agentteams import MatrixMedia

    artifact_content = b"%PDF-1.7\nverified\n"
    artifact_sha256 = hashlib.sha256(artifact_content).hexdigest()

    class StubController:
        calls = 0

        def team(self, actor_id, team_id):
            self.calls += 1
            assert (actor_id, team_id) == ("local-user", "team-a")
            return {
                "name": "team-a",
                "phase": "Active",
                "admin": {"name": "hub", "matrixUserId": "@hub:local"},
                "workerMembers": [{"name": "leader", "role": "team_leader"}],
                "leaderName": "leader",
                "leaderDMRoomID": "!room:local",
                "leaderReady": True,
                "readyWorkers": 0,
                "totalWorkers": 0,
            }

        def close(self):
            pass

    class StubMatrix:
        configured = True

        def __init__(self):
            self.sync_calls = 0
            self.sync_timeouts = []
            self.sent = []
            self.download_calls = 0

        def whoami(self):
            return "@hub:local"

        def joined_rooms(self):
            return {"!room:local"}

        def sync(self, room_id, since=None, timeout_ms=0):
            self.sync_calls += 1
            self.sync_timeouts.append(timeout_ms)
            if self.sync_calls == 1:
                return {"events": [], "next_cursor": "sync-0"}
            return {
                "events": [
                    {
                        "event_id": "$status-1",
                        "type": "m.room.message",
                        "content": {
                            "msgtype": "m.text",
                            "body": f"[WBH:{task_id}] started",
                            "com.workbuddy.hub": {
                                "kind": "task.status",
                                "task_id": task_id,
                                "status": "running",
                            },
                        },
                    },
                    {
                        "event_id": "$artifact-1",
                        "type": "m.room.message",
                        "sender": "@worker:local",
                        "origin_server_ts": 1786168800000,
                        "content": {
                            "msgtype": "m.file",
                            "body": "delivery-report.pdf",
                            "url": "mxc://local/report-1",
                            "info": {"mimetype": "application/pdf", "size": len(artifact_content)},
                            "com.workbuddy.hub": {
                                "kind": "task.artifact",
                                "task_id": task_id,
                                "purpose": "result",
                                "sha256": artifact_sha256,
                            },
                        },
                    },
                ],
                "next_cursor": "sync-1",
            }

        def download_media(self, mxc_uri, max_bytes):
            self.download_calls += 1
            assert mxc_uri == "mxc://local/report-1"
            assert max_bytes >= len(artifact_content)
            return MatrixMedia(content=artifact_content, content_type="application/pdf")

        def send_text(self, room_id, transaction_id, payload):
            self.sent.append((room_id, transaction_id, payload))
            return {"event_id": f"${transaction_id}"}

        def close(self):
            pass

    controller = StubController()
    matrix = StubMatrix()
    monkeypatch.setattr(main, "agentteams_controller_client", controller)
    monkeypatch.setattr(main, "agentteams_matrix_client", matrix)
    monkeypatch.setattr(main.settings, "agentteams_matrix_media_server_allowlist", "other-server")
    headers = {"X-Actor-Id": "local-user", "Idempotency-Key": "task-once"}
    body = {"team_id": "team-a", "goal": "Check the delivery package", "output_contract": {"type": "report"}}
    first = client.post("/api/v1/collaboration/tasks", headers=headers, json=body)
    second = client.post("/api/v1/collaboration/tasks", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]
    assert controller.calls == 1
    task_id = first.json()["task_id"]
    assert first.json()["external_task_id"] == f"${task_id}"
    assert matrix.sent[0][0] == "!room:local"
    assert matrix.sent[0][1] == task_id
    assert matrix.sent[0][2]["com.workbuddy.hub"]["kind"] == "task.request"

    status = client.get(f"/api/v1/collaboration/tasks/{task_id}", headers={"X-Actor-Id": "local-user"})
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    events = client.get(f"/api/v1/collaboration/tasks/{task_id}/events", headers={"X-Actor-Id": "local-user"})
    assert events.status_code == 200
    assert {item["event_type"] for item in events.json()["events"]} >= {"task_dispatched", "status_changed"}
    assert events.json()["artifacts"][0]["mxc_uri"] == "mxc://local/report-1"
    assert events.json()["artifacts"][0]["content_verified"] is False
    repeated_events = client.get(f"/api/v1/collaboration/tasks/{task_id}/events", headers={"X-Actor-Id": "local-user"})
    assert [item["event_type"] for item in repeated_events.json()["events"]].count("status_changed") == 1
    wait = client.get(
        f"/api/v1/collaboration/tasks/{task_id}/wait",
        headers={"X-Actor-Id": "local-user"},
        params={"cursor": repeated_events.json()["next_cursor"], "timeout_seconds": 1},
    )
    assert wait.status_code == 200
    assert wait.json()["timed_out"] is True
    assert wait.json()["sync"] == {"status": "ok", "error": None}
    assert matrix.sync_timeouts[-1] == 1000
    artifacts = client.get(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts",
        headers={"X-Actor-Id": "local-user"},
    )
    assert artifacts.status_code == 200
    assert [item["artifact_id"] for item in artifacts.json()["artifacts"]] == ["$artifact-1"]
    assert artifacts.json()["sync"] == {"status": "ok", "error": None}
    missing_key = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts/$artifact-1/verify",
        headers={"X-Actor-Id": "local-user"},
    )
    assert missing_key.status_code == 422
    verify_headers = {"X-Actor-Id": "local-user", "Idempotency-Key": "verify-artifact-once"}
    denied = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts/$artifact-1/verify",
        headers=verify_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "matrix_media_server_not_allowed"
    denied_state = client.get(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts",
        headers={"X-Actor-Id": "local-user"},
    )
    assert denied_state.json()["artifacts"][0]["verification_status"] == "failed"
    assert denied_state.json()["artifacts"][0]["verification_error"] == "matrix_media_server_not_allowed"
    monkeypatch.setattr(main.settings, "agentteams_matrix_media_server_allowlist", "local")
    verified = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts/$artifact-1/verify",
        headers=verify_headers,
    )
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    assert verified.json()["content_verified"] is True
    assert verified.json()["safe_to_execute"] is False
    assert verified.json()["actual_sha256"] == artifact_sha256
    repeated_verify = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts/$artifact-1/verify",
        headers=verify_headers,
    )
    assert repeated_verify.status_code == 200
    assert matrix.download_calls == 1
    verified_artifacts = client.get(
        f"/api/v1/collaboration/tasks/{task_id}/artifacts",
        headers={"X-Actor-Id": "local-user"},
    )
    assert verified_artifacts.json()["artifacts"][0]["verification_status"] == "verified"
    message = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/messages",
        headers={"X-Actor-Id": "local-user", "Idempotency-Key": "message-once"},
        json={"content": "Please continue"},
    )
    assert message.status_code == 200
    assert matrix.sent[-1][2]["com.workbuddy.hub"]["kind"] == "task.message"
    sent_count = len(matrix.sent)
    repeated_message = client.post(
        f"/api/v1/collaboration/tasks/{task_id}/messages",
        headers={"X-Actor-Id": "local-user", "Idempotency-Key": "message-once"},
        json={"content": "Please continue"},
    )
    assert repeated_message.status_code == 200
    assert len(matrix.sent) == sent_count
    cancel_headers = {"X-Actor-Id": "local-user", "Idempotency-Key": "cancel-once"}
    cancelled = client.post(f"/api/v1/collaboration/tasks/{task_id}/cancel", headers=cancel_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"
    assert matrix.sent[-1][2]["com.workbuddy.hub"]["kind"] == "task.cancel_requested"
    cancel_sent_count = len(matrix.sent)
    repeated_cancel = client.post(f"/api/v1/collaboration/tasks/{task_id}/cancel", headers=cancel_headers)
    assert repeated_cancel.status_code == 200
    assert repeated_cancel.json() == cancelled.json()
    assert len(matrix.sent) == cancel_sent_count
