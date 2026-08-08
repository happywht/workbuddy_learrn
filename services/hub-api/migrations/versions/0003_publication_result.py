"""Persist successful publication responses for idempotent retries."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_publication_result"
down_revision = "0002_collab_artifact_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publication_preview", sa.Column("result_json", sa.JSON()))


def downgrade() -> None:
    op.drop_column("publication_preview", "result_json")
