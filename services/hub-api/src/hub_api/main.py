from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import re
from typing import Any, Annotated
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .identity import ActorIdentity, IdentityError, OIDCVerifier
from .models import (
    Artifact,
    ArtifactVersion,
    AuditEvent,
    CollaborationArtifactVerification,
    CollaborationEvent,
    CollaborationTask,
    PublicationPreview,
)
from .media_validation import MediaValidationError, verify_media
from .observability import ObservabilityMiddleware, metrics_response
from .publication import (
    SCAN_RULES_VERSION,
    content_sha256,
    expires_at,
    is_expired,
    make_preview_id,
    scan_package,
)
from .tracing import TracingMiddleware, create_tracer_provider
from .integrations.agentteams import (
    HUB_EVENT_KEY,
    AgentTeamsControllerClient,
    AgentTeamsError,
    MatrixClient,
    build_hub_message,
    event_belongs_to_task,
    event_artifact,
    event_status,
    parse_mxc_uri,
    resolve_dispatch_target,
)
from .integrations.skillhub import SkillHubClient, SkillHubError
from .schemas import (
    ArtifactDetail,
    ArtifactListResponse,
    ArtifactSummary,
    HealthResponse,
    PublishRequest,
    PublishResponse,
    PublicationPreviewRequest,
    PublicationPreviewResponse,
    ValidationResult,
    CollaborationTaskRequest,
    CollaborationTaskResponse,
    CollaborationMessageRequest,
    CollaborationCancelResponse,
    CollaborationArtifactResponse,
    CollaborationArtifactsResponse,
    CollaborationEventsResponse,
    CollaborationEventResponse,
    CollaborationSyncResponse,
    CollaborationWaitResponse,
    SkillSearchResponse,
    SkillRecordResponse,
    SkillInstallPlanRequest,
    SkillInstallPlanResponse,
    VersionUpdateRequest,
    RatingRequest,
    ReportRequest,
    RollbackRequest,
)

settings = get_settings()
tracer_provider = (
    create_tracer_provider(
        service_name=settings.otel_service_name,
        environment=settings.env,
        sample_ratio=settings.otel_trace_sample_ratio,
        endpoint=settings.otel_exporter_otlp_traces_endpoint,
        timeout_seconds=settings.otel_export_timeout_seconds,
    )
    if settings.otel_exporter_otlp_traces_endpoint
    else None
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from . import db as db_module

    runtime_settings = get_settings()
    db_module.init_db()
    if runtime_settings.seed_demo_cases:
        from .seed import import_cases

        with db_module.SessionLocal() as db:
            import_cases(db, runtime_settings.registry_path)
    yield
    skillhub_client.close()
    agentteams_controller_client.close()
    agentteams_matrix_client.close()
    oidc_verifier.close()
    if tracer_provider is not None:
        tracer_provider.shutdown()


app = FastAPI(
    title="WorkBuddy Hub API",
    version="0.1.0",
    description="Unified catalog gateway for WorkBuddy cases and governed Skills.",
    lifespan=lifespan,
)
skillhub_client = SkillHubClient(
    settings.skillhub_base_url,
    token=settings.skillhub_token,
    timeout_seconds=settings.skillhub_timeout_seconds,
)
agentteams_controller_client = AgentTeamsControllerClient(
    settings.agentteams_base_url,
    token=settings.agentteams_token,
    timeout_seconds=settings.agentteams_timeout_seconds,
)
agentteams_matrix_client = MatrixClient(
    settings.agentteams_matrix_url,
    access_token=settings.agentteams_matrix_token,
    user_id=settings.agentteams_matrix_user_id,
    timeout_seconds=settings.agentteams_timeout_seconds,
)
oidc_verifier = OIDCVerifier(
    settings.oidc_issuer_url,
    settings.oidc_audience,
    groups_claim=settings.oidc_groups_claim,
    department_claim=settings.oidc_department_claim,
    department_group_prefix=settings.oidc_department_group_prefix,
    cache_seconds=settings.oidc_jwks_cache_seconds,
    clock_skew_seconds=settings.oidc_clock_skew_seconds,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Trace-Id"],
)
app.add_middleware(ObservabilityMiddleware)
if tracer_provider is not None:
    app.add_middleware(TracingMiddleware, tracer_provider=tracer_provider)


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="workbuddy-hub-api", version=app.version)


@app.get("/ready", response_model=HealthResponse, tags=["ops"])
def ready(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    db.execute(select(Artifact.id).limit(1))
    return HealthResponse(status="ready", service="workbuddy-hub-api", version=app.version)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    body, content_type = metrics_response()
    return Response(content=body, headers={"Content-Type": content_type})


def _identity_error(exc: IdentityError) -> HTTPException:
    provider_errors = {
        "oidc_not_configured",
        "oidc_endpoint_not_https",
        "oidc_endpoint_invalid",
        "oidc_jwks_host_mismatch",
        "oidc_provider_unavailable",
        "oidc_provider_invalid_response",
        "oidc_issuer_mismatch",
        "oidc_jwks_invalid",
    }
    status = 503 if exc.code in provider_errors else 401
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status_code=status, detail=exc.code, headers=headers)


