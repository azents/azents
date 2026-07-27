"""remove runtime execution platform policy

Revision ID: 8ee8f5ae5a4d
Revises: 19f9c6124382
Create Date: 2026-07-27 12:13:17.118076

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8ee8f5ae5a4d"
down_revision: str | Sequence[str] | None = "19f9c6124382"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DELETE FROM runtime_execution_policy_audit_events "
        "WHERE management_layer = 'platform'"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN event_type TYPE text USING event_type::text"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN management_layer TYPE text USING management_layer::text"
    )
    op.execute("DROP TYPE runtime_execution_audit_event_type")
    op.execute("DROP TYPE runtime_execution_management_layer")
    op.execute(
        "CREATE TYPE runtime_execution_audit_event_type AS ENUM ("
        "'profile_created', 'profile_replaced', 'profile_retired', "
        "'workspace_policy_replaced', 'agent_settings_replaced', "
        "'target_snapshot_attached', 'applied_snapshot_promoted')"
    )
    op.execute(
        "CREATE TYPE runtime_execution_management_layer AS ENUM ("
        "'profile', 'workspace', 'agent', 'runtime')"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN event_type TYPE runtime_execution_audit_event_type "
        "USING event_type::runtime_execution_audit_event_type"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN management_layer TYPE runtime_execution_management_layer "
        "USING management_layer::runtime_execution_management_layer"
    )
    op.drop_column("runtime_policy_snapshots", "execution_platform_version")
    op.drop_index(
        "ix_runtime_execution_platform_policies_updated_by_user_id",
        table_name="runtime_execution_platform_policies",
    )
    op.drop_table("runtime_execution_platform_policies")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "runtime_execution_platform_policies",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=32), nullable=True),
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
        sa.CheckConstraint(
            "id = 'platform'",
            name="ck_runtime_execution_platform_policies_singleton_id",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_runtime_execution_platform_policies_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_execution_platform_policies_updated_by_user_id",
        "runtime_execution_platform_policies",
        ["updated_by_user_id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO runtime_execution_platform_policies "
        "(id, version, policy, digest, updated_by_user_id, created_at, updated_at) "
        "SELECT 'platform', version, policy, digest, updated_by_user_id, "
        "created_at, updated_at FROM runtime_execution_profiles "
        "WHERE id = 'system-standard'"
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_platform_version", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE runtime_policy_snapshots SET execution_platform_version = "
        "execution_profile_version WHERE execution_profile_version IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN event_type TYPE text USING event_type::text"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN management_layer TYPE text USING management_layer::text"
    )
    op.execute("DROP TYPE runtime_execution_audit_event_type")
    op.execute("DROP TYPE runtime_execution_management_layer")
    op.execute(
        "CREATE TYPE runtime_execution_audit_event_type AS ENUM ("
        "'platform_policy_replaced', 'profile_created', 'profile_replaced', "
        "'profile_retired', 'workspace_policy_replaced', "
        "'agent_settings_replaced', 'target_snapshot_attached', "
        "'applied_snapshot_promoted')"
    )
    op.execute(
        "CREATE TYPE runtime_execution_management_layer AS ENUM ("
        "'platform', 'profile', 'workspace', 'agent', 'runtime')"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN event_type TYPE runtime_execution_audit_event_type "
        "USING event_type::runtime_execution_audit_event_type"
    )
    op.execute(
        "ALTER TABLE runtime_execution_policy_audit_events "
        "ALTER COLUMN management_layer TYPE runtime_execution_management_layer "
        "USING management_layer::runtime_execution_management_layer"
    )
