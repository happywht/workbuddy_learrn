from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from ..tracing import inject_trace_context


CANONICAL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:--[a-z0-9]+(?:-[a-z0-9]+)*)?$")


class SkillHubError(RuntimeError):
    """A controlled failure from the SkillHub provider."""

    def __init__(self, code: str, provider_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.provider_status = provider_status


@dataclass(frozen=True)
class SkillRecord:
    slug: str
    display_name: str
    summary: str
    version: str | None = None
    score: float | None = None
    updated_at: int | None = None
    tags: list[str] | None = None
    raw: dict[str, Any] | None = None


class SkillHubClient:
    """Small read-first client for SkillHub's ClawHub-compatible API.

    The Hub service owns the stable contract; this client owns only provider
    URL, auth headers, response mapping and bounded timeout behavior.
    """

    def __init__(
        self,
        base_url: str | None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            event_hooks={"request": [inject_trace_context]},
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def close(self) -> None:
        self._client.close()

    def _headers(self, actor_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        if actor_id:
            headers["X-Actor-Id"] = actor_id
        return headers

    def _get(self, path: str, actor_id: str | None = None, **kwargs: Any) -> httpx.Response:
        if not self.base_url:
            raise SkillHubError("skillhub_adapter_not_configured")
        try:
            response = self._client.get(
                f"{self.base_url}{path}",
                headers=self._headers(actor_id),
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise SkillHubError("skillhub_unavailable") from exc
        if response.status_code >= 500:
            raise SkillHubError("skillhub_unavailable", response.status_code)
        if response.status_code in (401, 403):
            raise SkillHubError("skillhub_auth_failed", response.status_code)
        if response.status_code >= 400:
            raise SkillHubError("skillhub_request_rejected", response.status_code)
        return response

    def publish(
        self,
        package: dict[str, Any],
        actor_id: str,
        grant: str,
        publish_path: str | None,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Publish only through an explicitly configured Trusted Grant endpoint.

        A general administrator token is intentionally insufficient. The
        SkillHub integration must expose a grant-verifying endpoint before Hub
        enables this operation.
        """
        if not self.base_url:
            raise SkillHubError("skillhub_adapter_not_configured")
        if not publish_path:
            raise SkillHubError("skillhub_publication_grant_endpoint_not_configured")
        if not grant:
            raise SkillHubError("skillhub_publication_grant_required")
        try:
            response = self._client.post(
                f"{self.base_url}{publish_path}",
                headers={
                    **self._headers(actor_id),
                    "X-WorkBuddy-Publication-Grant": grant,
                    "Idempotency-Key": idempotency_key,
                },
                json={"package": package},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SkillHubError("skillhub_unavailable") from exc
        if response.status_code in (401, 403):
            raise SkillHubError("skillhub_auth_failed", response.status_code)
        if response.status_code >= 500:
            raise SkillHubError("skillhub_unavailable", response.status_code)
        if response.status_code >= 400:
            raise SkillHubError("skillhub_publication_rejected", response.status_code)
        return response.json()

    def search(self, query: str, limit: int = 20, actor_id: str | None = None) -> list[SkillRecord]:
        payload = self._get("/api/v1/search", actor_id=actor_id, params={"q": query, "page": 0, "limit": limit}).json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [
            SkillRecord(
                slug=str(item.get("slug", "")),
                display_name=str(item.get("displayName", item.get("display_name", ""))),
                summary=str(item.get("summary", "")),
                version=item.get("version"),
                score=item.get("score"),
                updated_at=item.get("updatedAt", item.get("updated_at")),
                tags=item.get("tags") if isinstance(item.get("tags"), list) else None,
                raw=item,
            )
            for item in results
            if item.get("slug")
        ]

    def get(self, slug: str, actor_id: str | None = None) -> dict[str, Any]:
        self._validate_slug(slug)
        encoded_slug = quote(slug, safe="")
        return self._get(f"/api/v1/skills/{encoded_slug}", actor_id=actor_id).json()

    def resolve(self, slug: str, version: str = "latest", actor_id: str | None = None) -> dict[str, Any]:
        self._validate_slug(slug)
        payload = self._get(
            "/api/v1/resolve",
            actor_id=actor_id,
            params={"slug": slug, "version": version},
        ).json()
        if not isinstance(payload, dict):
            raise SkillHubError("skillhub_resolve_invalid_response")
        return payload

    def download_location(self, slug: str, version: str = "latest", actor_id: str | None = None) -> str:
        self._validate_slug(slug)
        response = self._get(
            "/api/v1/download",
            actor_id=actor_id,
            params={"slug": slug, "version": version},
        )
        location = response.headers.get("location")
        if not location:
            raise SkillHubError("skillhub_download_location_missing")
        return urljoin(f"{self.base_url}/", location)

    def download_sha256(
        self,
        slug: str,
        version: str = "latest",
        actor_id: str | None = None,
        *,
        max_bytes: int,
        download_url: str | None = None,
    ) -> str:
        """Hash a pinned package without retaining it in Hub memory.

        SkillHub returns a redirect to a signed object-store URL. The Hub
        authorization header is used only for the SkillHub redirect request,
        never for the final object-store request.
        """
        if max_bytes < 1:
            raise SkillHubError("skillhub_hash_limit_invalid")
        location = download_url or self.download_location(slug, version, actor_id=actor_id)
        try:
            with self._client.stream(
                "GET",
                location,
                headers={"Accept-Encoding": "identity"},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as response:
                if response.status_code in (401, 403):
                    raise SkillHubError("skillhub_auth_failed", response.status_code)
                if response.status_code >= 500:
                    raise SkillHubError("skillhub_unavailable", response.status_code)
                if response.status_code < 200 or response.status_code >= 300:
                    raise SkillHubError("skillhub_download_rejected", response.status_code)
                declared_length = response.headers.get("content-length")
                if declared_length:
                    try:
                        declared = int(declared_length)
                    except ValueError as exc:
                        raise SkillHubError("skillhub_download_invalid_response") from exc
                    if declared < 0:
                        raise SkillHubError("skillhub_download_invalid_response")
                    if declared > max_bytes:
                        raise SkillHubError("skillhub_download_too_large", response.status_code)
                digest = hashlib.sha256()
                total = 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise SkillHubError("skillhub_download_too_large", response.status_code)
                    digest.update(chunk)
                if declared_length and int(declared_length) != total:
                    raise SkillHubError("skillhub_download_invalid_response", response.status_code)
                return digest.hexdigest()
        except SkillHubError:
            raise
        except httpx.HTTPError as exc:
            raise SkillHubError("skillhub_unavailable") from exc

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not CANONICAL_SLUG_RE.fullmatch(slug):
            raise SkillHubError("skillhub_invalid_canonical_slug")
