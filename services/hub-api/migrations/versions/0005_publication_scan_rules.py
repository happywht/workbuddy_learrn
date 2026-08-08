"""Persist the publication scan rule version used for each preview."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_publication_scan_rules"
down_revision = "0004_publication_idempotency_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publication_preview",
        sa.Column("scan_rules_version", sa.String(length=40)),
    )


def downgrade() -> None:
    op.drop_column("publication_preview", "scan_rules_version")
