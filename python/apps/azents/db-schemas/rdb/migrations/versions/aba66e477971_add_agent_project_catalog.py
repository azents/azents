"""add agent project catalog

Revision ID: aba66e477971
Revises: 6fdebb212632
Create Date: 2026-07-03 09:04:11.963955

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "aba66e477971"
down_revision: str | Sequence[str] | None = "6fdebb212632"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROJECT_CATALOG_STATUSES = (
    "unchecked",
    "available",
    "missing",
    "unavailable",
    "error",
)


def upgrade() -> None:
    """Upgrade schema."""
    catalog_status = postgresql.ENUM(
        *PROJECT_CATALOG_STATUSES,
        name="agent_project_catalog_status",
    )
    catalog_status.create(op.get_bind(), checkfirst=True)
    catalog_status_column = postgresql.ENUM(
        *PROJECT_CATALOG_STATUSES,
        name="agent_project_catalog_status",
        create_type=False,
    )
    op.create_table(
        "agent_project_catalog_entries",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "status",
            catalog_status_column,
            server_default="unchecked",
            nullable=False,
        ),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "path",
            name="uq_agent_project_catalog_entries_agent_path",
        ),
    )
    op.create_index(
        "ix_agent_project_catalog_entries_agent_updated",
        "agent_project_catalog_entries",
        ["agent_id", "updated_at"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_project_catalog_entries (
                id,
                agent_id,
                path,
                status,
                status_detail,
                checked_at,
                created_at,
                updated_at
            )
            SELECT
                md5(agent_id || ':' || path),
                agent_id,
                path,
                'unchecked'::agent_project_catalog_status,
                NULL,
                NULL,
                created_at,
                updated_at
            FROM agent_project_presets
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_project_catalog_entries_agent_updated",
        table_name="agent_project_catalog_entries",
    )
    op.drop_table("agent_project_catalog_entries")
    postgresql.ENUM(name="agent_project_catalog_status").drop(
        op.get_bind(),
        checkfirst=True,
    )
