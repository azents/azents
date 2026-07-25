"""Add External Channel App mode foundation."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "00ae8d1fd42c"
down_revision: str | Sequence[str] | None = "b6088a911203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_MODE_ENUM = postgresql.ENUM(
    "single",
    "multi",
    name="external_channel_app_mode",
    create_type=False,
)
_ROUTE_CATALOG_STATUS_ENUM = postgresql.ENUM(
    "available",
    "removed",
    name="external_channel_route_catalog_status",
    create_type=False,
)
_INTERACTION_TYPE_ENUM = postgresql.ENUM(
    "shortcut",
    "block_action",
    "options",
    "view_submission",
    "management_action",
    name="external_channel_interaction_type",
    create_type=False,
)
_INTERACTION_STATUS_ENUM = postgresql.ENUM(
    "accepted",
    "processing",
    "completed",
    "expired",
    "rejected",
    "failed",
    name="external_channel_interaction_status",
    create_type=False,
)
_CONVERSATION_ADMISSION_ORIGIN_ENUM = postgresql.ENUM(
    "single_route",
    "channel_default",
    "shortcut",
    "mention_selector",
    name="external_channel_conversation_admission_origin",
    create_type=False,
)
_CONVERSATION_ADMISSION_STATUS_ENUM = postgresql.ENUM(
    "pending_selection",
    "selected",
    "awaiting_access",
    "bound",
    "expired",
    "rejected",
    name="external_channel_conversation_admission_status",
    create_type=False,
)
_CHANNEL_DEFAULT_STATUS_ENUM = postgresql.ENUM(
    "active",
    "invalidated",
    name="external_channel_channel_default_status",
    create_type=False,
)


def _abort_on_legacy_ambiguity() -> None:
    """Reject legacy data that cannot become an unambiguous Single App."""
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text("""
        SELECT connection_id, agent_id FROM external_channel_agent_routes
        GROUP BY connection_id, agent_id HAVING count(*) > 1
        ORDER BY connection_id, agent_id LIMIT 1
    """)
    ).one_or_none()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot add External Channel App mode: duplicate connection-Agent route: "
            f"{duplicate.connection_id}/{duplicate.agent_id}."
        )
    resource_id = bind.execute(
        sa.text("""
        SELECT resource_id FROM external_channel_bindings WHERE status = 'active'
        GROUP BY resource_id HAVING count(*) > 1 ORDER BY resource_id LIMIT 1
    """)
    ).scalar_one_or_none()
    if resource_id is not None:
        raise RuntimeError(
            "Cannot add External Channel App mode: resource has multiple active "
            f"{resource_id}."
        )
    route_id = bind.execute(
        sa.text("""
        SELECT route.id FROM external_channel_agent_routes AS route
        JOIN external_channel_connections AS connection
          ON connection.id = route.connection_id
        JOIN agents AS agent ON agent.id = route.agent_id
        WHERE connection.workspace_id <> agent.workspace_id ORDER BY route.id LIMIT 1
    """)
    ).scalar_one_or_none()
    if route_id is not None:
        raise RuntimeError(
            "Cannot add External Channel App mode: route crosses Workspace boundary: "
            f"{route_id}."
        )
    connection_id = bind.execute(
        sa.text("""
        SELECT connection.id FROM external_channel_connections AS connection
        LEFT JOIN external_channel_agent_routes AS route
          ON route.connection_id = connection.id
        GROUP BY connection.id
        HAVING count(route.id) <> 1
           OR count(route.id) FILTER (WHERE route.route_mode = 'dedicated') <> 1
        ORDER BY connection.id LIMIT 1
    """)
    ).scalar_one_or_none()
    if connection_id is not None:
        raise RuntimeError(
            "Cannot add External Channel App mode: connection does not have exactly "
            f"one dedicated route: {connection_id}."
        )


def _create_enum_types() -> None:
    """Create PostgreSQL enum types owned by this migration."""
    bind = op.get_bind()
    for enum_type in (
        _APP_MODE_ENUM,
        _ROUTE_CATALOG_STATUS_ENUM,
        _INTERACTION_TYPE_ENUM,
        _INTERACTION_STATUS_ENUM,
        _CONVERSATION_ADMISSION_ORIGIN_ENUM,
        _CONVERSATION_ADMISSION_STATUS_ENUM,
        _CHANNEL_DEFAULT_STATUS_ENUM,
    ):
        enum_type.create(bind)


def _drop_enum_types() -> None:
    """Drop PostgreSQL enum types owned by this migration."""
    bind = op.get_bind()
    for enum_type in (
        _CHANNEL_DEFAULT_STATUS_ENUM,
        _CONVERSATION_ADMISSION_STATUS_ENUM,
        _CONVERSATION_ADMISSION_ORIGIN_ENUM,
        _INTERACTION_STATUS_ENUM,
        _INTERACTION_TYPE_ENUM,
        _ROUTE_CATALOG_STATUS_ENUM,
        _APP_MODE_ENUM,
    ):
        enum_type.drop(bind)


def upgrade() -> None:
    """Upgrade schema with additive Single App-compatible records and constraints."""
    _abort_on_legacy_ambiguity()
    _create_enum_types()

    op.add_column(
        "external_channel_connections",
        sa.Column(
            "app_mode",
            _APP_MODE_ENUM,
            nullable=False,
            server_default="single",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE external_channel_connections SET app_mode = 'single' "
            "WHERE app_mode IS NULL"
        )
    )
    op.create_unique_constraint(
        "uq_external_channel_connections_id_app_mode",
        "external_channel_connections",
        ["id", "app_mode"],
    )
    op.create_unique_constraint(
        "uq_external_channel_resources_connection_id_id",
        "external_channel_resources",
        ["connection_id", "id"],
    )
    op.create_unique_constraint(
        "uq_external_channel_messages_resource_id_id",
        "external_channel_messages",
        ["resource_id", "id"],
    )

    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "connection_app_mode",
            _APP_MODE_ENUM,
            nullable=False,
            server_default="single",
        ),
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column(
            "catalog_status",
            _ROUTE_CATALOG_STATUS_ENUM,
            nullable=False,
            server_default="available",
        ),
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column("catalog_removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "external_channel_agent_routes",
        sa.Column("catalog_removed_by_user_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE external_channel_agent_routes "
            "SET connection_app_mode = 'single', catalog_status = 'available' "
            "WHERE connection_app_mode IS NULL OR catalog_status IS NULL"
        )
    )
    op.drop_index(
        "uq_external_channel_agent_routes_dedicated_connection",
        table_name="external_channel_agent_routes",
    )
    op.drop_constraint(
        "external_channel_agent_routes_connection_id_fkey",
        "external_channel_agent_routes",
        type_="foreignkey",
    )
    op.create_unique_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        ["connection_id", "agent_id"],
    )
    op.create_unique_constraint(
        "uq_external_channel_agent_routes_connection_id_id",
        "external_channel_agent_routes",
        ["connection_id", "id"],
    )
    op.create_index(
        "uq_external_channel_agent_routes_single_connection",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("connection_app_mode = 'single'"),
    )
    op.create_foreign_key(
        "fk_external_channel_agent_routes_connection_app_mode",
        "external_channel_agent_routes",
        "external_channel_connections",
        ["connection_id", "connection_app_mode"],
        ["id", "app_mode"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "external_channel_agent_routes_catalog_removed_by_user_id_fkey",
        "external_channel_agent_routes",
        "users",
        ["catalog_removed_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "external_channel_interactions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column(
            "transport",
            postgresql.ENUM(
                name="external_channel_transport",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_interaction_key", sa.String(length=128), nullable=False),
        sa.Column("interaction_type", _INTERACTION_TYPE_ENUM, nullable=False),
        sa.Column("callback_id", sa.String(length=255), nullable=True),
        sa.Column("action_id", sa.String(length=255), nullable=True),
        sa.Column("principal_id", sa.String(length=32), nullable=True),
        sa.Column("resource_correlation_key", sa.String(length=512), nullable=True),
        sa.Column("projection", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            _INTERACTION_STATUS_ENUM,
            nullable=False,
            server_default="accepted",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["external_channel_principals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_interaction_key",
            name="uq_external_channel_interactions_connection_provider_key",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "id",
            name="uq_external_channel_interactions_connection_id_id",
        ),
    )
    op.create_index(
        "ix_external_channel_interactions_expires_at",
        "external_channel_interactions",
        ["expires_at"],
    )

    op.create_table(
        "external_channel_conversation_admissions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.String(length=32), nullable=False),
        sa.Column("initiating_principal_id", sa.String(length=32), nullable=True),
        sa.Column("origin", _CONVERSATION_ADMISSION_ORIGIN_ENUM, nullable=False),
        sa.Column("status", _CONVERSATION_ADMISSION_STATUS_ENUM, nullable=False),
        sa.Column("selected_route_id", sa.String(length=32), nullable=True),
        sa.Column("interaction_id", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "resource_id"],
            [
                "external_channel_resources.connection_id",
                "external_channel_resources.id",
            ],
            name="fk_external_channel_conv_admissions_connection_resource",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "source_message_id"],
            [
                "external_channel_messages.resource_id",
                "external_channel_messages.id",
            ],
            name="fk_external_channel_conv_admissions_resource_source_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["initiating_principal_id"],
            ["external_channel_principals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "selected_route_id"],
            [
                "external_channel_agent_routes.connection_id",
                "external_channel_agent_routes.id",
            ],
            name="fk_external_channel_conv_admissions_connection_selected_route",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "interaction_id"],
            [
                "external_channel_interactions.connection_id",
                "external_channel_interactions.id",
            ],
            name="fk_external_channel_conv_admissions_connection_interaction",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_conversation_admissions_connection_status",
        "external_channel_conversation_admissions",
        ["connection_id", "status"],
    )
    op.create_index(
        "ix_external_channel_conversation_admissions_expires_at",
        "external_channel_conversation_admissions",
        ["expires_at"],
    )
    op.create_index(
        "uq_external_channel_conversation_admissions_open_resource",
        "external_channel_conversation_admissions",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_selection', 'selected', 'awaiting_access')"
        ),
    )

    op.create_table(
        "external_channel_channel_defaults",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("provider_channel_id", sa.String(length=255), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            _CHANNEL_DEFAULT_STATUS_ENUM,
            nullable=False,
            server_default="active",
        ),
        sa.Column("configured_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["configured_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "route_id"],
            [
                "external_channel_agent_routes.connection_id",
                "external_channel_agent_routes.id",
            ],
            name="fk_external_channel_channel_defaults_connection_route",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_channel_defaults_route_id_status",
        "external_channel_channel_defaults",
        ["route_id", "status"],
    )
    op.create_index(
        "uq_external_channel_channel_defaults_active_connection_channel",
        "external_channel_channel_defaults",
        ["connection_id", "provider_channel_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.drop_index(
        "uq_external_channel_bindings_active_resource_route",
        table_name="external_channel_bindings",
    )
    op.create_index(
        "uq_external_channel_bindings_active_resource",
        "external_channel_bindings",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION prevent_external_channel_connection_app_mode_update()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.app_mode IS DISTINCT FROM OLD.app_mode THEN
                    RAISE EXCEPTION 'External Channel App mode is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER external_channel_connections_app_mode_immutable
            BEFORE UPDATE OF app_mode ON external_channel_connections
            FOR EACH ROW
            EXECUTE FUNCTION prevent_external_channel_connection_app_mode_update()
            """
        )
    )


