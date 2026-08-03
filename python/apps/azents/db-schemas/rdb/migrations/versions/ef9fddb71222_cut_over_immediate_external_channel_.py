"""Cut over immediate External Channel provider delivery."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ef9fddb71222"
down_revision: str | Sequence[str] | None = "772e7ab22a8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_STATUS_VALUES = (
    "present",
    "failed",
    "unknown",
    "deleted",
)
_LEGACY_PROJECTION_STATUS_VALUES = (
    "pending",
    *_PROJECTION_STATUS_VALUES,
)
_ACTION_MODE_VALUES = ("finish", "continue")
_DELIVERY_ORIGIN_VALUES = (
    "channel_action",
    "access_request",
    "setup_claim",
    "binding_disconnect",
    "connection_disconnect",
    "binding_settings_available",
    "manager_operation",
)
_DELIVERY_OPERATION_VALUES = (
    "reply",
    "progress_create",
    "progress_update",
    "progress_delete",
    "control_message",
)
_DELIVERY_STATUS_VALUES = (
    "pending",
    "attempting",
    "delivered",
    "failed",
    "unknown",
    "not_attempted",
)


def _replace_projection_status(values: Sequence[str]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    temporary_type = "external_channel_work_projection_status_new"
    op.execute(sa.text(f"CREATE TYPE {temporary_type} AS ENUM ({quoted_values})"))
    for table_name, column_name in (
        ("external_channel_work_projection_parts", "status"),
        ("external_channel_access_requests", "control_projection_status"),
    ):
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                f"TYPE {temporary_type} "
                f"USING {column_name}::text::{temporary_type}"
            )
        )
    op.execute(sa.text("DROP TYPE external_channel_work_projection_status"))
    op.execute(
        sa.text(
            f"ALTER TYPE {temporary_type} "
            "RENAME TO external_channel_work_projection_status"
        )
    )


def _drop_projection_delivery_foreign_key() -> None:
    inspector = sa.inspect(op.get_bind())
    foreign_key = next(
        foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "external_channel_work_projection_parts"
        )
        if foreign_key["referred_table"] == "external_channel_delivery_attempts"
    )
    constraint_name = foreign_key["name"]
    if not isinstance(constraint_name, str):
        raise RuntimeError("Projection delivery foreign key has no name.")
    op.drop_constraint(
        constraint_name,
        "external_channel_work_projection_parts",
        type_="foreignkey",
    )


def _create_legacy_enum(name: str, values: Sequence[str]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({quoted_values})"))


def upgrade() -> None:
    """Replace durable provider-operation history with owner-local current state."""
    projection_status_enum = postgresql.ENUM(
        *_LEGACY_PROJECTION_STATUS_VALUES,
        name="external_channel_work_projection_status",
        create_type=False,
    )
    op.add_column(
        "external_channel_access_requests",
        sa.Column("control_provider_message_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "external_channel_access_requests",
        sa.Column("control_projection_status", projection_status_enum, nullable=True),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_work_projection_parts (
                id,
                work_id,
                part_ordinal,
                desired_progress_revision,
                status,
                provider_message_key
            )
            SELECT
                md5('channel-260802:' || work.id),
                work.id,
                0,
                work.desired_progress_revision,
                'present'::external_channel_work_projection_status,
                work.progress_provider_message_key
            FROM external_channel_works AS work
            JOIN external_channel_bindings AS binding
              ON binding.id = work.binding_id
            JOIN external_channel_agent_routes AS route
              ON route.id = binding.route_id
            JOIN external_channel_connections AS connection
              ON connection.id = route.connection_id
            WHERE connection.provider::text = 'slack'
              AND work.progress_provider_message_key IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM external_channel_work_projection_parts AS part
                  WHERE part.work_id = work.id
                    AND part.part_ordinal = 0
              )
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE external_channel_work_projection_parts "
            "SET status = 'unknown' "
            "WHERE status::text = 'pending'"
        )
    )
    op.alter_column(
        "external_channel_work_projection_parts",
        "status",
        server_default=None,
    )
    _replace_projection_status(_PROJECTION_STATUS_VALUES)

    _drop_projection_delivery_foreign_key()
    op.drop_column(
        "external_channel_work_projection_parts",
        "latest_delivery_attempt_id",
    )
    op.drop_column("external_channel_work_projection_parts", "deleted_at")
    op.drop_column("external_channel_works", "progress_provider_message_key")

    op.drop_table("external_channel_delivery_attempts")
    op.drop_table("external_channel_actions")
    for type_name in (
        "external_channel_delivery_status",
        "external_channel_delivery_operation",
        "external_channel_delivery_origin_type",
        "external_channel_action_mode",
    ):
        op.execute(sa.text(f"DROP TYPE {type_name}"))


def downgrade() -> None:
    """Restore the legacy schema without reconstructing discarded history."""
    _create_legacy_enum("external_channel_action_mode", _ACTION_MODE_VALUES)
    _create_legacy_enum(
        "external_channel_delivery_origin_type",
        _DELIVERY_ORIGIN_VALUES,
    )
    _create_legacy_enum(
        "external_channel_delivery_operation",
        _DELIVERY_OPERATION_VALUES,
    )
    _create_legacy_enum(
        "external_channel_delivery_status",
        _DELIVERY_STATUS_VALUES,
    )

    action_mode_enum = postgresql.ENUM(
        *_ACTION_MODE_VALUES,
        name="external_channel_action_mode",
        create_type=False,
    )
    delivery_origin_enum = postgresql.ENUM(
        *_DELIVERY_ORIGIN_VALUES,
        name="external_channel_delivery_origin_type",
        create_type=False,
    )
    delivery_operation_enum = postgresql.ENUM(
        *_DELIVERY_OPERATION_VALUES,
        name="external_channel_delivery_operation",
        create_type=False,
    )
    delivery_status_enum = postgresql.ENUM(
        *_DELIVERY_STATUS_VALUES,
        name="external_channel_delivery_status",
        create_type=False,
    )

    op.create_table(
        "external_channel_actions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("client_tool_call_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("mode", action_mode_enum, nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("work_id", sa.String(length=32), nullable=True),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["external_channel_works.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_session_id",
            "client_tool_call_id",
            name="uq_external_channel_actions_session_client_tool_call",
        ),
    )
    op.create_index(
        "ix_external_channel_actions_binding_id_created_at",
        "external_channel_actions",
        ["binding_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "external_channel_delivery_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("origin_type", delivery_origin_enum, nullable=False),
        sa.Column("origin_id", sa.String(length=32), nullable=False),
        sa.Column("operation", delivery_operation_enum, nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            delivery_status_enum,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("part_ordinal", sa.Integer(), server_default="0", nullable=False),
        sa.Column("channel_action_id", sa.String(length=32), nullable=True),
        sa.Column("binding_id", sa.String(length=32), nullable=True),
        sa.Column("provider_message_key", sa.String(length=255), nullable=True),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["channel_action_id"],
            ["external_channel_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_delivery_attempts_binding_id_status",
        "external_channel_delivery_attempts",
        ["binding_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_external_channel_delivery_attempts_status_created_at",
        "external_channel_delivery_attempts",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "binding_id", "operation", "part_ordinal"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "operation", "part_ordinal"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )

    op.add_column(
        "external_channel_works",
        sa.Column(
            "progress_provider_message_key",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_works AS work
            SET progress_provider_message_key = part.provider_message_key
            FROM external_channel_work_projection_parts AS part,
                 external_channel_bindings AS binding,
                 external_channel_agent_routes AS route,
                 external_channel_connections AS connection
            WHERE part.work_id = work.id
              AND part.part_ordinal = 0
              AND part.provider_message_key IS NOT NULL
              AND binding.id = work.binding_id
              AND route.id = binding.route_id
              AND connection.id = route.connection_id
              AND connection.provider::text = 'slack'
            """
        )
    )

    _replace_projection_status(_LEGACY_PROJECTION_STATUS_VALUES)
    op.alter_column(
        "external_channel_work_projection_parts",
        "status",
        server_default="pending",
    )
    op.add_column(
        "external_channel_work_projection_parts",
        sa.Column("latest_delivery_attempt_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_work_projection_parts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_external_channel_work_parts_latest_delivery",
        "external_channel_work_projection_parts",
        "external_channel_delivery_attempts",
        ["latest_delivery_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_column(
        "external_channel_access_requests",
        "control_projection_status",
    )
    op.drop_column(
        "external_channel_access_requests",
        "control_provider_message_key",
    )
