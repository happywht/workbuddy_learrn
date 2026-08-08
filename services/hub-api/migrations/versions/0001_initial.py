"""Initial Hub catalog, publication, collaboration and audit schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_id", sa.String(length=160)),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80)),
        sa.Column("audience", sa.String(length=240)),
        sa.Column("duration", sa.String(length=80)),
        sa.Column("output", sa.String(length=240)),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=160)),
        sa.Column("department_id", sa.String(length=160)),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_version", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.String(length=1000)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifact_kind_status", "artifact", ["kind", "status"])
    op.create_index("ix_artifact_category", "artifact", ["category"])
    op.create_table(
        "artifact_version",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("artifact_id", sa.String(length=80), sa.ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),
    )
    op.create_table(
        "publication_preview",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("requested_scope", sa.String(length=30), nullable=False),
        sa.Column("target_department_id", sa.String(length=160)),
        sa.Column("package_json", sa.JSON(), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("allowed_scopes", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.String(length=160)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=160)),
        sa.Column("object_id", sa.String(length=160)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "collaboration_task",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("team_id", sa.String(length=160), nullable=False),
        sa.Column("external_task_id", sa.String(length=240)),
        sa.Column("room_id", sa.String(length=240)),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("output_contract", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_event_cursor", sa.String(length=240)),
        sa.Column("idempotency_key", sa.String(length=240)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_collab_task_idempotency"),
    )
    op.create_index("ix_collab_task_actor_status", "collaboration_task", ["actor_id", "status"])
    op.create_table(
        "collaboration_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=100), sa.ForeignKey("collaboration_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("external_cursor", sa.String(length=240)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "external_cursor", name="uq_collab_event_cursor"),
    )


def downgrade() -> None:
    op.drop_table("collaboration_event")
    op.drop_index("ix_collab_task_actor_status", table_name="collaboration_task")
    op.drop_table("collaboration_task")
    op.drop_table("audit_event")
    op.drop_table("publication_preview")
    op.drop_table("artifact_version")
    op.drop_index("ix_artifact_category", table_name="artifact")
    op.drop_index("ix_artifact_kind_status", table_name="artifact")
    op.drop_table("artifact")
