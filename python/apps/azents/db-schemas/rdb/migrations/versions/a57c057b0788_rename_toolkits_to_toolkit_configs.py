"""rename toolkits to toolkit_configs

Revision ID: a57c057b0788
Revises: bfbf8c91d809
Create Date: 2026-03-12 03:20:48.190073

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

from alembic import op

revision: str = "a57c057b0788"
down_revision: str | Sequence[str] | None = "bfbf8c91d809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename the toolkits table to toolkit_configs."""
    op.rename_table("toolkits", "toolkit_configs")

    op.execute(
        "ALTER INDEX ix_toolkits_workspace_id RENAME TO ix_toolkit_configs_workspace_id"
    )
    op.execute(
        "ALTER TABLE toolkit_configs "
        "RENAME CONSTRAINT uq_toolkits_workspace_slug "
        "TO uq_toolkit_configs_workspace_slug"
    )


def downgrade() -> None:
    """Rename the toolkit_configs table back to toolkits."""
    op.execute(
        "ALTER TABLE toolkit_configs "
        "RENAME CONSTRAINT uq_toolkit_configs_workspace_slug "
        "TO uq_toolkits_workspace_slug"
    )
    op.execute(
        "ALTER INDEX ix_toolkit_configs_workspace_id RENAME TO ix_toolkits_workspace_id"
    )

    op.rename_table("toolkit_configs", "toolkits")
