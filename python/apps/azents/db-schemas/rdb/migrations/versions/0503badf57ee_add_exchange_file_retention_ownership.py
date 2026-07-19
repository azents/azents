"""add exchange file retention ownership

Revision ID: 0503badf57ee
Revises: 653ef7db49af
Create Date: 2026-07-19 13:53:53.596114

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0503badf57ee"
down_revision: str | Sequence[str] | None = "653ef7db49af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "exchange_files",
        sa.Column("retention_root_session_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column(
            "retention_bound_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_exchange_files_retention_root_session_id_agent_sessions",
        "exchange_files",
        "agent_sessions",
        ["retention_root_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_exchange_files_retention_root_status",
        "exchange_files",
        ["retention_root_session_id", "status", "id"],
        unique=False,
        postgresql_where=sa.text("retention_root_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_exchange_files_retention_root_status",
        table_name="exchange_files",
        postgresql_where=sa.text("retention_root_session_id IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_exchange_files_retention_root_session_id_agent_sessions",
        "exchange_files",
        type_="foreignkey",
    )
    op.drop_column("exchange_files", "retention_bound_at")
    op.drop_column("exchange_files", "retention_root_session_id")
