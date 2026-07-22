"""add runtime provider bootstrap foundation

Revision ID: 41c9f7fe1060
Revises: ddbafb0f6ce0
Create Date: 2026-07-22 13:47:09.582234

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "41c9f7fe1060"
down_revision: str | Sequence[str] | None = "ddbafb0f6ce0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_PROVIDER_REGISTRATION_METHOD = postgresql.ENUM(
    "admin",
    "bootstrap",
    name="runtime_provider_registration_method",
    create_type=False,
)
_RUNTIME_PROVIDER_LIFECYCLE_STATE = postgresql.ENUM(
    "active",
    "decommissioning",
    "decommissioned",
    "force_retired",
    name="runtime_provider_lifecycle_state",
    create_type=False,
)
_RUNTIME_PROVIDER_AVAILABILITY_MODE = postgresql.ENUM(
    "platform_wide",
    "selected_workspaces",
    name="runtime_provider_availability_mode",
    create_type=False,
)
_RUNTIME_PROVIDER_BOOTSTRAP_ADAPTER_KIND = postgresql.ENUM(
    "helm_file",
    name="runtime_provider_bootstrap_adapter_kind",
    create_type=False,
)
_RUNTIME_PROVIDER_BOOTSTRAP_DECLARATION_STATE = postgresql.ENUM(
    "present",
    "absent",
    "conflict",
    name="runtime_provider_bootstrap_declaration_state",
    create_type=False,
)
_RUNTIME_PROVIDER_AUDIT_EVENT_TYPE = postgresql.ENUM(
    "registered",
    "bootstrap_reconciled",
    "bootstrap_withdrawn",
    "bootstrap_conflict",
    "enabled",
    "disabled",
    "availability_changed",
    name="runtime_provider_audit_event_type",
    create_type=False,
)
_RUNTIME_PROVIDER_KIND = postgresql.ENUM(
    "kubernetes",
    "docker",
    name="runtime_provider_kind",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in (
        _RUNTIME_PROVIDER_REGISTRATION_METHOD,
        _RUNTIME_PROVIDER_LIFECYCLE_STATE,
        _RUNTIME_PROVIDER_AVAILABILITY_MODE,
        _RUNTIME_PROVIDER_BOOTSTRAP_ADAPTER_KIND,
        _RUNTIME_PROVIDER_BOOTSTRAP_DECLARATION_STATE,
        _RUNTIME_PROVIDER_AUDIT_EVENT_TYPE,
    ):
        enum_type.create(bind, checkfirst=True)

    op.add_column(
        "runtime_providers",
        sa.Column(
            "registration_method",
            _RUNTIME_PROVIDER_REGISTRATION_METHOD,
            server_default=sa.text("'admin'"),
            nullable=False,
        ),
    )
    op.add_column(
        "runtime_providers",
        sa.Column(
            "lifecycle_state",
            _RUNTIME_PROVIDER_LIFECYCLE_STATE,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.add_column(
        "runtime_providers",
        sa.Column(
            "availability_mode",
            _RUNTIME_PROVIDER_AVAILABILITY_MODE,
            server_default=sa.text("'platform_wide'"),
            nullable=False,
        ),
    )
    op.add_column(
        "runtime_providers",
        sa.Column(
            "admin_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_runtime_providers_lifecycle_enabled",
        "runtime_providers",
        ["lifecycle_state", "enabled"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_bootstrap_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column(
            "adapter_kind",
            _RUNTIME_PROVIDER_BOOTSTRAP_ADAPTER_KIND,
            nullable=False,
        ),
        sa.Column("last_revision", sa.String(length=255), nullable=True),
        sa.Column("last_digest", sa.String(length=64), nullable=True),
        sa.Column("last_reconciled_at", TimeZoneDateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key",
            name="uq_runtime_provider_bootstrap_sources_source_key",
        ),
    )
    op.create_index(
        "ix_runtime_provider_bootstrap_sources_adapter_kind",
        "runtime_provider_bootstrap_sources",
        ["adapter_kind"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_bootstrap_declarations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("provider_logical_id", sa.String(length=120), nullable=False),
        sa.Column("kind", _RUNTIME_PROVIDER_KIND, nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=True),
        sa.Column("declaration_key", sa.String(length=255), nullable=False),
        sa.Column("source_revision", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            _RUNTIME_PROVIDER_BOOTSTRAP_DECLARATION_STATE,
            nullable=False,
        ),
        sa.Column(
            "creation_seeds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("conflict_code", sa.String(length=120), nullable=True),
        sa.Column("conflict_message", sa.Text(), nullable=True),
        sa.Column("last_seen_at", TimeZoneDateTime(), nullable=True),
        sa.Column("withdrawn_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["runtime_provider_bootstrap_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            name="uq_runtime_provider_bootstrap_declarations_provider_id",
        ),
        sa.UniqueConstraint(
            "source_id",
            "declaration_key",
            name="uq_runtime_provider_bootstrap_declarations_source_key",
        ),
    )

    op.create_table(
        "runtime_provider_workspace_availability",
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("provider_id", "workspace_id"),
    )
    op.create_index(
        "ix_runtime_provider_workspace_availability_workspace_id",
        "runtime_provider_workspace_availability",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", _RUNTIME_PROVIDER_AUDIT_EVENT_TYPE, nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_provider_audit_events_provider_created",
        "runtime_provider_audit_events",
        ["provider_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("runtime_provider_audit_events")
    op.drop_table("runtime_provider_workspace_availability")
    op.drop_table("runtime_provider_bootstrap_declarations")
    op.drop_table("runtime_provider_bootstrap_sources")
    op.drop_index(
        "ix_runtime_providers_lifecycle_enabled",
        table_name="runtime_providers",
    )
    op.drop_column("runtime_providers", "admin_version")
    op.drop_column("runtime_providers", "availability_mode")
    op.drop_column("runtime_providers", "lifecycle_state")
    op.drop_column("runtime_providers", "registration_method")

    bind = op.get_bind()
    for enum_type in (
        _RUNTIME_PROVIDER_AUDIT_EVENT_TYPE,
        _RUNTIME_PROVIDER_BOOTSTRAP_DECLARATION_STATE,
        _RUNTIME_PROVIDER_BOOTSTRAP_ADAPTER_KIND,
        _RUNTIME_PROVIDER_AVAILABILITY_MODE,
        _RUNTIME_PROVIDER_LIFECYCLE_STATE,
        _RUNTIME_PROVIDER_REGISTRATION_METHOD,
    ):
        enum_type.drop(bind, checkfirst=True)
