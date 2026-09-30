"""Retire the independent External Channel inbound policy."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "43a0fbdc96fe"
down_revision: str | Sequence[str] | None = "0c18705eb6cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove only inbound authority, preserving every stored outbound value."""
    op.execute(
        sa.text(
            "UPDATE system_settings "
            "SET config = config - 'inbound_max_file_bytes', schema_version = 2, "
            "version = version + 1, validated_generation = NULL, "
            "validation_status = NULL, validation_metadata = NULL, validated_at = NULL "
            "WHERE section = 'external_channel_files'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE system_setting_candidates "
            "SET config = config - 'inbound_max_file_bytes', schema_version = 2 "
            "WHERE section = 'external_channel_files'"
        )
    )


def downgrade() -> None:
    """Restore the old shape without silently restoring 500 MiB eligibility."""
    for table in ("system_settings", "system_setting_candidates"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET config = config || "
                "'{\"inbound_max_file_bytes\": 134217728}'::jsonb, schema_version = 1 "
                "WHERE section = 'external_channel_files'"
            )
        )
