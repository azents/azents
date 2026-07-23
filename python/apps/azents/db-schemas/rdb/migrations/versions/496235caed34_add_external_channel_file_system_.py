"""add external channel file system setting section"""

from typing import Sequence

from alembic import op

revision: str = "496235caed34"
down_revision: str | Sequence[str] | None = "ae769da63fed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the External Channel file-transfer System Settings section."""
    op.execute(
        "ALTER TYPE system_setting_section "
        "ADD VALUE IF NOT EXISTS 'external_channel_files'"
    )


def downgrade() -> None:
    """Retain the PostgreSQL enum value on downgrade."""
    pass
