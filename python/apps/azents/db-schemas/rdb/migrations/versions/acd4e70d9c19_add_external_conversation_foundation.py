"""Add durable external conversation positions and invocation wake state."""

# ruff: noqa: E501

import hashlib
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "acd4e70d9c19"
down_revision: str | Sequence[str] | None = "4d6ed822762c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_KIND_ENUM = postgresql.ENUM(
    "parent_channel",
    "thread",
    name="external_channel_conversation_scope_kind",
    create_type=False,
)
_WAKE_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "claimed",
    "dispatched",
    name="external_channel_invocation_wake_dispatch_status",
    create_type=False,
)


def _create_enum(name: str, values: tuple[str, ...]) -> None:
    quoted = ", ".join("'%s'" % value for value in values)
    op.execute(
        sa.text(
            f"""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN CREATE TYPE {name} AS ENUM ({quoted}); END IF; END $$;"""
        )
    )


def _backfill_positions(bind: sa.Connection) -> None:
    """Create canonical positions and recover accepted read-through boundaries."""
    duplicate_count = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT connection_id, provider_resource_key
                FROM external_channel_resources
                WHERE provider_resource_key LIKE 'slack:%'
                   OR provider_resource_key LIKE 'discord:%'
                GROUP BY connection_id, provider_resource_key
                HAVING count(*) > 1
            ) AS duplicates
            """
        )
    ).scalar_one()
    if duplicate_count:
        raise RuntimeError(f"duplicate_resource_scope_count={duplicate_count}")

    rows = (
        bind.execute(
            sa.text(
                """
            SELECT binding.id AS binding_id,
                   resource.id AS resource_id,
                   resource.connection_id,
                   resource.provider_resource_key,
                   resource.labels,
                   binding.projected_through_position,
                   (
                       SELECT batch.last_provider_position
                       FROM external_channel_invocation_batches AS batch
                       WHERE batch.binding_id = binding.id
                       ORDER BY batch.created_at DESC, batch.id DESC
                       LIMIT 1
                   ) AS latest_batch_position
            FROM external_channel_bindings AS binding
            JOIN external_channel_resources AS resource
              ON resource.id = binding.resource_id
            WHERE binding.status = 'active'
            ORDER BY binding.id
            """
            )
        )
        .mappings()
        .all()
    )

    unrecoverable = 0
    malformed = 0
    for row in rows:
        key = row["provider_resource_key"]
        labels = row["labels"] if isinstance(row["labels"], dict) else {}
        scope: tuple[str, str] | None = None
        if isinstance(key, str):
            parts = key.split(":")
            if key.startswith("slack:") and len(parts) == 4:
                scope = (parts[2], parts[3])
            elif key.startswith("discord:") and len(parts) == 3:
                target = next(
                    (
                        labels[name]
                        for name in (
                            "delivery_channel_id",
                            "thread_channel_id",
                            "thread_id",
                        )
                        if isinstance(labels.get(name), str) and labels[name]
                    ),
                    None,
                )
                if target is not None:
                    scope = (target, target)
        boundary = row["projected_through_position"] or row["latest_batch_position"]
        if scope is None:
            malformed += 1
        elif not isinstance(boundary, str) or not boundary:
            unrecoverable += 1
        else:
            position_id = hashlib.md5(
                f"{row['resource_id']}_thread".encode()
            ).hexdigest()
            bind.execute(
                sa.text(
                    """
                    INSERT INTO external_channel_conversation_positions
                        (id, connection_id, scope_kind, provider_channel_id,
                         provider_thread_key, read_through_position, created_at, updated_at)
                    VALUES (:id, :connection_id, 'thread', :channel_id,
                            :thread_key, :boundary, now(), now())
                    ON CONFLICT (id) DO UPDATE
                    SET read_through_position = EXCLUDED.read_through_position
                    """
                ),
                {
                    "id": position_id,
                    "connection_id": row["connection_id"],
                    "channel_id": scope[0],
                    "thread_key": scope[1],
                    "boundary": boundary,
                },
            )
    if malformed or unrecoverable:
        raise RuntimeError(
            f"malformed_active_scope_count={malformed}; "
            f"unrecoverable_active_position_count={unrecoverable}"
        )

    for table in (
        "external_channel_conversation_admissions",
        "external_channel_access_requests",
    ):
        bind.execute(
            sa.text(
                f"""
                UPDATE {table} AS row
                SET connection_id = resource.connection_id,
                    conversation_position_id = position.id
                FROM external_channel_resources AS resource
                JOIN external_channel_conversation_positions AS position
                  ON position.connection_id = resource.connection_id
                 AND position.id = md5(resource.id || '_thread')
                WHERE row.resource_id = resource.id
                  AND row.conversation_position_id IS NULL
                """
            )
        )
    bind.execute(
        sa.text(
            """
            UPDATE external_channel_invocation_batches AS batch
            SET connection_id = resource.connection_id,
                conversation_position_id = position.id
            FROM external_channel_bindings AS binding
            JOIN external_channel_resources AS resource
              ON resource.id = binding.resource_id
            JOIN external_channel_conversation_positions AS position
              ON position.connection_id = resource.connection_id
             AND position.id = md5(resource.id || '_thread')
            WHERE batch.binding_id = binding.id
              AND batch.conversation_position_id IS NULL
            """
        )
    )


def upgrade() -> None:
    """Add conversation positions, boundaries, and durable wake state."""
    _create_enum(
        "external_channel_conversation_scope_kind", ("parent_channel", "thread")
    )
    _create_enum(
        "external_channel_invocation_wake_dispatch_status",
        ("pending", "claimed", "dispatched"),
    )
    op.create_table(
        "external_channel_conversation_positions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("scope_kind", _SCOPE_KIND_ENUM, nullable=False),
        sa.Column("provider_channel_id", sa.Text(), nullable=False),
        sa.Column("provider_thread_key", sa.Text(), nullable=True),
        sa.Column("read_through_position", sa.Text(), nullable=True),
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
            "(scope_kind = 'parent_channel' AND provider_thread_key IS NULL) OR (scope_kind = 'thread' AND provider_thread_key IS NOT NULL)",
            name="ck_external_channel_conversation_positions_scope_key",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["external_channel_connections.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "id",
            name="uq_external_channel_conversation_positions_connection_id_id",
        ),
    )
    op.create_index(
        "uq_external_channel_conversation_positions_parent",
        "external_channel_conversation_positions",
        ["connection_id", "provider_channel_id"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'parent_channel'"),
    )
    op.create_index(
        "uq_external_channel_conversation_positions_thread",
        "external_channel_conversation_positions",
        ["connection_id", "provider_channel_id", "provider_thread_key"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'thread'"),
    )
    for table in (
        "external_channel_conversation_admissions",
        "external_channel_access_requests",
    ):
        op.add_column(
            table,
            sa.Column("conversation_position_id", sa.String(length=32), nullable=True),
        )
        op.add_column(
            table, sa.Column("range_start_position", sa.Text(), nullable=True)
        )
        op.add_column(table, sa.Column("trigger_position", sa.Text(), nullable=True))
    op.add_column(
        "external_channel_access_requests",
        sa.Column("connection_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column("conversation_position_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column("connection_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column("range_start_position", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column("trigger_position", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column(
            "context_omitted", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column(
            "wake_dispatch_status",
            _WAKE_STATUS_ENUM,
            server_default="dispatched",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_invocation_batches",
        sa.Column(
            "wake_dispatch_claimed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_external_channel_conv_admissions_connection_position",
        "external_channel_conversation_admissions",
        "external_channel_conversation_positions",
        ["connection_id", "conversation_position_id"],
        ["connection_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_channel_invocation_batches_conversation_position",
        "external_channel_invocation_batches",
        "external_channel_conversation_positions",
        ["connection_id", "conversation_position_id"],
        ["connection_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_channel_access_requests_connection_resource",
        "external_channel_access_requests",
        "external_channel_resources",
        ["connection_id", "resource_id"],
        ["connection_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_channel_access_requests_connection_position",
        "external_channel_access_requests",
        "external_channel_conversation_positions",
        ["connection_id", "conversation_position_id"],
        ["connection_id", "id"],
        ondelete="RESTRICT",
    )
    _backfill_positions(op.get_bind())


def downgrade() -> None:
    """Remove additive conversation-position fields; retain enum types."""
    op.drop_constraint(
        "fk_external_channel_access_requests_connection_position",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_channel_access_requests_connection_resource",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_channel_invocation_batches_conversation_position",
        "external_channel_invocation_batches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_channel_conv_admissions_connection_position",
        "external_channel_conversation_admissions",
        type_="foreignkey",
    )
    for table in (
        "external_channel_access_requests",
        "external_channel_invocation_batches",
        "external_channel_conversation_admissions",
    ):
        op.drop_column(table, "trigger_position")
        op.drop_column(table, "range_start_position")
        op.drop_column(table, "conversation_position_id")
    op.drop_column("external_channel_access_requests", "connection_id")
    op.drop_column("external_channel_invocation_batches", "connection_id")
    op.drop_column("external_channel_invocation_batches", "wake_dispatch_claimed_at")
    op.drop_column("external_channel_invocation_batches", "wake_dispatch_status")
    op.drop_column("external_channel_invocation_batches", "context_omitted")
    op.drop_index(
        "uq_external_channel_conversation_positions_thread",
        table_name="external_channel_conversation_positions",
    )
    op.drop_index(
        "uq_external_channel_conversation_positions_parent",
        table_name="external_channel_conversation_positions",
    )
    op.drop_table("external_channel_conversation_positions")
