"""generalize external channel ingress owners

Revision ID: 346454f625fe
Revises: b53dacd10814
Create Date: 2026-08-10 17:39:33.469859

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "346454f625fe"
down_revision: str | Sequence[str] | None = "b53dacd10814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_owner_table() -> None:
    op.create_table(
        "external_channel_ingress_owners",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("target_resource_id", sa.String(length=32), nullable=False),
        sa.Column("route_id", sa.String(length=32), nullable=False),
        sa.Column("participation_setting_id", sa.String(length=32), nullable=True),
        sa.Column("participation_settings_generation", sa.Integer(), nullable=True),
        sa.Column(
            "response_mode",
            postgresql.ENUM(name="external_channel_response_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("binding_id", sa.String(length=32), nullable=True),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column(
            "preparation_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "preparation_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_batch_pending",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("current_batch_id", sa.String(length=32), nullable=True),
        sa.Column(
            "current_batch_started_at", sa.DateTime(timezone=True), nullable=True
        ),
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
            "(current_batch_id IS NULL AND current_batch_started_at IS NULL) OR "
            "(current_batch_id IS NOT NULL AND current_batch_started_at IS NOT NULL "
            "AND lease_owner IS NOT NULL)",
            name="ck_external_channel_ingress_owners_batch",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_external_channel_ingress_owners_lease",
        ),
        sa.CheckConstraint(
            "preparation_attempt_count >= 0 AND preparation_attempt_count <= 5",
            name="ck_external_channel_ingress_owners_preparation_attempt_count",
        ),
        sa.CheckConstraint(
            "(binding_id IS NULL AND session_id IS NULL) OR "
            "(binding_id IS NOT NULL AND session_id IS NOT NULL)",
            name="ck_external_channel_ingress_owners_ready",
        ),
        sa.CheckConstraint(
            "(participation_setting_id IS NULL "
            "AND participation_settings_generation IS NULL) OR "
            "(participation_setting_id IS NOT NULL "
            "AND participation_settings_generation IS NOT NULL)",
            name="ck_external_channel_ingress_owners_setting",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["external_channel_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["participation_setting_id"],
            ["external_channel_participation_settings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["external_channel_agent_routes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_resource_id",
            name="uq_external_channel_ingress_owners_target_resource",
        ),
    )
    op.create_index(
        "ix_external_channel_ingress_owners_recovery",
        "external_channel_ingress_owners",
        ["preparation_next_attempt_at", "lease_expires_at", "updated_at"],
        unique=False,
    )


def upgrade() -> None:
    """Replace Session-keyed owners with effective-conversation owners."""
    connection = op.get_bind()
    op.add_column(
        "external_channel_access_requests",
        sa.Column("source_resource_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_access_requests
            SET source_resource_id = resource_id
            """
        )
    )
    op.alter_column(
        "external_channel_access_requests",
        "source_resource_id",
        nullable=False,
    )
    op.create_foreign_key(
        "external_channel_access_requests_source_resource_id_fkey",
        "external_channel_access_requests",
        "external_channel_resources",
        ["source_resource_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_external_channel_access_requests_connection_source_resource",
        "external_channel_access_requests",
        "external_channel_resources",
        ["connection_id", "source_resource_id"],
        ["connection_id", "id"],
        ondelete="RESTRICT",
    )
    incompatible = connection.execute(
        sa.text(
            """
            SELECT drain.session_id
            FROM external_channel_ingress_sessions AS drain
            LEFT JOIN external_channel_ingress_items AS item
                ON item.session_id = drain.session_id
            LEFT JOIN external_channel_resources AS resource
                ON resource.id = item.resource_id
            LEFT JOIN external_channel_bindings AS binding
                ON binding.id = item.binding_id
            LEFT JOIN external_channel_agent_routes AS route
                ON route.id = binding.route_id
            GROUP BY drain.session_id
            HAVING count(item.id) = 0
                OR count(DISTINCT item.connection_id) <> 1
                OR count(DISTINCT item.resource_id) <> 1
                OR count(DISTINCT item.binding_id) <> 1
                OR bool_or(resource.connection_id <> item.connection_id)
                OR bool_or(binding.resource_id <> item.resource_id)
                OR bool_or(binding.agent_session_id <> drain.session_id)
                OR bool_or(route.connection_id <> item.connection_id)
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if incompatible is not None:
        raise RuntimeError(
            "External Channel ingress migration found an incompatible Session owner."
        )

    _create_owner_table()
    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_ingress_owners (
                id,
                connection_id,
                target_resource_id,
                route_id,
                participation_setting_id,
                participation_settings_generation,
                response_mode,
                binding_id,
                session_id,
                preparation_attempt_count,
                preparation_next_attempt_at,
                lease_owner,
                lease_generation,
                lease_acquired_at,
                lease_expires_at,
                first_batch_pending,
                current_batch_id,
                current_batch_started_at,
                created_at,
                updated_at
            )
            SELECT
                md5('external-channel-ingress-owner:' || drain.session_id),
                item.connection_id,
                item.resource_id,
                binding.route_id,
                NULL,
                NULL,
                binding.response_mode,
                item.binding_id,
                drain.session_id,
                0,
                NULL,
                drain.lease_owner,
                drain.lease_generation,
                drain.lease_acquired_at,
                drain.lease_expires_at,
                drain.first_batch_pending,
                drain.current_batch_id,
                drain.current_batch_started_at,
                drain.created_at,
                drain.updated_at
            FROM external_channel_ingress_sessions AS drain
            JOIN LATERAL (
                SELECT connection_id, resource_id, binding_id
                FROM external_channel_ingress_items
                WHERE session_id = drain.session_id
                ORDER BY queue_key
                LIMIT 1
            ) AS item ON TRUE
            JOIN external_channel_bindings AS binding ON binding.id = item.binding_id
            """
        )
    )

    op.add_column(
        "external_channel_ingress_items",
        sa.Column("owner_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_ingress_items",
        sa.Column("source_resource_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_ingress_items AS item
            SET owner_id = owner.id,
                source_resource_id = item.resource_id
            FROM external_channel_ingress_owners AS owner
            WHERE owner.session_id = item.session_id
            """
        )
    )
    op.alter_column("external_channel_ingress_items", "owner_id", nullable=False)
    op.alter_column(
        "external_channel_ingress_items", "source_resource_id", nullable=False
    )

    op.drop_index(
        "ix_external_channel_ingress_items_session_due_queue",
        table_name="external_channel_ingress_items",
    )
    op.drop_constraint(
        "uq_external_channel_ingress_items_active_identity",
        "external_channel_ingress_items",
        type_="unique",
    )
    op.drop_constraint(
        "external_channel_ingress_items_session_id_fkey",
        "external_channel_ingress_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "external_channel_ingress_items_binding_id_fkey",
        "external_channel_ingress_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "external_channel_ingress_items_resource_id_fkey",
        "external_channel_ingress_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "external_channel_ingress_items_owner_id_fkey",
        "external_channel_ingress_items",
        "external_channel_ingress_owners",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "external_channel_ingress_items_source_resource_id_fkey",
        "external_channel_ingress_items",
        "external_channel_resources",
        ["source_resource_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_external_channel_ingress_items_active_identity",
        "external_channel_ingress_items",
        ["owner_id", "deduplication_key"],
    )
    op.create_index(
        "ix_external_channel_ingress_items_owner_due_queue",
        "external_channel_ingress_items",
        ["owner_id", "state", "next_attempt_at", "queue_key"],
        unique=False,
    )
    op.drop_column("external_channel_ingress_items", "session_id")
    op.drop_column("external_channel_ingress_items", "binding_id")
    op.drop_column("external_channel_ingress_items", "resource_id")

    op.drop_index(
        "ix_external_channel_ingress_sessions_recovery",
        table_name="external_channel_ingress_sessions",
    )
    op.drop_table("external_channel_ingress_sessions")


def downgrade() -> None:
    """Restore the Session-keyed queue when every owner is ready."""
    connection = op.get_bind()
    unresolved = connection.execute(
        sa.text(
            """
            SELECT candidate.id
            FROM (
                SELECT owner.id
                FROM external_channel_ingress_owners AS owner
                LEFT JOIN external_channel_ingress_items AS item
                    ON item.owner_id = owner.id
                WHERE owner.binding_id IS NULL
                   OR owner.session_id IS NULL
                   OR item.source_resource_id <> owner.target_resource_id
                UNION ALL
                SELECT min(owner.id) AS id
                FROM external_channel_ingress_owners AS owner
                WHERE owner.session_id IS NOT NULL
                GROUP BY owner.session_id
                HAVING count(*) > 1
                UNION ALL
                SELECT access.id
                FROM external_channel_access_requests AS access
                WHERE access.source_resource_id <> access.resource_id
            ) AS candidate
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if unresolved is not None:
        raise RuntimeError(
            "Cannot downgrade External Channel ingress with owners that the "
            "Session-keyed lifecycle cannot represent."
        )

    op.create_table(
        "external_channel_ingress_sessions",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_batch_pending",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("current_batch_id", sa.String(length=32), nullable=True),
        sa.Column(
            "current_batch_started_at", sa.DateTime(timezone=True), nullable=True
        ),
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
            "(current_batch_id IS NULL AND current_batch_started_at IS NULL) OR "
            "(current_batch_id IS NOT NULL AND current_batch_started_at IS NOT NULL "
            "AND lease_owner IS NOT NULL)",
            name="ck_external_channel_ingress_sessions_batch",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_external_channel_ingress_sessions_lease",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_external_channel_ingress_sessions_recovery",
        "external_channel_ingress_sessions",
        ["lease_expires_at", "updated_at"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_ingress_sessions (
                session_id, lease_owner, lease_generation, lease_acquired_at,
                lease_expires_at, first_batch_pending, current_batch_id,
                current_batch_started_at, created_at, updated_at
            )
            SELECT session_id, lease_owner, lease_generation, lease_acquired_at,
                   lease_expires_at, first_batch_pending, current_batch_id,
                   current_batch_started_at, created_at, updated_at
            FROM external_channel_ingress_owners
            """
        )
    )

    op.add_column(
        "external_channel_ingress_items",
        sa.Column("resource_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_ingress_items",
        sa.Column("binding_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_ingress_items",
        sa.Column("session_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_ingress_items AS item
            SET resource_id = item.source_resource_id,
                binding_id = owner.binding_id,
                session_id = owner.session_id
            FROM external_channel_ingress_owners AS owner
            WHERE owner.id = item.owner_id
            """
        )
    )
    for column in ("session_id", "resource_id", "binding_id"):
        op.alter_column("external_channel_ingress_items", column, nullable=False)

    op.drop_index(
        "ix_external_channel_ingress_items_owner_due_queue",
        table_name="external_channel_ingress_items",
    )
    op.drop_constraint(
        "uq_external_channel_ingress_items_active_identity",
        "external_channel_ingress_items",
        type_="unique",
    )
    op.drop_constraint(
        "external_channel_ingress_items_owner_id_fkey",
        "external_channel_ingress_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "external_channel_ingress_items_source_resource_id_fkey",
        "external_channel_ingress_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "external_channel_ingress_items_session_id_fkey",
        "external_channel_ingress_items",
        "external_channel_ingress_sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "external_channel_ingress_items_binding_id_fkey",
        "external_channel_ingress_items",
        "external_channel_bindings",
        ["binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "external_channel_ingress_items_resource_id_fkey",
        "external_channel_ingress_items",
        "external_channel_resources",
        ["resource_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_external_channel_ingress_items_active_identity",
        "external_channel_ingress_items",
        ["session_id", "deduplication_key"],
    )
    op.create_index(
        "ix_external_channel_ingress_items_session_due_queue",
        "external_channel_ingress_items",
        ["session_id", "state", "next_attempt_at", "queue_key"],
        unique=False,
    )
    op.drop_column("external_channel_ingress_items", "source_resource_id")
    op.drop_column("external_channel_ingress_items", "owner_id")

    op.drop_index(
        "ix_external_channel_ingress_owners_recovery",
        table_name="external_channel_ingress_owners",
    )
    op.drop_table("external_channel_ingress_owners")
    op.drop_constraint(
        "fk_external_channel_access_requests_connection_source_resource",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "external_channel_access_requests_source_resource_id_fkey",
        "external_channel_access_requests",
        type_="foreignkey",
    )
    op.drop_column("external_channel_access_requests", "source_resource_id")