def downgrade() -> None:
    """Downgrade only when no Phase 1-only durable data would be discarded."""
    bind = op.get_bind()
    unsafe = bind.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM external_channel_connections WHERE app_mode <> 'single'
            ) OR EXISTS (
                SELECT 1
                FROM external_channel_agent_routes
                WHERE connection_app_mode <> 'single'
                   OR catalog_status <> 'available'
                   OR catalog_removed_at IS NOT NULL
                   OR catalog_removed_by_user_id IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM external_channel_interactions
            ) OR EXISTS (
                SELECT 1 FROM external_channel_conversation_admissions
            ) OR EXISTS (
                SELECT 1 FROM external_channel_channel_defaults
            ) OR EXISTS (
                SELECT 1
                FROM external_channel_connections AS connection
                LEFT JOIN external_channel_agent_routes AS route
                  ON route.connection_id = connection.id
                GROUP BY connection.id
                HAVING count(route.id) <> 1
                   OR count(route.id) FILTER (
                       WHERE route.route_mode = 'dedicated'
                   ) <> 1
            )
            """
        )
    ).scalar_one()
    if unsafe:
        raise RuntimeError(
            "Cannot downgrade while External Channel App mode data exists."
        )
    op.execute(
        sa.text(
            "DROP TRIGGER external_channel_connections_app_mode_immutable "
            "ON external_channel_connections"
        )
    )
    op.execute(
        sa.text("DROP FUNCTION prevent_external_channel_connection_app_mode_update()")
    )
    op.drop_index(
        "uq_external_channel_bindings_active_resource",
        table_name="external_channel_bindings",
    )
    op.create_index(
        "uq_external_channel_bindings_active_resource_route",
        "external_channel_bindings",
        ["resource_id", "route_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(
        "uq_external_channel_channel_defaults_active_connection_channel",
        table_name="external_channel_channel_defaults",
    )
    op.drop_index(
        "ix_external_channel_channel_defaults_route_id_status",
        table_name="external_channel_channel_defaults",
    )
    op.drop_table("external_channel_channel_defaults")
    op.drop_index(
        "uq_external_channel_conversation_admissions_open_resource",
        table_name="external_channel_conversation_admissions",
    )
    op.drop_index(
        "ix_external_channel_conversation_admissions_expires_at",
        table_name="external_channel_conversation_admissions",
    )
    op.drop_index(
        "ix_external_channel_conversation_admissions_connection_status",
        table_name="external_channel_conversation_admissions",
    )
    op.drop_table("external_channel_conversation_admissions")
    op.drop_index(
        "ix_external_channel_interactions_expires_at",
        table_name="external_channel_interactions",
    )
    op.drop_table("external_channel_interactions")
    op.drop_constraint(
        "uq_external_channel_messages_resource_id_id",
        "external_channel_messages",
        type_="unique",
    )
    op.drop_constraint(
        "uq_external_channel_resources_connection_id_id",
        "external_channel_resources",
        type_="unique",
    )
    op.drop_constraint(
        "external_channel_agent_routes_catalog_removed_by_user_id_fkey",
        "external_channel_agent_routes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_channel_agent_routes_connection_app_mode",
        "external_channel_agent_routes",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_external_channel_agent_routes_single_connection",
        table_name="external_channel_agent_routes",
    )
    op.drop_constraint(
        "uq_external_channel_agent_routes_connection_id_id",
        "external_channel_agent_routes",
        type_="unique",
    )
    op.drop_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        type_="unique",
    )
    op.create_foreign_key(
        "external_channel_agent_routes_connection_id_fkey",
        "external_channel_agent_routes",
        "external_channel_connections",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_external_channel_agent_routes_dedicated_connection",
        "external_channel_agent_routes",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("route_mode = 'dedicated'"),
    )
    op.drop_column("external_channel_agent_routes", "catalog_removed_by_user_id")
    op.drop_column("external_channel_agent_routes", "catalog_removed_at")
    op.drop_column("external_channel_agent_routes", "catalog_status")
    op.drop_column("external_channel_agent_routes", "connection_app_mode")
    op.drop_constraint(
        "uq_external_channel_connections_id_app_mode",
        "external_channel_connections",
        type_="unique",
    )
    op.drop_column("external_channel_connections", "app_mode")
    _drop_enum_types()
