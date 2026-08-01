"""Add External Channel participation foundation."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from alembic_postgresql_enum import TableReference
from sqlalchemy.dialects import postgresql

revision: str = "772e7ab22a8e"
down_revision: str | Sequence[str] | None = "d0a55d801644"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONVERSATION_LOCATION_ENUM = postgresql.ENUM(
    "channel",
    "threads",
    name="external_channel_conversation_location",
    create_type=False,
)
_PARTICIPATION_SETTING_STATUS_ENUM = postgresql.ENUM(
    "active",
    "invalidated",
    name="external_channel_participation_setting_status",
    create_type=False,
)
_SETUP_CLAIM_STATUS_ENUM = postgresql.ENUM(
    "pending_agent",
    "pending_location",
    "selected",
    "completed",
    "expired",
    "invalidated",
    name="external_channel_setup_claim_status",
    create_type=False,
)
_RESPONSE_MODE_ENUM = postgresql.ENUM(
    "mention_only",
    "all_messages",
    name="external_channel_response_mode",
    create_type=False,
)


def _create_enum_types() -> None:
    """Create PostgreSQL enum types owned by this migration."""
    bind = op.get_bind()
    for enum_type in (
        _CONVERSATION_LOCATION_ENUM,
        _PARTICIPATION_SETTING_STATUS_ENUM,
        _SETUP_CLAIM_STATUS_ENUM,
    ):
        enum_type.create(bind)


def _drop_enum_types() -> None:
    """Drop PostgreSQL enum types owned by this migration."""
    bind = op.get_bind()
    for enum_type in (
        _SETUP_CLAIM_STATUS_ENUM,
        _PARTICIPATION_SETTING_STATUS_ENUM,
        _CONVERSATION_LOCATION_ENUM,
    ):
        enum_type.drop(bind)


def _expand_existing_enum_types() -> None:
    """Add read-compatible values to enum types owned by earlier migrations."""
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="external_channel_resource_type",
        new_values=["parent_channel", "thread"],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="external_channel_resources",
                column_name="resource_type",
            )
        ],
        enum_values_to_rename=[],
    )
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="external_channel_delivery_origin_type",
        new_values=[
            "channel_action",
            "access_request",
            "setup_claim",
            "binding_disconnect",
            "connection_disconnect",
            "binding_settings_available",
            "manager_operation",
        ],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="external_channel_delivery_attempts",
                column_name="origin_type",
            )
        ],
        enum_values_to_rename=[],
    )


def _restore_existing_enum_types() -> None:
    """Restore enum types owned by earlier migrations after absence checks."""
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="external_channel_delivery_origin_type",
        new_values=[
            "channel_action",
            "access_request",
            "binding_disconnect",
            "connection_disconnect",
            "manager_operation",
        ],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="external_channel_delivery_attempts",
                column_name="origin_type",
            )
        ],
        enum_values_to_rename=[],
    )
    op.sync_enum_values(  # pyright: ignore[reportAttributeAccessIssue] # alembic_postgresql_enum extension
        enum_schema="public",
        enum_name="external_channel_resource_type",
        new_values=["thread"],
        affected_columns=[
            TableReference(
                table_schema="public",
                table_name="external_channel_resources",
                column_name="resource_type",
            )
        ],
        enum_values_to_rename=[],
    )


def _abort_unsafe_downgrade() -> None:
    """Reject downgrade after participation-only state has been written."""
    unsafe = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
                SELECT 1 FROM external_channel_participation_settings
            ) OR EXISTS (
                SELECT 1 FROM external_channel_setup_claims
            ) OR EXISTS (
                SELECT 1 FROM external_channel_channel_defaults
                WHERE configured_by_principal_id IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM external_channel_resources
                WHERE resource_type = 'parent_channel'
            ) OR EXISTS (
                SELECT 1 FROM external_channel_delivery_attempts
                WHERE origin_type IN ('setup_claim', 'binding_settings_available')
            )
            """
            )
        )
        .scalar_one()
    )
    if unsafe:
        raise RuntimeError(
            "Cannot downgrade after External Channel participation state is written."
        )


