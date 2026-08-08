"""Add persisted collaboration artifact verification results."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_collab_artifact_verify"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collaboration_artifact_verification",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.String(length=100),
            sa.ForeignKey("collaboration_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("claimed_sha256", sa.String(length=64)),
        sa.Column("actual_sha256", sa.String(length=64)),
        sa.Column("claimed_size", sa.Integer()),
        sa.Column("actual_size", sa.Integer()),
        sa.Column("declared_media_type", sa.String(length=160)),
        sa.Column("response_media_type", sa.String(length=160)),
        sa.Column("detected_media_type", sa.String(length=160)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "artifact_id", name="uq_collab_artifact_verification"),
    )
    op.create_index(
        "ix_collab_artifact_verification_status",
        "collaboration_artifact_verification",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collab_artifact_verification_status",
        table_name="collaboration_artifact_verification",
    )
    op.drop_table("collaboration_artifact_verification")
