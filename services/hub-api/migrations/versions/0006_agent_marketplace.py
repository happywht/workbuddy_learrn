"""Add the lightweight Agent registry and task marketplace."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_agent_marketplace"
down_revision = "0005_publication_scan_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.String(length=1000)),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("owner_id", sa.String(length=160)),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_agent_name"),
    )
    op.create_table(
        "marketplace_task",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("owner_agent_id", sa.String(length=100), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("claimed_by_agent_id", sa.String(length=100), sa.ForeignKey("agent.id")),
        sa.Column("submission", sa.JSON()),
        sa.Column("evaluation", sa.JSON()),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_marketplace_task_status_visibility", "marketplace_task", ["status", "visibility"])
    op.create_index("ix_marketplace_task_owner", "marketplace_task", ["owner_agent_id"])
    op.create_table(
        "marketplace_task_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=100), sa.ForeignKey("marketplace_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("agent_id", sa.String(length=100)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("marketplace_task_event")
    op.drop_index("ix_marketplace_task_owner", table_name="marketplace_task")
    op.drop_index("ix_marketplace_task_status_visibility", table_name="marketplace_task")
    op.drop_table("marketplace_task")
    op.drop_table("agent")
