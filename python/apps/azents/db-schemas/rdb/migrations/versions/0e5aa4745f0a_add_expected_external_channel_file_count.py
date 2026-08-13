"""Add expected External Channel file count."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0e5aa4745f0a"
down_revision: str | Sequence[str] | None = "6e0b87045f7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist callback-observed file counts for durable ingress retries."""
    op.add_column(
        "external_channel_ingress_items",
        sa.Column("expected_file_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_external_channel_ingress_items_expected_file_count",
        "external_channel_ingress_items",
        "expected_file_count IS NULL OR "
        "(expected_file_count >= 0 AND expected_file_count <= 20)",
    )


def downgrade() -> None:
    """Remove callback-observed file count state."""
    op.drop_constraint(
        "ck_external_channel_ingress_items_expected_file_count",
        "external_channel_ingress_items",
        type_="check",
    )
    op.drop_column("external_channel_ingress_items", "expected_file_count")
