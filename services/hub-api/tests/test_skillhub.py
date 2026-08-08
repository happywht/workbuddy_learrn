from __future__ import annotations

import hashlib

import httpx

from hub_api.integrations.skillhub import SkillHubClient, SkillHubError


def test_skillhub_search_maps_clawhub_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/search"
        assert request.url.params["q"] == "excel"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "slug": "team--excel-check",
                        "displayName": "Excel Check",
                        "summary": "Checks a workbook.",
                        "version": "1.2.0",
                        "score": 1.5,
                        "updatedAt": 123,
                    }
                ]
            },
        )

    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.search("excel")
    assert result[0].slug == "team--excel-check"
    assert result[0].version == "1.2.0"
    client.close()


def test_skillhub_not_configured_is_explicit():
    client = SkillHubClient(None)
    try:
        client.search("anything")
    except SkillHubError as exc:
        assert str(exc) == "skillhub_adapter_not_configured"
    else:
        raise AssertionError("expected unconfigured adapter error")
    client.close()


def test_skillhub_http_failure_maps_to_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=transport))
    try:
        client.search("timeout")
    except SkillHubError as exc:
        assert exc.code == "skillhub_unavailable"
        assert exc.provider_status == 503
    else:
        raise AssertionError("expected provider failure")
    client.close()


def test_skillhub_auth_failure_is_distinguishable():
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=transport))
    try:
        client.search("private")
    except SkillHubError as exc:
        assert exc.code == "skillhub_auth_failed"
        assert exc.provider_status == 403
    else:
        raise AssertionError("expected auth failure")
    client.close()


def test_skillhub_detail_resolve_and_download_match_pinned_compat_routes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/skills/team--quarterly-report":
            return httpx.Response(
                200,
                json={
                    "skill": {"slug": "team--quarterly-report", "displayName": "Quarterly Report"},
                    "latestVersion": {"version": "1.0.0"},
                },
            )
        if request.url.path == "/api/v1/resolve":
            assert request.url.params["slug"] == "team--quarterly-report"
            return httpx.Response(
                200,
                json={"match": {"version": "1.0.0"}, "latestVersion": {"version": "1.0.0"}},
            )
        assert request.url.path == "/api/v1/download"
        assert request.url.params["slug"] == "team--quarterly-report"
        assert request.url.params["version"] == "1.0.0"
        return httpx.Response(
            302,
            headers={"location": "/api/v1/skills/team/quarterly-report/versions/1.0.0/download"},
        )

    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.get("team--quarterly-report")["latestVersion"]["version"] == "1.0.0"
    assert client.resolve("team--quarterly-report", "1.0.0")["match"]["version"] == "1.0.0"
    assert client.download_location("team--quarterly-report", "1.0.0") == (
        "http://skillhub.test/api/v1/skills/team/quarterly-report/versions/1.0.0/download"
    )
    client.close()


def test_skillhub_download_sha256_follows_redirect_and_does_not_forward_bearer():
    content = b"skill-package"
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/download":
            return httpx.Response(302, headers={"location": "/objects/package.zip"})
        assert request.url.path == "/objects/package.zip"
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, content=content, headers={"content-length": str(len(content))})

    client = SkillHubClient(
        "http://skillhub.test",
        token="provider-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.download_sha256("team--package", "1.0.0", max_bytes=1024) == hashlib.sha256(content).hexdigest()
    assert seen["authorization"] is None
    client.close()


def test_skillhub_download_sha256_rejects_declared_or_streamed_overflow():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/download":
            return httpx.Response(302, headers={"location": "/objects/package.zip"})
        return httpx.Response(200, content=b"123456", headers={"content-length": "6"})

    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        client.download_sha256("team--package", "1.0.0", max_bytes=5)
    except SkillHubError as exc:
        assert exc.code == "skillhub_download_too_large"
    else:
        raise AssertionError("expected package size limit")
    client.close()


def test_skillhub_download_sha256_maps_object_store_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/download":
            return httpx.Response(302, headers={"location": "/objects/package.zip"})
        return httpx.Response(503)

    client = SkillHubClient("http://skillhub.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        client.download_sha256("team--package", "1.0.0", max_bytes=1024)
    except SkillHubError as exc:
        assert exc.code == "skillhub_unavailable"
        assert exc.provider_status == 503
    else:
        raise AssertionError("expected object store failure")
    client.close()


def test_skillhub_rejects_noncanonical_slug_before_request():
    client = SkillHubClient("http://skillhub.test")
    try:
        client.get("team/quarterly report")
    except SkillHubError as exc:
        assert exc.code == "skillhub_invalid_canonical_slug"
    else:
        raise AssertionError("expected canonical slug validation error")
    client.close()


def test_skillhub_publish_requires_grant_and_never_uses_super_admin_semantics():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["actor"] = request.headers.get("x-actor-id")
        seen["grant"] = request.headers.get("x-workbuddy-publication-grant")
        seen["idempotency"] = request.headers.get("idempotency-key")
        return httpx.Response(201, json={"slug": "team/excel", "version": "1.0.0", "status": "published"})

    transport = httpx.MockTransport(handler)
    client = SkillHubClient("http://skillhub.test", token="scoped-token", client=httpx.Client(transport=transport))
    payload = client.publish(
        {"slug": "team/excel", "version": "1.0.0"},
        "user-1",
        "signed-grant",
        "/api/v1/trusted-publications",
        idempotency_key="preview_123",
    )
    assert payload["status"] == "published"
    assert seen == {
        "authorization": "Bearer scoped-token",
        "actor": "user-1",
        "grant": "signed-grant",
        "idempotency": "preview_123",
    }
    client.close()