def get_optional_identity(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
) -> ActorIdentity | None:
    auth_mode = settings.auth_mode.strip().lower()
    if auth_mode == "oidc":
        if not authorization:
            return None
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            raise HTTPException(
                status_code=401,
                detail="bearer_token_required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return oidc_verifier.verify(token.strip())
        except IdentityError as exc:
            raise _identity_error(exc) from exc
    if auth_mode == "local_header":
        if not actor_id:
            return None
        if settings.env != "local":
            raise HTTPException(status_code=503, detail="local_identity_disabled")
        subject = actor_id.strip()
        if not subject or len(subject) > 160:
            raise HTTPException(status_code=401, detail="local_identity_invalid")
        return ActorIdentity(subject=subject, auth_mode="local_header")
    if authorization or actor_id:
        raise HTTPException(status_code=503, detail="identity_mode_not_supported")
    return None


def require_identity(
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
) -> ActorIdentity:
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="identity_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


def _can_read(artifact: Artifact, identity: ActorIdentity | None) -> bool:
    if artifact.visibility == "public":
        return True
    if identity is None:
        return False
    if artifact.visibility == "personal":
        return artifact.owner_id == identity.subject
    if artifact.visibility == "department":
        return bool(artifact.department_id and artifact.department_id in identity.departments)
    if artifact.visibility == "organization":
        return identity.auth_mode == "oidc"
    return False


def _to_summary(artifact: Artifact) -> ArtifactSummary:
    return ArtifactSummary.model_validate(artifact)


def _to_detail(artifact: Artifact) -> ArtifactDetail:
    return ArtifactDetail(
        id=artifact.id,
        kind=artifact.kind,
        provider=artifact.provider,
        title=artifact.title,
        summary=artifact.summary,
        category=artifact.category,
        audience=artifact.audience,
        duration=artifact.duration,
        output=artifact.output,
        tags=artifact.tags or [],
        visibility=artifact.visibility,
        status=artifact.status,
        current_version=artifact.current_version,
        source_url=artifact.source_url,
        owner_id=artifact.owner_id,
        department_id=artifact.department_id,
        metadata=artifact.metadata_json or {},
        versions=[
            {
                "version": version.version,
                "content_sha256": version.content_sha256,
                "created_at": version.created_at,
            }
            for version in artifact.versions
        ],
    )


def _skill_to_summary(record) -> ArtifactSummary:
    raw = record.raw or {}
    return ArtifactSummary(
        id=f"skillhub:{record.slug}",
        kind="skill",
        provider="skillhub",
        title=record.display_name or record.slug,
        summary=record.summary or "",
        category=None,
        audience=None,
        duration=None,
        output=None,
        tags=record.tags or [],
        visibility=str(raw.get("visibility", "organization")),
        status=str(raw.get("status", "published")),
        current_version=record.version or str(raw.get("latestVersion", "unknown")),
        source_url=f"{settings.skillhub_base_url.rstrip('/')}/api/v1/skills/{record.slug}" if settings.skillhub_base_url else None,
    )


def _skill_actor(identity: ActorIdentity | None) -> str | None:
    if getattr(skillhub_client, "configured", False):
        return require_identity(identity).subject
    return identity.subject if identity else None


@app.get("/api/v1/artifacts", response_model=ArtifactListResponse, tags=["catalog"])
def list_artifacts(
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
    q: str | None = Query(default=None, min_length=1, max_length=120),
    kind: str | None = Query(default=None, pattern="^(case|skill)$"),
    category: str | None = Query(default=None, max_length=80),
    visibility: str | None = Query(default=None, pattern="^(public|personal|department|organization)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ArtifactListResponse:
    query = select(Artifact).where(Artifact.status == "published")
    if kind:
        query = query.where(Artifact.kind == kind)
    if category:
        query = query.where(Artifact.category == category)
    if visibility:
        query = query.where(Artifact.visibility == visibility)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Artifact.title.ilike(pattern), Artifact.summary.ilike(pattern)))
    visible = [item for item in db.scalars(query.order_by(Artifact.updated_at.desc())).all() if _can_read(item, identity)]
    if q:
        needle = q.casefold()
        visible = [
            item
            for item in visible
            if needle in item.title.casefold()
            or needle in item.summary.casefold()
            or any(needle in tag.casefold() for tag in (item.tags or []))
        ]
    skill_items = []
    if q and (kind in (None, "skill")):
        try:
            skill_items = skillhub_client.search(q, limit=limit, actor_id=_skill_actor(identity))
        except SkillHubError as exc:
            if kind == "skill":
                status = 503 if exc.code in {"skillhub_unavailable", "skillhub_adapter_not_configured"} else 502
                raise HTTPException(status_code=status, detail=exc.code) from exc
    case_summaries = [_to_summary(item) for item in visible]
    combined = case_summaries + [_skill_to_summary(item) for item in skill_items]
    page = combined[offset : offset + limit]
    return ArtifactListResponse(
        items=page,
        total=len(combined),
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/artifacts/{artifact_id:path}", response_model=ArtifactDetail, tags=["catalog"])
def get_artifact(
    artifact_id: str,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
) -> ArtifactDetail:
    if artifact_id.startswith("skillhub:"):
        slug = artifact_id.removeprefix("skillhub:")
        try:
            raw = skillhub_client.get(slug, actor_id=_skill_actor(identity))
        except SkillHubError as exc:
            status = 503 if exc.code in {"skillhub_unavailable", "skillhub_adapter_not_configured"} else 502
            raise HTTPException(status_code=status, detail=exc.code) from exc
        version = str(raw.get("version") or raw.get("latestVersion") or "unknown")
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        return ArtifactDetail(
            id=artifact_id,
            kind="skill",
            provider="skillhub",
            title=str(raw.get("displayName") or raw.get("display_name") or raw.get("name") or slug),
            summary=str(raw.get("summary") or raw.get("description") or ""),
            tags=[str(tag) for tag in tags],
            visibility=str(raw.get("visibility", "organization")),
            status=str(raw.get("status", "published")),
            current_version=version,
            source_url=f"{settings.skillhub_base_url.rstrip('/')}/api/v1/skills/{slug}" if settings.skillhub_base_url else None,
            metadata=raw,
            versions=[],
        )
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.status != "published" or not _can_read(artifact, identity):
        raise HTTPException(status_code=404, detail="artifact_not_found")
    return _to_detail(artifact)


@app.get("/api/v1/skills", response_model=SkillSearchResponse, tags=["skills"])
def search_skills(
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
) -> SkillSearchResponse:
    try:
        records = skillhub_client.search(q, limit=limit, actor_id=_skill_actor(identity))
    except SkillHubError as exc:
        status = 503 if exc.code in {"skillhub_unavailable", "skillhub_adapter_not_configured"} else 502
        raise HTTPException(status_code=status, detail=exc.code) from exc
    return SkillSearchResponse(
        query=q,
        items=[SkillRecordResponse.model_validate(record.__dict__) for record in records],
    )


@app.get("/api/v1/skills/{slug:path}", tags=["skills"])
def get_skill(
    slug: str,
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
) -> dict:
    try:
        return skillhub_client.get(slug, actor_id=_skill_actor(identity))
    except SkillHubError as exc:
        status = 503 if exc.code in {"skillhub_unavailable", "skillhub_adapter_not_configured"} else 502
        raise HTTPException(status_code=status, detail=exc.code) from exc


@app.post("/api/v1/artifacts/{artifact_id:path}/install-plans", response_model=SkillInstallPlanResponse, tags=["skills"])
def create_skill_install_plan(
    artifact_id: str,
    request: SkillInstallPlanRequest,
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
) -> SkillInstallPlanResponse:
    if not artifact_id.startswith("skillhub:"):
        raise HTTPException(status_code=422, detail="install_plan_requires_skillhub_artifact")
    slug = artifact_id.removeprefix("skillhub:")
    if slug != request.slug:
        raise HTTPException(status_code=409, detail="skill_slug_mismatch")
    try:
        actor = _skill_actor(identity)
        detail = skillhub_client.get(slug, actor_id=actor)
        raw = detail if isinstance(detail, dict) else {}
        resolved = skillhub_client.resolve(slug, request.version or "latest", actor_id=actor)
        match = resolved.get("match") if isinstance(resolved.get("match"), dict) else {}
        version = str(match.get("version") or "")
        if not version:
            raise SkillHubError("skillhub_version_missing")
        download_url = skillhub_client.download_location(slug, version, actor_id=actor)
        sha256 = raw.get("sha256") or raw.get("checksum") or raw.get("contentSha256")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            sha256 = skillhub_client.download_sha256(
                slug,
                version,
                actor_id=actor,
                max_bytes=settings.skillhub_hash_max_bytes,
                download_url=download_url,
            )
    except SkillHubError as exc:
        status = 503 if exc.code in {"skillhub_unavailable", "skillhub_adapter_not_configured"} else 502
        raise HTTPException(status_code=status, detail=exc.code) from exc
    permissions = raw.get("permissions") if isinstance(raw.get("permissions"), list) else []
    agents = raw.get("supportedAgents", raw.get("supported_agents", []))
    supported_agents = agents if isinstance(agents, list) else []
    return SkillInstallPlanResponse(
        slug=slug,
        version=version,
        download_url=download_url,
        sha256=sha256,
        source=f"skillhub:{slug}@{version}",
        permissions=[str(item) for item in permissions],
        supported_agents=[str(item) for item in supported_agents],
        target_agent=request.target_agent,
        install_directory=f"~/.workbuddy/skills/{slug}",
        uninstall=f"Remove the installed skill at ~/.workbuddy/skills/{slug}",
    )


@app.get("/api/v1/collaboration/teams", tags=["collaboration"])
def list_collaboration_teams(
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> dict:
    actor = identity.subject
    try:
        payload = agentteams_controller_client.teams(actor)
    except AgentTeamsError as exc:
        raise _provider_http_error(exc) from exc
    teams = payload.get("teams")
    if not isinstance(teams, list):
        return payload
    unavailable_reason = None
    matrix_user_id = ""
    joined_rooms: set[str] = set()
    if not agentteams_matrix_client.configured:
        unavailable_reason = "agentteams_matrix_not_configured"
    else:
        try:
            matrix_user_id = agentteams_matrix_client.whoami()
            joined_rooms = agentteams_matrix_client.joined_rooms()
        except AgentTeamsError as exc:
            unavailable_reason = exc.code
    enriched = []
    for team in teams:
        if not isinstance(team, dict):
            continue
        item = dict(team)
        if unavailable_reason:
            item["hubDispatch"] = {"ready": False, "reason": unavailable_reason}
        else:
            try:
                target = resolve_dispatch_target(item, matrix_user_id, joined_rooms)
            except AgentTeamsError as exc:
                item["hubDispatch"] = {"ready": False, "reason": exc.code}
            else:
                item["hubDispatch"] = {"ready": True, "roomKind": target.room_kind}
        enriched.append(item)
    return {**payload, "teams": enriched}


COLLAB_STATUSES = {
    "created",
    "queued",
    "running",
    "input_required",
    "completed",
    "failed",
    "cancel_requested",
    "cancelled",
    "timed_out",
}


def _task_id(actor_id: str, idempotency_key: str | None) -> str:
    if idempotency_key:
        value = uuid5(NAMESPACE_URL, f"workbuddy-hub:{actor_id}:{idempotency_key}")
        return f"collab_{value.hex}"
    return f"collab_{uuid4().hex}"


def _collab_response(task: CollaborationTask) -> CollaborationTaskResponse:
    return CollaborationTaskResponse(
        task_id=task.id,
        external_task_id=task.external_task_id or "",
        dispatch_event_id=task.external_task_id or "",
        transport="matrix",
        status_source="hub",
        room_id=task.room_id,
        team_id=task.team_id,
        status=task.status,
        goal=task.goal,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _provider_http_error(exc: AgentTeamsError) -> HTTPException:
    if exc.code.endswith("_not_configured") or exc.code.endswith("_unavailable"):
        status = 503
    elif exc.code in {"agentteams_team_not_found", "agentteams_matrix_media_not_found"}:
        status = 404
    elif exc.code == "agentteams_matrix_media_too_large":
        status = 413
    elif exc.code in {"agentteams_matrix_media_uri_invalid", "agentteams_matrix_media_limit_invalid"}:
        status = 422
    elif exc.code in {"agentteams_no_joined_dispatch_room", "agentteams_matrix_user_mismatch"}:
        status = 403
    else:
        status = 502
    return HTTPException(status_code=status, detail=exc.code)


def _owned_task(db: Session, task_id: str, actor_id: str) -> CollaborationTask:
    task = db.get(CollaborationTask, task_id)
    if task is None or task.actor_id != actor_id:
        raise HTTPException(status_code=404, detail="collaboration_task_not_found")
    return task


TERMINAL_COLLAB_STATUSES = {"completed", "failed", "cancelled", "timed_out"}


def _refresh_collaboration_events(
    db: Session, task: CollaborationTask, *, timeout_ms: int = 0
) -> CollaborationSyncResponse:
    if not task.room_id:
        return CollaborationSyncResponse(status="degraded", error="collaboration_room_missing")
    try:
        provider_payload = agentteams_matrix_client.sync(
            task.room_id, since=task.last_event_cursor, timeout_ms=timeout_ms
        )
    except AgentTeamsError as exc:
        if not (exc.code.endswith("_unavailable") or exc.code.endswith("_not_configured")):
            raise _provider_http_error(exc) from exc
        return CollaborationSyncResponse(status="degraded", error=exc.code)
    provider_events = provider_payload.get("events", []) if isinstance(provider_payload, dict) else []
    for item in provider_events if isinstance(provider_events, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("sender") or "") == agentteams_matrix_client.user_id:
            continue
        if not event_belongs_to_task(item, task.id):
            continue
        event_cursor = item.get("event_id")
        if event_cursor and db.scalar(
            select(CollaborationEvent.id).where(
                CollaborationEvent.task_id == task.id,
                CollaborationEvent.external_cursor == str(event_cursor),
            )
        ):
            continue
        new_status = event_status(item)
        artifact = event_artifact(item, task.id)
        if new_status in COLLAB_STATUSES and new_status != task.status:
            task.status = new_status
        event_type = "status_changed" if new_status else "artifact_received" if artifact else "matrix_message"
        db.add(
            CollaborationEvent(
                task_id=task.id,
                event_type=event_type,
                external_cursor=str(event_cursor) if event_cursor else None,
                payload=item,
            )
        )
        if artifact:
            db.add(
                AuditEvent(
                    event_type="collaboration_artifact_observed",
                    actor_id=task.actor_id,
                    object_id=task.id,
                    payload={
                        "artifact_id": artifact["artifact_id"],
                        "name": artifact["name"],
                        "mxc_uri": artifact["mxc_uri"],
                        "verification_status": artifact["verification_status"],
                    },
                )
            )
    task.last_event_cursor = provider_payload.get("next_cursor") or task.last_event_cursor
    db.commit()
    return CollaborationSyncResponse(status="ok")


def _collaboration_event_page(
    db: Session,
    task: CollaborationTask,
    *,
    after_cursor: int,
    sync: CollaborationSyncResponse,
) -> CollaborationEventsResponse:
    stored = db.scalars(
        select(CollaborationEvent)
        .where(CollaborationEvent.task_id == task.id, CollaborationEvent.id > after_cursor)
        .order_by(CollaborationEvent.id.asc())
    ).all()
    events = [
        CollaborationEventResponse(
            event_id=event.id,
            event_type=event.event_type,
            cursor=event.external_cursor,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in stored
    ]
    artifacts = [
        _collaboration_artifact_response(db, artifact)
        for event in stored
        if (artifact := event_artifact(event.payload, task.id)) is not None
    ]
    next_cursor = events[-1].event_id if events else after_cursor
    return CollaborationEventsResponse(
        task_id=task.id,
        events=events,
        artifacts=artifacts,
        next_cursor=next_cursor,
        sync=sync,
    )


def _collaboration_artifact_response(
    db: Session, artifact: dict
) -> CollaborationArtifactResponse:
    verification = db.scalar(
        select(CollaborationArtifactVerification).where(
            CollaborationArtifactVerification.task_id == artifact["task_id"],
            CollaborationArtifactVerification.artifact_id == artifact["artifact_id"],
        )
    )
    if verification is None:
        return CollaborationArtifactResponse(**artifact)
    enriched = {
        **artifact,
        "verification_status": verification.status,
        "content_verified": verification.status == "verified",
        "actual_sha256": verification.actual_sha256,
        "actual_size": verification.actual_size,
        "response_media_type": verification.response_media_type,
        "detected_media_type": verification.detected_media_type,
        "verification_error": verification.error_code,
        "verified_at": verification.verified_at,
    }
    return CollaborationArtifactResponse(**enriched)


def _save_artifact_verification(
    db: Session,
    *,
    task: CollaborationTask,
    artifact: dict,
    actor_id: str,
    idempotency_key: str,
    status: str,
    response_media_type: str | None = None,
    actual_sha256: str | None = None,
    actual_size: int | None = None,
    detected_media_type: str | None = None,
    error_code: str | None = None,
) -> CollaborationArtifactVerification:
    verification = db.scalar(
        select(CollaborationArtifactVerification).where(
            CollaborationArtifactVerification.task_id == task.id,
            CollaborationArtifactVerification.artifact_id == artifact["artifact_id"],
        )
    )
    if verification is None:
        verification = CollaborationArtifactVerification(
            task_id=task.id,
            artifact_id=artifact["artifact_id"],
            status=status,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        db.add(verification)
    verification.status = status
    verification.claimed_sha256 = artifact.get("sha256")
    verification.actual_sha256 = actual_sha256
    verification.claimed_size = artifact.get("size")
    verification.actual_size = actual_size
    verification.declared_media_type = artifact.get("media_type")
    verification.response_media_type = response_media_type
    verification.detected_media_type = detected_media_type
    verification.error_code = error_code
    verification.actor_id = actor_id
    verification.idempotency_key = idempotency_key
    verification.verified_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            event_type=f"collaboration_artifact_verification_{status}",
            actor_id=actor_id,
            object_id=task.id,
            payload={
                "artifact_id": artifact["artifact_id"],
                "claimed_sha256": artifact.get("sha256"),
                "actual_sha256": actual_sha256,
                "actual_size": actual_size,
                "detected_media_type": detected_media_type,
                "error_code": error_code,
            },
        )
    )
    db.commit()
    db.refresh(verification)
    return verification


@app.post("/api/v1/collaboration/tasks", response_model=CollaborationTaskResponse, tags=["collaboration"])
def create_collaboration_task(
    request: CollaborationTaskRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CollaborationTaskResponse:
    actor = identity.subject
    if idempotency_key:
        existing = db.scalar(
            select(CollaborationTask).where(
                CollaborationTask.actor_id == actor,
                CollaborationTask.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return _collab_response(existing)
    task_id = _task_id(actor, idempotency_key)
    try:
        team = agentteams_controller_client.team(actor, request.team_id)
        matrix_user_id = agentteams_matrix_client.whoami()
        target = resolve_dispatch_target(team, matrix_user_id, agentteams_matrix_client.joined_rooms())
        baseline = agentteams_matrix_client.sync(target.room_id)
        message = build_hub_message(
            kind="task.request",
            task_id=task_id,
            actor_id=actor,
            content=request.goal,
            leader_matrix_user_id=target.leader_matrix_user_id,
            budget=request.budget,
            output_contract=request.output_contract,
        )
        provider_payload = agentteams_matrix_client.send_text(target.room_id, task_id, message)
    except AgentTeamsError as exc:
        raise _provider_http_error(exc) from exc
    dispatch_event_id = str(provider_payload.get("event_id") or "")
    if not dispatch_event_id:
        raise HTTPException(status_code=502, detail="agentteams_matrix_event_id_missing")
    task = CollaborationTask(
        id=task_id,
        actor_id=actor,
        team_id=request.team_id,
        external_task_id=dispatch_event_id,
        room_id=target.room_id,
        goal=request.goal,
        budget=request.budget,
        output_contract=request.output_contract,
        status="queued",
        last_event_cursor=baseline.get("next_cursor"),
        idempotency_key=idempotency_key,
    )
    dispatch_payload = {
        "transport": "matrix",
        "event_id": dispatch_event_id,
        "room_id": target.room_id,
        "room_kind": target.room_kind,
        "matrix_sender": matrix_user_id,
        HUB_EVENT_KEY: message[HUB_EVENT_KEY],
    }
    db.add(task)
    # Persist the parent before audit events so PostgreSQL can enforce the FK
    # even though these models do not define an ORM relationship.
    db.flush()
    db.add(
        CollaborationEvent(
            task_id=task.id,
            event_type="task_dispatched",
            external_cursor=dispatch_event_id,
            payload=dispatch_payload,
        )
    )
    db.add(AuditEvent(event_type="collaboration_task_dispatched", actor_id=actor, object_id=task.id, payload=dispatch_payload))
    db.commit()
    db.refresh(task)
    return _collab_response(task)


@app.get("/api/v1/collaboration/tasks/{task_id}", response_model=CollaborationTaskResponse, tags=["collaboration"])
def get_collaboration_task(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> CollaborationTaskResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    return _collab_response(task)


@app.get(
    "/api/v1/collaboration/tasks/{task_id}/events",
    response_model=CollaborationEventsResponse,
    tags=["collaboration"],
)
def get_collaboration_events(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    cursor: int = Query(default=0, ge=0),
) -> CollaborationEventsResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    sync = _refresh_collaboration_events(db, task)
    return _collaboration_event_page(db, task, after_cursor=cursor, sync=sync)


@app.get(
    "/api/v1/collaboration/tasks/{task_id}/wait",
    response_model=CollaborationWaitResponse,
    tags=["collaboration"],
)
def wait_for_collaboration_task(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    cursor: int = Query(default=0, ge=0),
    timeout_seconds: int = Query(default=20, ge=1, le=25),
) -> CollaborationWaitResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    existing = _collaboration_event_page(
        db,
        task,
        after_cursor=cursor,
        sync=CollaborationSyncResponse(status="not_needed"),
    )
    if existing.events or task.status in TERMINAL_COLLAB_STATUSES:
        return CollaborationWaitResponse(
            **existing.model_dump(), task=_collab_response(task), timed_out=False
        )
    sync = _refresh_collaboration_events(db, task, timeout_ms=timeout_seconds * 1000)
    page = _collaboration_event_page(db, task, after_cursor=cursor, sync=sync)
    return CollaborationWaitResponse(
        **page.model_dump(),
        task=_collab_response(task),
        timed_out=not page.events and sync.status == "ok" and task.status not in TERMINAL_COLLAB_STATUSES,
    )


@app.get(
    "/api/v1/collaboration/tasks/{task_id}/artifacts",
    response_model=CollaborationArtifactsResponse,
    tags=["collaboration"],
)
def get_collaboration_artifacts(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> CollaborationArtifactsResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    sync = _refresh_collaboration_events(db, task)
    stored = db.scalars(
        select(CollaborationEvent)
        .where(CollaborationEvent.task_id == task.id)
        .order_by(CollaborationEvent.id.asc())
    ).all()
    artifacts = [
        _collaboration_artifact_response(db, artifact)
        for event in stored
        if (artifact := event_artifact(event.payload, task.id)) is not None
    ]
    return CollaborationArtifactsResponse(task_id=task.id, artifacts=artifacts, sync=sync)


@app.post(
    "/api/v1/collaboration/tasks/{task_id}/artifacts/{artifact_id}/verify",
    response_model=CollaborationArtifactResponse,
    tags=["collaboration"],
)
def verify_collaboration_artifact(
    task_id: str,
    artifact_id: str,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> CollaborationArtifactResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    stored = db.scalars(
        select(CollaborationEvent)
        .where(CollaborationEvent.task_id == task.id)
        .order_by(CollaborationEvent.id.asc())
    ).all()
    artifact = next(
        (
            candidate
            for event in stored
            if (candidate := event_artifact(event.payload, task.id)) is not None
            and candidate["artifact_id"] == artifact_id
        ),
        None,
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="collaboration_artifact_not_found")
    existing = db.scalar(
        select(CollaborationArtifactVerification).where(
            CollaborationArtifactVerification.task_id == task.id,
            CollaborationArtifactVerification.artifact_id == artifact_id,
        )
    )
    if existing and existing.status == "verified":
        return _collaboration_artifact_response(db, artifact)

    allowlist = {
        item.strip().lower()
        for item in settings.agentteams_matrix_media_server_allowlist.split(",")
        if item.strip()
    }
    if not allowlist:
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            error_code="matrix_media_server_allowlist_not_configured",
        )
        raise HTTPException(status_code=503, detail="matrix_media_server_allowlist_not_configured")
    try:
        media_server, _ = parse_mxc_uri(artifact["mxc_uri"])
    except AgentTeamsError as exc:
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            error_code=exc.code,
        )
        raise _provider_http_error(exc) from exc
    if media_server.lower() not in allowlist:
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            error_code="matrix_media_server_not_allowed",
        )
        raise HTTPException(status_code=403, detail="matrix_media_server_not_allowed")
    if not artifact.get("sha256"):
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            error_code="artifact_sha256_required",
        )
        raise HTTPException(status_code=422, detail="artifact_sha256_required")

    try:
        media = agentteams_matrix_client.download_media(
            artifact["mxc_uri"], settings.agentteams_matrix_media_max_bytes
        )
    except AgentTeamsError as exc:
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            error_code=exc.code,
        )
        raise _provider_http_error(exc) from exc
    try:
        result = verify_media(
            content=media.content,
            filename=artifact["name"],
            declared_media_type=artifact["media_type"],
            response_media_type=media.content_type,
            claimed_size=artifact.get("size"),
            claimed_sha256=artifact["sha256"],
            max_uncompressed_bytes=settings.agentteams_matrix_media_max_bytes * 10,
        )
    except MediaValidationError as exc:
        _save_artifact_verification(
            db,
            task=task,
            artifact=artifact,
            actor_id=actor,
            idempotency_key=idempotency_key,
            status="failed",
            response_media_type=media.content_type,
            actual_sha256=exc.actual_sha256,
            actual_size=len(media.content),
            error_code=exc.code,
        )
        raise HTTPException(status_code=422, detail=exc.code) from exc
    _save_artifact_verification(
        db,
        task=task,
        artifact=artifact,
        actor_id=actor,
        idempotency_key=idempotency_key,
        status="verified",
        response_media_type=media.content_type,
        actual_sha256=str(result["actual_sha256"]),
        actual_size=int(result["actual_size"]),
        detected_media_type=str(result["detected_media_type"]),
    )
    return _collaboration_artifact_response(db, artifact)


@app.post("/api/v1/collaboration/tasks/{task_id}/messages", tags=["collaboration"])
def send_collaboration_message(
    task_id: str,
    request: CollaborationMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> dict:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    existing = _audit_idempotent_result(
        db,
        event_type="collaboration_message_sent",
        actor_id=actor,
        object_id=task.id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return existing
    if not task.room_id:
        raise HTTPException(status_code=409, detail="collaboration_room_missing")
    if request.attachments:
        raise HTTPException(status_code=501, detail="matrix_attachment_bridge_not_implemented")
    try:
        message = build_hub_message(
            kind="task.message",
            task_id=task.id,
            actor_id=actor,
            content=request.content,
        )
        payload = agentteams_matrix_client.send_text(task.room_id, f"message-{uuid4().hex}", message)
    except AgentTeamsError as exc:
        raise _provider_http_error(exc) from exc
    result = {"task_id": task.id, "status": "sent", "provider": payload}
    db.add(
        AuditEvent(
            event_type="collaboration_message_sent",
            actor_id=actor,
            object_id=task.id,
            payload={"idempotency_key": idempotency_key, "result": result},
        )
    )
    db.commit()
    return result


@app.post("/api/v1/collaboration/tasks/{task_id}/cancel", response_model=CollaborationCancelResponse, tags=["collaboration"])
def cancel_collaboration_task(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
) -> CollaborationCancelResponse:
    actor = identity.subject
    task = _owned_task(db, task_id, actor)
    existing = _audit_idempotent_result(
        db,
        event_type="collaboration_task_cancel_requested",
        actor_id=actor,
        object_id=task.id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return CollaborationCancelResponse.model_validate(existing)
    if task.status in TERMINAL_COLLAB_STATUSES:
        result = {"task_id": task.id, "status": task.status}
        db.add(
            AuditEvent(
                event_type="collaboration_task_cancel_requested",
                actor_id=actor,
                object_id=task.id,
                payload={"idempotency_key": idempotency_key, "result": result},
            )
        )
        db.commit()
        return CollaborationCancelResponse.model_validate(result)
    if not task.room_id:
        raise HTTPException(status_code=409, detail="collaboration_room_missing")
    try:
        message = build_hub_message(
            kind="task.cancel_requested",
            task_id=task.id,
            actor_id=actor,
            content="Cancellation requested. Stop further work and report the current state.",
        )
        provider_payload = agentteams_matrix_client.send_text(
            task.room_id, f"cancel-{task.id}", message
        )
    except AgentTeamsError as exc:
        raise _provider_http_error(exc) from exc
    task.status = "cancel_requested"
    db.add(CollaborationEvent(task_id=task.id, event_type="cancel_requested", payload=provider_payload))
    result = {"task_id": task.id, "status": task.status}
    db.add(AuditEvent(event_type="collaboration_task_cancel_requested", actor_id=actor, object_id=task.id, payload={**provider_payload, "idempotency_key": idempotency_key, "result": result}))
    db.commit()
    return CollaborationCancelResponse.model_validate(result)


def _allowed_publication_scopes(
    identity: ActorIdentity, target_department_id: str | None
) -> list[str]:
    scopes = ["personal"]
    if identity.auth_mode != "oidc":
        return scopes
    if target_department_id and target_department_id in identity.departments:
        scopes.append("department")
    scopes.append("organization")
    return scopes


def _validate_publication_target(scope: str, target_department_id: str | None) -> None:
    if scope == "department":
        if not target_department_id or target_department_id != target_department_id.strip():
            raise HTTPException(status_code=422, detail="target_department_required")
    elif target_department_id is not None:
        raise HTTPException(status_code=422, detail="target_department_not_allowed")


def _publication_preview_response(preview: PublicationPreview) -> PublicationPreviewResponse:
    return PublicationPreviewResponse(
        preview_id=preview.id,
        validation=ValidationResult(
            status=preview.status,
            warnings=preview.warnings or [],
            rules_version=preview.scan_rules_version or "legacy-unknown",
        ),
        allowed_scopes=preview.allowed_scopes or [],
        expires_at=preview.expires_at,
        content_sha256=preview.content_sha256,
    )


def _artifact_url(artifact_id: str) -> str:
    return f"/workbuddy-hub/community/case.html?id={artifact_id}"


def _can_manage_artifact(artifact: Artifact, identity: ActorIdentity) -> bool:
    return artifact.owner_id == identity.subject


def _audit_idempotent_result(
    db: Session, *, event_type: str, actor_id: str, object_id: str, idempotency_key: str
) -> dict | None:
    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == event_type,
            AuditEvent.actor_id == actor_id,
            AuditEvent.object_id == object_id,
        )
    ).all()
    for event in events:
        if (event.payload or {}).get("idempotency_key") == idempotency_key:
            result = (event.payload or {}).get("result")
            return result if isinstance(result, dict) else None
    return None


@app.post("/api/v1/publication-previews", response_model=PublicationPreviewResponse, tags=["publication"])
def create_publication_preview(
    request: PublicationPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ] = None,
) -> PublicationPreviewResponse:
    actor = identity.subject
    _validate_publication_target(request.requested_scope, request.target_department_id)
    if settings.auth_mode.strip().lower() == "oidc" and not idempotency_key:
        raise HTTPException(status_code=400, detail="idempotency_key_required")
    package_hash = content_sha256(request.package)
    if idempotency_key:
        existing = db.scalar(
            select(PublicationPreview).where(
                PublicationPreview.actor_id == actor,
                PublicationPreview.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if (
                existing.kind != request.kind
                or existing.requested_scope != request.requested_scope
                or existing.target_department_id != request.target_department_id
                or existing.content_sha256 != package_hash
            ):
                raise HTTPException(status_code=409, detail="idempotency_key_reused")
            return _publication_preview_response(existing)
    validation_status, warnings = scan_package(request.kind, request.package)
    allowed_scopes = _allowed_publication_scopes(identity, request.target_department_id)
    if request.requested_scope not in allowed_scopes:
        warning = (
            "target_department_not_authorized"
            if request.requested_scope == "department" and request.target_department_id
            else "requested_scope_not_authorized"
        )
        warnings = [*warnings, warning]
    preview = PublicationPreview(
        id=make_preview_id(),
        kind=request.kind,
        requested_scope=request.requested_scope,
        target_department_id=request.target_department_id,
        package_json=request.package,
        source_json=request.source,
        content_sha256=package_hash,
        allowed_scopes=allowed_scopes,
        warnings=warnings,
        status=validation_status,
        actor_id=actor,
        idempotency_key=idempotency_key,
        scan_rules_version=SCAN_RULES_VERSION,
        expires_at=expires_at(),
    )
    db.add(preview)
    db.add(
        AuditEvent(
            event_type="preview_created",
            actor_id=actor,
            object_id=preview.id,
            payload={
                "kind": request.kind,
                "requested_scope": request.requested_scope,
                "status": validation_status,
                "scan_rules_version": SCAN_RULES_VERSION,
            },
        )
    )
    db.commit()
    return _publication_preview_response(preview)


@app.post("/api/v1/publications", response_model=PublishResponse, tags=["publication"])
def publish_preview(
    request: PublishRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    publication_grant: Annotated[str | None, Header(alias="X-WorkBuddy-Publication-Grant")] = None,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ] = None,
) -> PublishResponse:
    actor = identity.subject
    _validate_publication_target(request.confirmed_scope, request.target_department_id)
    preview = db.get(PublicationPreview, request.preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="preview_not_found")
    if idempotency_key:
        existing = _audit_idempotent_result(
            db,
            event_type="publication_result",
            actor_id=actor,
            object_id=preview.id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return PublishResponse.model_validate(existing)
    if preview.actor_id != actor:
        raise HTTPException(status_code=403, detail="preview_actor_mismatch")
    if request.confirmation.confirmed is not True:
        raise HTTPException(status_code=400, detail="explicit_confirmation_required")
    if request.confirmed_scope != preview.requested_scope:
        raise HTTPException(status_code=409, detail="scope_changed_since_preview")
    if request.target_department_id != preview.target_department_id:
        raise HTTPException(status_code=409, detail="target_department_changed_since_preview")
    if preview.status == "published":
        if not preview.result_json:
            raise HTTPException(status_code=409, detail="publication_result_missing")
        return PublishResponse.model_validate(preview.result_json)
    if is_expired(preview):
        raise HTTPException(status_code=410, detail="preview_expired")
    if preview.status == "blocked":
        raise HTTPException(status_code=422, detail="preview_validation_failed")
    current_allowed_scopes = _allowed_publication_scopes(identity, request.target_department_id)
    if (
        request.confirmed_scope not in preview.allowed_scopes
        or request.confirmed_scope not in current_allowed_scopes
    ):
        raise HTTPException(status_code=403, detail="scope_denied")
    package = preview.package_json
    if preview.kind == "skill":
        try:
            provider_payload = skillhub_client.publish(
                package,
                actor_id=actor,
                grant=publication_grant or "",
                publish_path=settings.skillhub_publish_path,
                idempotency_key=preview.id,
            )
        except SkillHubError as exc:
            status = 503 if exc.code in {
                "skillhub_adapter_not_configured",
                "skillhub_unavailable",
                "skillhub_publication_grant_endpoint_not_configured",
            } else 502
            raise HTTPException(status_code=status, detail=exc.code) from exc
        provider_id = str(provider_payload.get("skill_id") or provider_payload.get("skillId") or provider_payload.get("slug") or package.get("slug") or package.get("id") or "")
        version = str(provider_payload.get("version") or package.get("version") or "")
        if not provider_id or not version:
            raise HTTPException(status_code=502, detail="skillhub_publication_response_invalid")
        result = PublishResponse(
            artifact_id=f"skillhub:{provider_id}",
            version=version,
            scope=request.confirmed_scope,
            status=str(provider_payload.get("status", "published")),
            url=f"{settings.skillhub_base_url.rstrip('/')}/api/v1/skills/{provider_id}" if settings.skillhub_base_url else None,
        )
        preview.status = "published"
        preview.result_json = result.model_dump(mode="json")
        preview.confirmed_at = datetime.now(timezone.utc)
        db.add(
            AuditEvent(
                event_type="skill_publication_created",
                actor_id=actor,
                object_id=f"skillhub:{provider_id}",
                payload={"preview_id": preview.id, "scope": request.confirmed_scope, "hash": preview.content_sha256},
            )
        )
        if idempotency_key:
            db.add(
                AuditEvent(
                    event_type="publication_result",
                    actor_id=actor,
                    object_id=preview.id,
                    payload={
                        "idempotency_key": idempotency_key,
                        "result": result.model_dump(mode="json"),
                    },
                )
            )
        db.commit()
        return result
    artifact_id = str(package["id"])
    if db.get(Artifact, artifact_id) is not None:
        raise HTTPException(status_code=409, detail="artifact_already_exists")
    artifact = Artifact(
        id=artifact_id,
        kind="case",
        provider="hub-case",
        provider_id=artifact_id,
        title=str(package["name"]),
        summary=str(package["summary"]),
        category=str(package.get("category")) if package.get("category") else None,
        audience=str(package.get("audience")) if package.get("audience") else None,
        duration=str(package.get("duration")) if package.get("duration") else None,
        output=str(package.get("output")) if package.get("output") else None,
        tags=list(package.get("tags", [])),
        visibility=request.confirmed_scope,
        owner_id=actor,
        department_id=request.target_department_id,
        status="published",
        current_version=str(package["version"]),
        source_url=package.get("learningPath"),
        metadata_json=package,
    )
    db.add(artifact)
    db.add(
        ArtifactVersion(
            artifact_id=artifact_id,
            version=str(package["version"]),
            payload=package,
            content_sha256=preview.content_sha256,
        )
    )
    result = PublishResponse(
        artifact_id=artifact_id,
        version=str(package["version"]),
        scope=request.confirmed_scope,
        status="published",
        url=f"/workbuddy-hub/community/case.html?id={artifact_id}",
    )
    preview.status = "published"
    preview.result_json = result.model_dump(mode="json")
    preview.confirmed_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            event_type="publication_created",
            actor_id=actor,
            object_id=artifact_id,
            payload={"preview_id": preview.id, "scope": request.confirmed_scope, "hash": preview.content_sha256},
        )
    )
    if idempotency_key:
        db.add(
            AuditEvent(
                event_type="publication_result",
                actor_id=actor,
                object_id=preview.id,
                payload={
                    "idempotency_key": idempotency_key,
                    "result": result.model_dump(mode="json"),
                },
            )
        )
    db.commit()
    return result


@app.post(
    "/api/v1/artifacts/{artifact_id:path}/versions",
    response_model=PublishResponse,
    tags=["publication"],
)
def publish_artifact_version(
    artifact_id: str,
    request: VersionUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=240)
    ] = None,
) -> PublishResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    actor = identity.subject
    if not _can_manage_artifact(artifact, identity):
        raise HTTPException(status_code=403, detail="artifact_owner_required")
    if idempotency_key:
        existing = _audit_idempotent_result(
            db,
            event_type="artifact_version_result",
            actor_id=actor,
            object_id=artifact.id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return PublishResponse.model_validate(existing)
    _validate_publication_target(request.confirmed_scope, request.target_department_id)
    preview = db.get(PublicationPreview, request.preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="preview_not_found")
    if preview.actor_id != actor:
        raise HTTPException(status_code=403, detail="preview_actor_mismatch")
    if preview.status == "published" and preview.result_json:
        return PublishResponse.model_validate(preview.result_json)
    if preview.kind != artifact.kind or preview.package_json.get("id") != artifact.id:
        raise HTTPException(status_code=409, detail="version_preview_artifact_mismatch")
    if request.confirmation.confirmed is not True:
        raise HTTPException(status_code=400, detail="explicit_confirmation_required")
    if request.confirmed_scope != artifact.visibility or request.confirmed_scope != preview.requested_scope:
        raise HTTPException(status_code=409, detail="scope_changed_since_preview")
    if request.target_department_id != artifact.department_id or request.target_department_id != preview.target_department_id:
        raise HTTPException(status_code=409, detail="target_department_changed_since_preview")
    if is_expired(preview):
        raise HTTPException(status_code=410, detail="preview_expired")
    if preview.status == "blocked":
        raise HTTPException(status_code=422, detail="preview_validation_failed")
    if (
        request.confirmed_scope not in preview.allowed_scopes
        or request.confirmed_scope not in _allowed_publication_scopes(identity, request.target_department_id)
    ):
        raise HTTPException(status_code=403, detail="scope_denied")
    package = preview.package_json
    version = str(package.get("version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise HTTPException(status_code=422, detail="version_semver_required")
    if db.scalar(
        select(ArtifactVersion.id).where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.version == version,
        )
    ):
        raise HTTPException(status_code=409, detail="artifact_version_exists")
    artifact.title = str(package["name"])
    artifact.summary = str(package["summary"])
    artifact.category = str(package.get("category")) if package.get("category") else None
    artifact.audience = str(package.get("audience")) if package.get("audience") else None
    artifact.duration = str(package.get("duration")) if package.get("duration") else None
    artifact.output = str(package.get("output")) if package.get("output") else None
    artifact.tags = list(package.get("tags", []))
    artifact.current_version = version
    artifact.source_url = package.get("learningPath")
    artifact.metadata_json = package
    artifact.status = "published"
    db.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version=version,
            payload=package,
            content_sha256=preview.content_sha256,
        )
    )
    result = PublishResponse(
        artifact_id=artifact.id,
        version=version,
        scope=artifact.visibility,
        status="published",
        url=_artifact_url(artifact.id),
    )
    preview.status = "published"
    preview.result_json = result.model_dump(mode="json")
    preview.confirmed_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            event_type="artifact_version_created",
            actor_id=actor,
            object_id=artifact.id,
            payload={"preview_id": preview.id, "version": version, "result": result.model_dump(mode="json")},
        )
    )
    if idempotency_key:
        db.add(
            AuditEvent(
                event_type="artifact_version_result",
                actor_id=actor,
                object_id=artifact.id,
                payload={
                    "idempotency_key": idempotency_key,
                    "result": result.model_dump(mode="json"),
                },
            )
        )
    db.commit()
    return result


@app.post("/api/v1/artifacts/{artifact_id:path}/reports", tags=["governance"])
def report_artifact(
    artifact_id: str,
    request: ReportRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=240)],
) -> dict:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    actor = identity.subject
    existing = _audit_idempotent_result(
        db,
        event_type="artifact_reported",
        actor_id=actor,
        object_id=artifact.id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return existing
    if artifact.status != "published" or not _can_read(artifact, identity):
        raise HTTPException(status_code=404, detail="artifact_not_found")
    artifact.status = "reported"
    result = {"artifact_id": artifact.id, "status": "reported", "category": request.category}
    db.add(
        AuditEvent(
            event_type="artifact_reported",
            actor_id=actor,
            object_id=artifact.id,
            payload={
                "category": request.category,
                "reason": request.reason,
                "idempotency_key": idempotency_key,
                "result": result,
            },
        )
    )
    db.commit()
    return result


@app.post("/api/v1/artifacts/{artifact_id:path}/ratings", tags=["governance"])
def rate_artifact(
    artifact_id: str,
    request: RatingRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=240)],
) -> dict:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.status != "published" or not _can_read(artifact, identity):
        raise HTTPException(status_code=404, detail="artifact_not_found")
    actor = identity.subject
    existing = _audit_idempotent_result(
        db,
        event_type="artifact_rated",
        actor_id=actor,
        object_id=artifact.id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return existing
    result = {"artifact_id": artifact.id, "score": request.score, "status": "recorded"}
    db.add(
        AuditEvent(
            event_type="artifact_rated",
            actor_id=actor,
            object_id=artifact.id,
            payload={
                "score": request.score,
                "comment": request.comment,
                "idempotency_key": idempotency_key,
                "result": result,
            },
        )
    )
    db.commit()
    return result


@app.post("/api/v1/artifacts/{artifact_id:path}/rollback", response_model=PublishResponse, tags=["governance"])
def rollback_artifact(
    artifact_id: str,
    request: RollbackRequest,
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=240)],
) -> PublishResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    if not _can_manage_artifact(artifact, identity):
        raise HTTPException(status_code=403, detail="artifact_owner_required")
    previous_version = artifact.current_version
    existing = _audit_idempotent_result(
        db,
        event_type="artifact_rolled_back",
        actor_id=identity.subject,
        object_id=artifact.id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return PublishResponse.model_validate(existing)
    if request.confirmation.confirmed is not True:
        raise HTTPException(status_code=400, detail="explicit_confirmation_required")
    version = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.version == request.version,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="artifact_version_not_found")
    package = version.payload
    artifact.title = str(package.get("name", artifact.title))
    artifact.summary = str(package.get("summary", artifact.summary))
    artifact.category = str(package.get("category")) if package.get("category") else None
    artifact.audience = str(package.get("audience")) if package.get("audience") else None
    artifact.duration = str(package.get("duration")) if package.get("duration") else None
    artifact.output = str(package.get("output")) if package.get("output") else None
    artifact.tags = list(package.get("tags", artifact.tags or []))
    artifact.current_version = version.version
    artifact.source_url = package.get("learningPath")
    artifact.metadata_json = package
    artifact.status = "published"
    result = PublishResponse(
        artifact_id=artifact.id,
        version=version.version,
        scope=artifact.visibility,
        status="published",
        url=_artifact_url(artifact.id),
    )
    db.add(
        AuditEvent(
            event_type="artifact_rolled_back",
            actor_id=identity.subject,
            object_id=artifact.id,
            payload={
                "from_version": previous_version,
                "to_version": version.version,
                "idempotency_key": idempotency_key,
                "result": result.model_dump(mode="json"),
            },
        )
    )
    db.commit()
    return result


MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_WRITE_TOOLS = {
    "registry.publish_preview",
    "registry.publish",
    "registry.update",
    "registry.rate",
    "registry.report",
    "registry.rollback",
    "collab.create_task",
    "collab.send",
    "collab.cancel",
    "collab.verify_artifact",
}


def _mcp_contract() -> dict[str, Any]:
    path = settings.registry_path.parents[2] / "contracts" / "mcp" / "hub-tools.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"properties": {}}
    return payload if isinstance(payload, dict) else {"properties": {}}


def _mcp_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _mcp_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _mcp_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mcp_json(item) for item in value]
    return value


def _mcp_validate_arguments(name: str, arguments: Any) -> dict[str, Any]:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("tool_arguments_must_be_object")
    schema = _mcp_contract().get("properties", {}).get(name)
    if not isinstance(schema, dict):
        raise LookupError("tool_not_found")
    required = schema.get("required", [])
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"missing_required_arguments:{','.join(missing)}")
    if schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ValueError(f"unknown_arguments:{','.join(unknown)}")
    return arguments


def _mcp_require_identity(identity: ActorIdentity | None) -> ActorIdentity:
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="identity_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


def _mcp_tool_result(
    name: str,
    arguments: dict[str, Any],
    *,
    db: Session,
    identity: ActorIdentity | None,
) -> Any:
    if name in MCP_WRITE_TOOLS:
        identity = _mcp_require_identity(identity)
    if name == "registry.search":
        result = list_artifacts(
            db=db,
            identity=identity,
            q=arguments["query"],
            kind=arguments.get("kind"),
            category=None,
            visibility=None,
            limit=arguments.get("limit", 20),
            offset=0,
        )
        tags = {str(item).casefold() for item in arguments.get("tags", [])}
        if tags:
            filtered = [
                item
                for item in result.items
                if tags.intersection({tag.casefold() for tag in item.tags})
            ]
            result = ArtifactListResponse(
                items=filtered,
                total=len(filtered),
                limit=result.limit,
                offset=result.offset,
            )
        return result
    if name == "registry.get":
        return get_artifact(arguments["artifact_id"], db=db, identity=identity)
    if name == "registry.install_plan":
        request = SkillInstallPlanRequest(
            slug=arguments["slug"],
            version=arguments.get("version"),
            target_agent=arguments.get("target_agent", "workbuddy"),
        )
        return create_skill_install_plan(arguments["artifact_id"], request, identity)
    if name == "registry.publish_preview":
        request = PublicationPreviewRequest.model_validate(
            {key: value for key, value in arguments.items() if key != "idempotency_key"}
        )
        return create_publication_preview(
            request, db=db, identity=_mcp_require_identity(identity), idempotency_key=arguments["idempotency_key"]
        )
    if name == "registry.publish":
        request = PublishRequest.model_validate(
            {key: value for key, value in arguments.items() if key != "idempotency_key"}
        )
        return publish_preview(
            request,
            db=db,
            identity=_mcp_require_identity(identity),
            publication_grant=None,
            idempotency_key=arguments["idempotency_key"],
        )
    if name == "registry.update":
        request = VersionUpdateRequest.model_validate(
            {key: value for key, value in arguments.items() if key != "idempotency_key"}
        )
        return publish_artifact_version(
            arguments["artifact_id"],
            request,
            db=db,
            identity=_mcp_require_identity(identity),
            idempotency_key=arguments["idempotency_key"],
        )
    if name == "registry.rate":
        request = RatingRequest.model_validate(
            {key: value for key, value in arguments.items() if key not in {"artifact_id", "idempotency_key"}}
        )
        return rate_artifact(
            arguments["artifact_id"], request, db=db, identity=_mcp_require_identity(identity), idempotency_key=arguments["idempotency_key"]
        )
    if name == "registry.report":
        request = ReportRequest.model_validate(
            {key: value for key, value in arguments.items() if key not in {"artifact_id", "idempotency_key"}}
        )
        return report_artifact(
            arguments["artifact_id"], request, db=db, identity=_mcp_require_identity(identity), idempotency_key=arguments["idempotency_key"]
        )
    if name == "registry.rollback":
        request = RollbackRequest.model_validate(
            {key: value for key, value in arguments.items() if key not in {"artifact_id", "idempotency_key"}}
        )
        return rollback_artifact(
            arguments["artifact_id"], request, db=db, identity=_mcp_require_identity(identity), idempotency_key=arguments["idempotency_key"]
        )
    if name == "collab.teams":
        return list_collaboration_teams(_mcp_require_identity(identity))
    if name == "collab.create_task":
        request = CollaborationTaskRequest.model_validate(
            {key: value for key, value in arguments.items() if key != "idempotency_key"}
        )
        return create_collaboration_task(
            request,
            db=db,
            identity=_mcp_require_identity(identity),
            idempotency_key=arguments["idempotency_key"],
        )
    if name == "collab.status":
        return get_collaboration_task(
            arguments["task_id"], db=db, identity=_mcp_require_identity(identity)
        )
    if name == "collab.events":
        return get_collaboration_events(
            arguments["task_id"],
            db=db,
            identity=_mcp_require_identity(identity),
            cursor=arguments.get("cursor", 0),
        )
    if name == "collab.wait":
        return wait_for_collaboration_task(
            arguments["task_id"],
            db=db,
            identity=_mcp_require_identity(identity),
            cursor=arguments.get("cursor", 0),
            timeout_seconds=arguments.get("timeout_seconds", 20),
        )
    if name == "collab.artifacts":
        return get_collaboration_artifacts(
            arguments["task_id"], db=db, identity=_mcp_require_identity(identity)
        )
    if name == "collab.verify_artifact":
        return verify_collaboration_artifact(
            arguments["task_id"],
            arguments["artifact_id"],
            db=db,
            idempotency_key=arguments["idempotency_key"],
            identity=_mcp_require_identity(identity),
        )
    if name == "collab.send":
        request = CollaborationMessageRequest.model_validate(
            {key: value for key, value in arguments.items() if key not in {"task_id", "idempotency_key"}}
        )
        return send_collaboration_message(
            arguments["task_id"],
            request,
            db=db,
            idempotency_key=arguments["idempotency_key"],
            identity=_mcp_require_identity(identity),
        )
    if name == "collab.cancel":
        return cancel_collaboration_task(
            arguments["task_id"],
            db=db,
            idempotency_key=arguments["idempotency_key"],
            identity=_mcp_require_identity(identity),
        )
    raise LookupError("tool_not_found")


