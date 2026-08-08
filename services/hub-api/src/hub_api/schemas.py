from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ArtifactVersionSummary(BaseModel):
    version: str
    content_sha256: str | None = None
    created_at: datetime


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    provider: str
    title: str
    summary: str
    category: str | None = None
    audience: str | None = None
    duration: str | None = None
    output: str | None = None
    tags: list[str] = Field(default_factory=list)
    visibility: str
    status: str
    current_version: str
    source_url: str | None = None


class ArtifactDetail(ArtifactSummary):
    owner_id: str | None = None
    department_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    versions: list[ArtifactVersionSummary] = Field(default_factory=list)


class ArtifactListResponse(BaseModel):
    items: list[ArtifactSummary]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class PublicationPreviewRequest(BaseModel):
    kind: str = Field(pattern="^(case|skill)$")
    requested_scope: str = Field(pattern="^(personal|department|organization)$")
    target_department_id: str | None = Field(default=None, min_length=1, max_length=160)
    package: dict[str, Any]
    source: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    status: str
    warnings: list[str] = Field(default_factory=list)
    rules_version: str = "legacy-unknown"


class PublicationPreviewResponse(BaseModel):
    preview_id: str
    validation: ValidationResult
    allowed_scopes: list[str]
    expires_at: datetime
    content_sha256: str


class Confirmation(BaseModel):
    confirmed: bool = True
    confirmed_at: datetime


class PublishRequest(BaseModel):
    preview_id: str = Field(min_length=8)
    confirmed_scope: str = Field(pattern="^(personal|department|organization)$")
    target_department_id: str | None = Field(default=None, min_length=1, max_length=160)
    confirmation: Confirmation


class PublishResponse(BaseModel):
    artifact_id: str
    version: str
    scope: str
    status: str
    url: str | None = None


class VersionUpdateRequest(BaseModel):
    preview_id: str = Field(min_length=8)
    confirmed_scope: str = Field(pattern="^(personal|department|organization)$")
    target_department_id: str | None = Field(default=None, min_length=1, max_length=160)
    confirmation: Confirmation


class RatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="quality", min_length=1, max_length=80)


class RollbackRequest(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    confirmation: Confirmation


class SkillRecordResponse(BaseModel):
    slug: str
    display_name: str
    summary: str
    version: str | None = None
    score: float | None = None
    updated_at: int | None = None


class SkillSearchResponse(BaseModel):
    provider: str = "skillhub"
    items: list[SkillRecordResponse]
    query: str


class SkillInstallPlanRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=240)
    version: str | None = Field(default=None, min_length=1, max_length=40)
    target_agent: str = Field(default="workbuddy", min_length=1, max_length=80)


class SkillInstallPlanResponse(BaseModel):
    provider: str = "skillhub"
    slug: str
    version: str
    download_url: str
    sha256: str
    source: str
    permissions: list[str] = Field(default_factory=list)
    supported_agents: list[str] = Field(default_factory=list)
    target_agent: str
    install_directory: str
    requires_execution_confirmation: bool = True
    uninstall: str


class CollaborationTaskRequest(BaseModel):
    team_id: str = Field(min_length=1)
    goal: str = Field(min_length=1, max_length=4000)
    budget: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)


class CollaborationTaskResponse(BaseModel):
    task_id: str
    external_task_id: str = Field(description="Deprecated alias of dispatch_event_id")
    dispatch_event_id: str
    transport: Literal["matrix"] = "matrix"
    status_source: Literal["hub"] = "hub"
    room_id: str | None = None
    team_id: str
    status: str
    goal: str
    created_at: datetime
    updated_at: datetime


class CollaborationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class CollaborationCancelResponse(BaseModel):
    task_id: str
    status: str


class CollaborationEventResponse(BaseModel):
    event_id: int
    event_type: str
    cursor: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class CollaborationArtifactResponse(BaseModel):
    artifact_id: str
    task_id: str
    name: str
    mxc_uri: str
    media_type: str
    size: int | None = None
    sha256: str | None = None
    purpose: str
    sender: str | None = None
    origin_server_ts: int | None = None
    verification_status: Literal["metadata_only", "verified", "failed"] = "metadata_only"
    content_verified: bool = False
    safe_to_execute: Literal[False] = False
    actual_sha256: str | None = None
    actual_size: int | None = None
    response_media_type: str | None = None
    detected_media_type: str | None = None
    verification_error: str | None = None
    verified_at: datetime | None = None


class CollaborationSyncResponse(BaseModel):
    status: Literal["ok", "degraded", "not_needed"]
    error: str | None = None


class CollaborationEventsResponse(BaseModel):
    task_id: str
    events: list[CollaborationEventResponse]
    artifacts: list[CollaborationArtifactResponse]
    next_cursor: int
    sync: CollaborationSyncResponse


class CollaborationArtifactsResponse(BaseModel):
    task_id: str
    artifacts: list[CollaborationArtifactResponse]
    sync: CollaborationSyncResponse


class CollaborationWaitResponse(CollaborationEventsResponse):
    task: CollaborationTaskResponse
    timed_out: bool
