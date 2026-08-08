from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWK

from .tracing import inject_trace_context


class IdentityError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ActorIdentity:
    subject: str
    auth_mode: str
    groups: frozenset[str] = frozenset()
    departments: frozenset[str] = frozenset()


def _string_values(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset({value}) if value else frozenset()
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item) for item in value if isinstance(item, (str, int)) and str(item))


class OIDCVerifier:
    """Validate organization access tokens against a pinned OIDC issuer."""

    def __init__(
        self,
        issuer_url: str | None,
        audience: str | None,
        *,
        groups_claim: str = "groups",
        department_claim: str = "departments",
        department_group_prefix: str = "department:",
        cache_seconds: int = 300,
        clock_skew_seconds: int = 30,
        allow_insecure_http: bool = False,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/") if issuer_url else None
        self.audience = audience
        self.groups_claim = groups_claim
        self.department_claim = department_claim
        self.department_group_prefix = department_group_prefix
        self.cache_seconds = cache_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.allow_insecure_http = allow_insecure_http
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            event_hooks={"request": [inject_trace_context]},
        )
        self._keys: dict[str, PyJWK] = {}
        self._expires_at = 0.0
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self.issuer_url and self.audience)

    def close(self) -> None:
        self._client.close()

    def _validate_https_endpoint(self, url: str, *, same_host: str | None = None) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ({"https", "http"} if self.allow_insecure_http else {"https"}):
            raise IdentityError("oidc_endpoint_not_https")
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise IdentityError("oidc_endpoint_invalid")
        if same_host and parsed.hostname.lower() != same_host.lower():
            raise IdentityError("oidc_jwks_host_mismatch")

    def _json(self, url: str) -> dict[str, Any]:
        try:
            response = self._client.get(url, timeout=self.timeout_seconds)
        except httpx.HTTPError as exc:
            raise IdentityError("oidc_provider_unavailable") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise IdentityError("oidc_provider_unavailable")
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdentityError("oidc_provider_invalid_response") from exc
        if not isinstance(payload, dict):
            raise IdentityError("oidc_provider_invalid_response")
        return payload

    def _refresh_keys(self) -> None:
        if not self.configured:
            raise IdentityError("oidc_not_configured")
        self._validate_https_endpoint(self.issuer_url or "")
        issuer_host = urlsplit(self.issuer_url or "").hostname
        discovery = self._json(f"{self.issuer_url}/.well-known/openid-configuration")
        if discovery.get("issuer") != self.issuer_url:
            raise IdentityError("oidc_issuer_mismatch")
        jwks_uri = str(discovery.get("jwks_uri") or "")
        self._validate_https_endpoint(jwks_uri, same_host=issuer_host)
        jwks = self._json(jwks_uri)
        raw_keys = jwks.get("keys")
        if not isinstance(raw_keys, list):
            raise IdentityError("oidc_jwks_invalid")
        keys: dict[str, PyJWK] = {}
        for raw in raw_keys:
            if not isinstance(raw, dict) or raw.get("alg") not in (None, "RS256"):
                continue
            kid = str(raw.get("kid") or "")
            if not kid:
                continue
            try:
                keys[kid] = PyJWK.from_dict(raw, algorithm="RS256")
            except (ValueError, TypeError):
                continue
        if not keys:
            raise IdentityError("oidc_jwks_invalid")
        self._keys = keys
        self._expires_at = monotonic() + self.cache_seconds

    def _key(self, kid: str) -> PyJWK:
        with self._lock:
            if monotonic() >= self._expires_at:
                self._refresh_keys()
            key = self._keys.get(kid)
            if key is None:
                self._refresh_keys()
                key = self._keys.get(kid)
            if key is None:
                raise IdentityError("oidc_signing_key_not_found")
            return key

    def verify(self, token: str) -> ActorIdentity:
        if not self.configured:
            raise IdentityError("oidc_not_configured")
        if not token or len(token) > 16_384:
            raise IdentityError("oidc_token_invalid")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise IdentityError("oidc_token_invalid") from exc
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise IdentityError("oidc_token_algorithm_rejected")
        try:
            claims = jwt.decode(
                token,
                key=self._key(header["kid"]).key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer_url,
                leeway=self.clock_skew_seconds,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise IdentityError("oidc_token_invalid") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 160:
            raise IdentityError("oidc_subject_invalid")
        groups = _string_values(claims.get(self.groups_claim))
        departments = set(_string_values(claims.get(self.department_claim)))
        if self.department_group_prefix:
            departments.update(
                group.removeprefix(self.department_group_prefix)
                for group in groups
                if group.startswith(self.department_group_prefix)
                and group != self.department_group_prefix
            )
        return ActorIdentity(
            subject=subject,
            auth_mode="oidc",
            groups=groups,
            departments=frozenset(departments),
        )
