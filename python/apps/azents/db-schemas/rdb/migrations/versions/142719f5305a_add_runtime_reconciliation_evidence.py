"""add runtime reconciliation evidence

Revision ID: 142719f5305a
Revises: 155e9db4ee7e
Create Date: 2026-08-04 15:34:40.614420

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "142719f5305a"
down_revision: str | Sequence[str] | None = "155e9db4ee7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("in_sync", "drifted", name="runtime_provider_reconciliation_status").create(
        op.get_bind()
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_status",
            postgresql.ENUM(
                "in_sync",
                "drifted",
                name="runtime_provider_reconciliation_status",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("provider_reconciliation_kind", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_reason", sa.String(length=256), nullable=True
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_provider_generation", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_observed_generation", sa.Integer(), nullable=True
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_configuration_revision_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_observed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_reconciliation_requested_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_runtimes_provider_reconciliation",
        "agent_runtimes",
        ["provider_reconciliation_status", "provider_reconciliation_kind"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_agent_runtimes_reconciliation_revision_id",
        "agent_runtimes",
        "runtime_configuration_revisions",
        ["provider_reconciliation_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_agent_runtimes_reconciliation_revision_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_agent_runtimes_provider_reconciliation", table_name="agent_runtimes"
    )
    op.drop_column("agent_runtimes", "provider_reconciliation_requested_at")
    op.drop_column("agent_runtimes", "provider_reconciliation_observed_at")
    op.drop_column(
        "agent_runtimes", "provider_reconciliation_configuration_revision_id"
    )
    op.drop_column("agent_runtimes", "provider_reconciliation_observed_generation")
    op.drop_column("agent_runtimes", "provider_reconciliation_provider_generation")
    op.drop_column("agent_runtimes", "provider_reconciliation_reason")
    op.drop_column("agent_runtimes", "provider_reconciliation_kind")
    op.drop_column("agent_runtimes", "provider_reconciliation_status")
    sa.Enum("in_sync", "drifted", name="runtime_provider_reconciliation_status").drop(
        op.get_bind()
    )
