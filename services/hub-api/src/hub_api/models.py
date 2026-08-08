from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Artifact(Base):
    __tablename__ = "artifact"
    __table_args__ = (
        Index("ix_artifact_kind_status", "kind", "status"),
        Index("ix_artifact_category", "category"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="case")
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="hub-case")
    provider_id: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    audience: Mapped[str | None] = mapped_column(String(240))
    duration: Mapped[str | None] = mapped_column(String(80))
    output: Mapped[str | None] = mapped_column(String(240))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="public")
    owner_id: Mapped[str | None] = mapped_column(String(160))
    department_id: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="published")
    current_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0.0")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    versions: Mapped[list["ArtifactVersion"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan", order_by="ArtifactVersion.created_at"
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_version"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    artifact: Mapped[Artifact] = relationship(back_populates="versions")


class PublicationPreview(Base):
    __tablename__ = "publication_preview"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    target_department_id: Mapped[str | None] = mapped_column(String(160))
    package_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed_scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="preview_validated")
    actor_id: Mapped[str | None] = mapped_column(String(160))
    idempotency_key: Mapped[str | None] = mapped_column(String(240))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scan_rules_version: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(160))
    object_id: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CollaborationTask(Base):
    __tablename__ = "collaboration_task"
    __table_args__ = (
        Index("ix_collab_task_actor_status", "actor_id", "status"),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_collab_task_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    team_id: Mapped[str] = mapped_column(String(160), nullable=False)
    external_task_id: Mapped[str | None] = mapped_column(String(240))
    room_id: Mapped[str | None] = mapped_column(String(240))
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_contract: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    last_event_cursor: Mapped[str | None] = mapped_column(String(240))
    idempotency_key: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CollaborationEvent(Base):
    __tablename__ = "collaboration_event"
    __table_args__ = (UniqueConstraint("task_id", "external_cursor", name="uq_collab_event_cursor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("collaboration_task.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    external_cursor: Mapped[str | None] = mapped_column(String(240))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CollaborationArtifactVerification(Base):
    __tablename__ = "collaboration_artifact_verification"
    __table_args__ = (
        UniqueConstraint("task_id", "artifact_id", name="uq_collab_artifact_verification"),
        Index("ix_collab_artifact_verification_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("collaboration_task.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    claimed_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    claimed_size: Mapped[int | None] = mapped_column(Integer)
    actual_size: Mapped[int | None] = mapped_column(Integer)
    declared_media_type: Mapped[str | None] = mapped_column(String(160))
    response_media_type: Mapped[str | None] = mapped_column(String(160))
    detected_media_type: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(100))
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
