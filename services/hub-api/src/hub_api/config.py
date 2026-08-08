from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _repository_root(service_root: Path) -> Path:
    return service_root.parents[1] if len(service_root.parents) > 1 else service_root


REPOSITORY_ROOT = _repository_root(SERVICE_ROOT)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(SERVICE_ROOT / ".env", SERVICE_ROOT / ".env.local"),
        env_prefix="HUB_",
        extra="ignore",
    )

    env: str = "local"
    auth_mode: str = "local_header"
    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_groups_claim: str = "groups"
    oidc_department_claim: str = "departments"
    oidc_department_group_prefix: str = "department:"
    oidc_jwks_cache_seconds: int = Field(default=300, ge=30, le=86_400)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    database_url: str = "sqlite:///./var/hub.db"
    registry_path: Path = REPOSITORY_ROOT / "workbuddy-hub" / "data" / "registry.json"
    seed_demo_cases: bool = True
    cors_origins: list[str] = ["http://127.0.0.1:4173", "http://localhost:4173"]
    otel_service_name: str = "workbuddy-hub-api"
    otel_exporter_otlp_traces_endpoint: str | None = None
    otel_trace_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    otel_export_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    skillhub_base_url: str | None = None
    skillhub_token: str | None = None
    skillhub_publish_path: str | None = None
    skillhub_timeout_seconds: float = 10.0
    skillhub_hash_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    agentteams_base_url: str | None = None
    agentteams_token: str | None = None
    agentteams_matrix_url: str | None = None
    agentteams_matrix_token: str | None = None
    agentteams_matrix_user_id: str | None = None
    agentteams_matrix_media_server_allowlist: str = ""
    agentteams_matrix_media_max_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024
    )
    agentteams_timeout_seconds: float = 10.0

    @field_validator("registry_path", mode="before")
    @classmethod
    def resolve_registry_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (SERVICE_ROOT / path).resolve()

    @field_validator("otel_exporter_otlp_traces_endpoint", mode="before")
    @classmethod
    def validate_otel_endpoint(cls, value: str | None) -> str | None:
        endpoint = str(value or "").strip()
        if not endpoint:
            return None
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith("/v1/traces")
        ):
            raise ValueError("OTLP traces endpoint must be an HTTP(S) /v1/traces URL without credentials")
        return endpoint


@lru_cache
def get_settings() -> Settings:
    return Settings()