@app.post("/api/v1/mcp", response_model=None, tags=["mcp"])
def mcp_endpoint(
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_db)],
    identity: Annotated[ActorIdentity | None, Depends(get_optional_identity)],
) -> Response | dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        return JSONResponse(status_code=400, content=_mcp_error(request_id, -32600, "invalid_request"))
    method = payload["method"]
    if method == "notifications/initialized" and "id" not in payload:
        return Response(status_code=204)
    if method == "initialize":
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        requested_version = params.get("protocolVersion")
        protocol_version = requested_version if isinstance(requested_version, str) else MCP_PROTOCOL_VERSION
        return _mcp_response(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "workbuddy-hub", "version": app.version},
            },
        )
    if method == "tools/list":
        tools = []
        for name, schema in _mcp_contract().get("properties", {}).items():
            if isinstance(schema, dict):
                tools.append({"name": name, "description": schema.get("description", ""), "inputSchema": schema})
        return _mcp_response(request_id, {"tools": tools})
    if method != "tools/call":
        return _mcp_error(request_id, -32601, "method_not_found")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    name = params.get("name")
    try:
        if not isinstance(name, str):
            raise ValueError("tool_name_required")
        arguments = _mcp_validate_arguments(name, params.get("arguments"))
        value = _mcp_tool_result(name, arguments, db=db, identity=identity)
        structured = _mcp_json(value)
        return _mcp_response(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
                "structuredContent": structured,
                "isError": False,
            },
        )
    except (ValueError, LookupError, ValidationError) as exc:
        return _mcp_response(
            request_id,
            {"content": [{"type": "text", "text": str(exc)}], "isError": True},
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _mcp_response(
            request_id,
            {
                "content": [{"type": "text", "text": detail}],
                "structuredContent": {"status_code": exc.status_code, "detail": detail},
                "isError": True,
            },
        )
