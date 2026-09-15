"""Replace Runtime Web service authority."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "a32efa82fd63"
down_revision: str | Sequence[str] | None = "097a97177350"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete legacy Session services and install Agent-port authority."""
    op.execute(
        sa.text(
            """
            LOCK TABLE
                runtime_web_session_routes,
                runtime_web_auth_bindings,
                runtime_web_auth_tickets,
                runtime_web_operation_receipts,
                runtime_web_cycles,
                runtime_web_requests,
                runtime_web_endpoints,
                runtime_web_quota_scopes
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM runtime_web_session_routes
                    WHERE lease_expires_at > now()
                ) THEN
                    RAISE EXCEPTION
                        'Runtime Web maintenance preflight found active legacy sessions'
                        USING ERRCODE = '55006';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(sa.text("DELETE FROM runtime_web_session_routes"))

    op.drop_table("runtime_web_auth_tickets")
    op.drop_table("runtime_web_auth_bindings")
    op.drop_table("runtime_web_operation_receipts")
    op.drop_constraint(
        "fk_runtime_web_endpoints_current_cycle",
        "runtime_web_endpoints",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_runtime_web_endpoints_current_pending",
        "runtime_web_endpoints",
        type_="foreignkey",
    )
    op.drop_table("runtime_web_cycles")
    op.drop_table("runtime_web_requests")
    op.drop_table("runtime_web_endpoints")
    op.drop_table("runtime_web_quota_scopes")

    op.execute("DROP TYPE runtime_web_cycle_end_reason")
    op.execute("DROP TYPE runtime_web_request_state")
    op.execute("DROP TYPE runtime_web_requester_kind")
    op.execute("DROP TYPE runtime_web_operation_kind")
    op.execute("DROP TYPE runtime_web_quota_scope_kind")

    op.drop_constraint(
        "ck_runtime_web_auth_configuration_duration",
        "runtime_web_auth_configuration",
        type_="check",
    )
    op.drop_column("runtime_web_auth_configuration", "active_duration_seconds")

    sa.Enum("user", "agent", name="runtime_web_actor_kind").create(op.get_bind())
    sa.Enum(
        "create",
        "request",
        "update",
        "turn_on",
        "turn_off",
        "reset",
        "delete",
        "close",
        name="runtime_web_operation_kind",
    ).create(op.get_bind())

    op.create_table(
        "runtime_web_services",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("hostname_key", sa.String(length=12), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column(
            "selected_duration_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
        sa.Column(
            "exposure_deadline_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "selected_duration_seconds IN (3600, 21600, 86400)",
            name="ck_runtime_web_services_duration",
        ),
        sa.CheckConstraint(
            "port >= 1 AND port <= 65535",
            name="ck_runtime_web_services_port",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_runtime_web_services_revision",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "port",
            name="uq_runtime_web_services_agent_port",
        ),
        sa.UniqueConstraint(
            "hostname_key",
            name="uq_runtime_web_services_hostname_key",
        ),
    )
    op.create_index(
        "ix_runtime_web_services_agent",
        "runtime_web_services",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_services_deadline",
        "runtime_web_services",
        ["exposure_deadline_at"],
        unique=False,
        postgresql_where=sa.text("exposure_deadline_at IS NOT NULL"),
    )

    op.create_table(
        "runtime_web_quota_scopes",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id"),
    )

    op.create_table(
        "runtime_web_operation_receipts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "actor_kind",
            postgresql.ENUM(
                "user",
                "agent",
                name="runtime_web_actor_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column(
            "operation_kind",
            postgresql.ENUM(
                "create",
                "request",
                "update",
                "turn_on",
                "turn_off",
                "reset",
                "delete",
                "close",
                name="runtime_web_operation_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("service_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["runtime_web_services.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_kind",
            "actor_id",
            "execution_id",
            "operation_key",
            "operation_kind",
            name="uq_runtime_web_operation_receipts_operation",
        ),
    )
    op.create_index(
        "ix_runtime_web_operation_receipts_service",
        "runtime_web_operation_receipts",
        ["service_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "runtime_web_auth_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("initiation_id", sa.String(length=32), nullable=False),
        sa.Column("main_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column("service_id", sa.String(length=32), nullable=False),
        sa.Column("expires_at", TimeZoneDateTime(timezone=True), nullable=False),
        sa.Column("broker_binding_hash", sa.String(length=64), nullable=True),
        sa.Column("broker_bound_at", TimeZoneDateTime(timezone=True), nullable=True),
        sa.Column("settled_at", TimeZoneDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_runtime_web_auth_bindings_deadline",
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["runtime_web_services.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "broker_binding_hash", name="uq_runtime_web_auth_bindings_broker_hash"
        ),
        sa.UniqueConstraint(
            "initiation_id", name="uq_runtime_web_auth_bindings_initiation"
        ),
        sa.UniqueConstraint(
            "main_binding_hash", name="uq_runtime_web_auth_bindings_main_hash"
        ),
    )
    op.create_index(
        "ix_runtime_web_auth_bindings_expiry",
        "runtime_web_auth_bindings",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("settled_at IS NULL"),
    )

    op.create_table(
        "runtime_web_auth_tickets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column("service_id", sa.String(length=32), nullable=False),
        sa.Column("issued_at", TimeZoneDateTime(timezone=True), nullable=False),
        sa.Column("expires_at", TimeZoneDateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", TimeZoneDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name="ck_runtime_web_auth_tickets_deadline",
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["runtime_web_auth_bindings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["runtime_web_services.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "secret_hash", name="uq_runtime_web_auth_tickets_secret_hash"
        ),
    )
    op.create_index(
        "ix_runtime_web_auth_tickets_expiry",
        "runtime_web_auth_tickets",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    """Reject restoration of deleted Session-scoped Runtime Web state."""
    raise RuntimeError(
        "Runtime Web service-management cutover is irreversible and forward-only"
    )
