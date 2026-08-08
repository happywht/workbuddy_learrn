"""Persist publication preview idempotency keys."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_publication_idempotency_key"
down_revision = "0003_publication_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publication_preview", sa.Column("idempotency_key", sa.String(length=240)))
    op.create_index(
        "uq_publication_preview_actor_idempotency",
        "publication_preview",
        ["actor_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_publication_preview_actor_idempotency",
        "publication_preview",
    )
    op.drop_column("publication_preview", "idempotency_key")