def upgrade() -> None:
    """Upgrade schema with disabled, read-compatible participation state."""
    _create_enum_types()
    _expand_existing_enum_types()

    op.add_column(
        "external_channel_channel_defaults",
        sa.Column("configured_by_principal_id", sa.String(length=32), nullable=True),
    )
    op.alter_column(
        "external_channel_channel_defaults",
        "configured_by_user_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_external_channel_channel_defaults_configured_principal",
        "external_channel_channel_defaults",
        "external_channel_principals",
        ["configured_by_principal_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_external_channel_channel_defaults_configured_actor",
        "external_channel_channel_defaults",
        "num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1",
    )

    op.create_table(
        "external_channel_participation_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("provider_parent_channel_id", sa.String(length=255), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("location", _CONVERSATION_LOCATION_ENUM, nullable=False),
        sa.Column("response_mode", _RESPONSE_MODE_ENUM, nullable=False),
        sa.Column("settings_generation", sa.Integer(), nullable=False),
        sa.Column("status", _PARTICIPATION_SETTING_STATUS_ENUM, nullable=False),
        sa.Column("configured_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("configured_by_principal_id", sa.String(length=32), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(configured_by_user_id, configured_by_principal_id) = 1",
            name="ck_external_channel_participation_settings_configured_actor",
        ),
        sa.CheckConstraint(
            "settings_generation > 0",
            name="ck_external_channel_participation_settings_positive_generation",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND invalidated_at IS NULL "
            "AND invalidation_reason IS NULL) OR "
            "(status = 'invalidated' AND invalidated_at IS NOT NULL "
            "AND invalidation_reason IS NOT NULL)",
            name="ck_external_channel_participation_invalidation_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["configured_by_user_id"],
            ["users.id"],
            name="fk_external_channel_participation_configured_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["configured_by_principal_id"],
            ["external_channel_principals.id"],
            name="fk_external_channel_participation_configured_principal",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "route_id"],
            [
                "external_channel_agent_routes.connection_id",
                "external_channel_agent_routes.id",
            ],
            name="fk_external_channel_participation_settings_connection_route",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "id",
            name="uq_external_channel_participation_settings_connection_id_id",
        ),
    )
    op.create_index(
        "ix_external_channel_participation_settings_route_id_status",
        "external_channel_participation_settings",
        ["route_id", "status"],
    )
    op.create_index(
        "uq_external_channel_participation_active_channel",
        "external_channel_participation_settings",
        ["connection_id", "provider_parent_channel_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "external_channel_setup_claims",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("provider_parent_channel_id", sa.String(length=255), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=True),
        sa.Column("conversation_position_id", sa.String(length=32), nullable=False),
        sa.Column("source_resource_id", sa.String(length=32), nullable=False),
        sa.Column("principal_id", sa.String(length=32), nullable=False),
        sa.Column("source_projection", postgresql.JSONB(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("claim_generation", sa.Integer(), nullable=False),
        sa.Column("status", _SETUP_CLAIM_STATUS_ENUM, nullable=False),
        sa.Column("selected_setting_id", sa.String(length=32), nullable=True),
        sa.Column("selected_resource_id", sa.String(length=32), nullable=True),
        sa.Column("selected_source_revision", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_revision > 0 AND claim_generation > 0",
            name="ck_external_channel_setup_claims_positive_revisions",
        ),
        sa.CheckConstraint(
            "selected_source_revision IS NULL OR "
            "(selected_source_revision > 0 "
            "AND selected_source_revision <= source_revision)",
            name="ck_external_channel_setup_claims_selected_source_revision",
        ),
        sa.CheckConstraint(
            "(status IN ('pending_agent', 'pending_location') "
            "AND selected_setting_id IS NULL "
            "AND selected_resource_id IS NULL "
            "AND selected_source_revision IS NULL "
            "AND selected_at IS NULL) OR "
            "(status IN ('selected', 'completed') "
            "AND selected_setting_id IS NOT NULL "
            "AND selected_resource_id IS NOT NULL "
            "AND selected_source_revision IS NOT NULL "
            "AND selected_at IS NOT NULL) OR "
            "status IN ('expired', 'invalidated')",
            name="ck_external_channel_setup_claims_selection_metadata",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) "
            "OR status <> 'completed'",
            name="ck_external_channel_setup_claims_completed_at",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "conversation_position_id"],
            [
                "external_channel_conversation_positions.connection_id",
                "external_channel_conversation_positions.id",
            ],
            name="fk_external_channel_setup_claims_connection_position",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "route_id"],
            [
                "external_channel_agent_routes.connection_id",
                "external_channel_agent_routes.id",
            ],
            name="fk_external_channel_setup_claims_connection_route",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "source_resource_id"],
            [
                "external_channel_resources.connection_id",
                "external_channel_resources.id",
            ],
            name="fk_external_channel_setup_claims_connection_source_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "selected_setting_id"],
            [
                "external_channel_participation_settings.connection_id",
                "external_channel_participation_settings.id",
            ],
            name="fk_external_channel_setup_claims_connection_selected_setting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "selected_resource_id"],
            [
                "external_channel_resources.connection_id",
                "external_channel_resources.id",
            ],
            name="fk_external_channel_setup_claims_connection_selected_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["external_channel_principals.id"],
            name="fk_external_channel_setup_claims_principal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "id",
            name="uq_external_channel_setup_claims_connection_id_id",
        ),
    )
    op.create_index(
        "ix_external_channel_setup_claims_route_id_status",
        "external_channel_setup_claims",
        ["route_id", "status"],
    )
    op.create_index(
        "ix_external_channel_setup_claims_status_expires_at",
        "external_channel_setup_claims",
        ["status", "expires_at"],
    )
    op.create_index(
        "uq_external_channel_setup_claims_nonterminal_connection_channel",
        "external_channel_setup_claims",
        ["connection_id", "provider_parent_channel_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_agent', 'pending_location', 'selected')"
        ),
    )

    op.add_column(
        "external_channel_interactions",
        sa.Column("setup_claim_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_external_channel_interactions_setup_claim",
        "external_channel_interactions",
        "external_channel_setup_claims",
        ["setup_claim_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_external_channel_interactions_setup_claim_id",
        "external_channel_interactions",
        ["setup_claim_id"],
    )

    op.add_column(
        "external_channel_access_requests",
        sa.Column("setup_claim_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_external_channel_access_requests_setup_claim",
        "external_channel_access_requests",
        "external_channel_setup_claims",
        ["setup_claim_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_external_channel_access_requests_setup_claim_id",
        "external_channel_access_requests",
        ["setup_claim_id"],
    )


def downgrade() -> None:
    """Downgrade before participation-only state is written."""
    _abort_unsafe_downgrade()

    op.drop_index(
        "ix_external_channel_access_requests_setup_claim_id",
        table_name="external_channel_access_requests",
    )
    op.drop_constraint(
        "fk_external_channel_access_requests_setup_claim",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_column("external_channel_access_requests", "setup_claim_id")

    op.drop_index(
        "ix_external_channel_interactions_setup_claim_id",
        table_name="external_channel_interactions",
    )
    op.drop_constraint(
        "fk_external_channel_interactions_setup_claim",
        "external_channel_interactions",
        type_="foreignkey",
    )
    op.drop_column("external_channel_interactions", "setup_claim_id")

    op.drop_index(
        "uq_external_channel_setup_claims_nonterminal_connection_channel",
        table_name="external_channel_setup_claims",
    )
    op.drop_index(
        "ix_external_channel_setup_claims_status_expires_at",
        table_name="external_channel_setup_claims",
    )
    op.drop_index(
        "ix_external_channel_setup_claims_route_id_status",
        table_name="external_channel_setup_claims",
    )
    op.drop_table("external_channel_setup_claims")

    op.drop_index(
        "uq_external_channel_participation_active_channel",
        table_name="external_channel_participation_settings",
    )
    op.drop_index(
        "ix_external_channel_participation_settings_route_id_status",
        table_name="external_channel_participation_settings",
    )
    op.drop_table("external_channel_participation_settings")

    op.drop_constraint(
        "ck_external_channel_channel_defaults_configured_actor",
        "external_channel_channel_defaults",
        type_="check",
    )
    op.drop_constraint(
        "fk_external_channel_channel_defaults_configured_principal",
        "external_channel_channel_defaults",
        type_="foreignkey",
    )
    op.drop_column(
        "external_channel_channel_defaults",
        "configured_by_principal_id",
    )
    op.alter_column(
        "external_channel_channel_defaults",
        "configured_by_user_id",
        existing_type=sa.String(length=32),
        nullable=False,
    )

    _restore_existing_enum_types()
    _drop_enum_types()
