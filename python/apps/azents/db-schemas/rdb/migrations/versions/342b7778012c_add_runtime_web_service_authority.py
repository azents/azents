"""Add Runtime Web service authority."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "342b7778012c"
down_revision: str | Sequence[str] | None = "c05bc1b811fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("shared_cookie", "separate_domain", name="runtime_web_auth_mode").create(
        op.get_bind()
    )
    sa.Enum("agent", "session", name="runtime_web_quota_scope_kind").create(
        op.get_bind()
    )
    sa.Enum(
        "prepare",
        "request",
        "direct_create",
        "approve",
        "reject",
        "cancel",
        "close",
        name="runtime_web_operation_kind",
    ).create(op.get_bind())
    sa.Enum(
        "closed",
        "expired",
        "replaced",
        "session_removed",
        name="runtime_web_cycle_end_reason",
    ).create(op.get_bind())
    sa.Enum(
        "pending", "approved", "rejected", "cancelled", name="runtime_web_request_state"
    ).create(op.get_bind())
    sa.Enum("user", "agent", name="runtime_web_requester_kind").create(op.get_bind())
    op.create_table(
        "runtime_web_auth_configuration",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "shared_cookie",
                "separate_domain",
                name="runtime_web_auth_mode",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("configuration_version", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active_epoch", sa.BigInteger(), nullable=False),
        sa.Column("duration_configuration_revision", sa.BigInteger(), nullable=False),
        sa.Column("active_duration_seconds", sa.Integer(), nullable=False),
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
            "active_duration_seconds >= 300 AND active_duration_seconds <= 28800",
            name="ck_runtime_web_auth_configuration_duration",
        ),
        sa.CheckConstraint(
            "configuration_version >= 1 AND active_epoch >= 1 AND "
            "duration_configuration_revision >= 1",
            name="ck_runtime_web_auth_configuration_versions",
        ),
        sa.CheckConstraint(
            "id = 1", name="ck_runtime_web_auth_configuration_singleton"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "runtime_web_auth_configuration",
            sa.column("id", sa.SmallInteger()),
            sa.column("enabled", sa.Boolean()),
            sa.column(
                "mode",
                postgresql.ENUM(
                    "shared_cookie",
                    "separate_domain",
                    name="runtime_web_auth_mode",
                    create_type=False,
                ),
            ),
            sa.column("configuration_version", sa.BigInteger()),
            sa.column("fingerprint", sa.String()),
            sa.column("active_epoch", sa.BigInteger()),
            sa.column("duration_configuration_revision", sa.BigInteger()),
            sa.column("active_duration_seconds", sa.Integer()),
        ),
        [
            {
                "id": 1,
                "enabled": False,
                "mode": "separate_domain",
                "configuration_version": 1,
                "fingerprint": (
                    "9d83c5f39577f63a9e9ce3eeef51751ed5798537fcea984a30dcdb21105d339d"
                ),
                "active_epoch": 1,
                "duration_configuration_revision": 1,
                "active_duration_seconds": 7_200,
            }
        ],
    )
    op.create_table(
        "runtime_web_quota_scopes",
        sa.Column(
            "scope_kind",
            postgresql.ENUM(
                "agent",
                "session",
                name="runtime_web_quota_scope_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scope_kind", "subject_id"),
    )
    op.create_table(
        "runtime_web_endpoints",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("hostname_key", sa.String(length=52), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column(
            "authority_revision", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("close_barrier", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("current_pending_request_id", sa.String(length=32), nullable=True),
        sa.Column("current_cycle_id", sa.String(length=32), nullable=True),
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
            "authority_revision >= 0 AND close_barrier >= 0",
            name="ck_runtime_web_endpoints_revisions",
        ),
        sa.CheckConstraint(
            "port >= 1 AND port <= 65535", name="ck_runtime_web_endpoints_port"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_session_id", "port", name="uq_runtime_web_endpoints_session_port"
        ),
        sa.UniqueConstraint(
            "hostname_key", name="uq_runtime_web_endpoints_hostname_key"
        ),
    )
    op.create_index(
        "ix_runtime_web_endpoints_agent",
        "runtime_web_endpoints",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_endpoints_session",
        "runtime_web_endpoints",
        ["agent_session_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "runtime_web_gateway_identities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(
                "shared_cookie",
                "separate_domain",
                name="runtime_web_auth_mode",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("browser_profile", sa.String(length=120), nullable=False),
        sa.Column(
            "issued_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name="ck_runtime_web_gateway_identities_deadline"
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "secret_hash", name="uq_runtime_web_gateway_identities_secret_hash"
        ),
    )
    op.create_index(
        "ix_runtime_web_gateway_identities_auth_session",
        "runtime_web_gateway_identities",
        ["auth_session_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_gateway_identities_expiry",
        "runtime_web_gateway_identities",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "runtime_web_auth_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("initiation_id", sa.String(length=32), nullable=False),
        sa.Column("main_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("broker_binding_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "broker_bound_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "settled_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_runtime_web_auth_bindings_deadline"
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["runtime_web_endpoints.id"], ondelete="CASCADE"
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
        "runtime_web_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column(
            "requester_kind",
            postgresql.ENUM(
                "user", "agent", name="runtime_web_requester_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(
                "pending",
                "approved",
                "rejected",
                "cancelled",
                name="runtime_web_request_state",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("requester_user_id", sa.String(length=32), nullable=True),
        sa.Column("requester_agent_id", sa.String(length=32), nullable=True),
        sa.Column("requester_execution_id", sa.String(length=32), nullable=True),
        sa.Column("requester_call_id", sa.String(length=255), nullable=True),
        sa.Column("label_snapshot", sa.String(length=120), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "decided_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
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
            "(requester_kind = 'user' AND requester_user_id IS NOT NULL "
            "AND requester_agent_id IS NULL) OR "
            "(requester_kind = 'agent' AND requester_user_id IS NULL "
            "AND requester_agent_id IS NOT NULL)",
            name="ck_runtime_web_requests_requester",
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND decided_at IS NULL "
            "AND decided_by_user_id IS NULL) OR "
            "(state <> 'pending' AND decided_at IS NOT NULL)",
            name="ck_runtime_web_requests_decision",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_runtime_web_requests_revision"),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["runtime_web_endpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requester_agent_id"], ["agents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_web_requests_endpoint_created",
        "runtime_web_requests",
        ["endpoint_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_runtime_web_requests_pending_endpoint",
        "runtime_web_requests",
        ["endpoint_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "runtime_web_auth_tickets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("auth_session_id", sa.String(length=32), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column(
            "issued_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "consumed_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name="ck_runtime_web_auth_tickets_deadline"
        ),
        sa.ForeignKeyConstraint(
            ["auth_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["runtime_web_auth_bindings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["runtime_web_endpoints.id"], ondelete="CASCADE"
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
    op.create_table(
        "runtime_web_cycles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("approver_user_id", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("duration_configuration_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "approved_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            TimeZoneDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("close_barrier", sa.BigInteger(), nullable=False),
        sa.Column(
            "ended_at",
            TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "end_reason",
            postgresql.ENUM(
                "closed",
                "expired",
                "replaced",
                "session_removed",
                name="runtime_web_cycle_end_reason",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL AND end_reason IS NULL) OR "
            "(ended_at IS NOT NULL AND end_reason IS NOT NULL)",
            name="ck_runtime_web_cycles_end",
        ),
        sa.CheckConstraint(
            "close_barrier >= 0", name="ck_runtime_web_cycles_close_barrier"
        ),
        sa.CheckConstraint(
            "duration_configuration_revision >= 1",
            name="ck_runtime_web_cycles_duration_configuration_revision",
        ),
        sa.CheckConstraint(
            "duration_seconds >= 300 AND duration_seconds <= 28800",
            name="ck_runtime_web_cycles_duration",
        ),
        sa.CheckConstraint(
            "expires_at > approved_at", name="ck_runtime_web_cycles_deadline"
        ),
        sa.ForeignKeyConstraint(
            ["approver_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["runtime_web_endpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["runtime_web_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_web_cycles_endpoint_approved",
        "runtime_web_cycles",
        ["endpoint_id", "approved_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_web_cycles_expires",
        "runtime_web_cycles",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "uq_runtime_web_cycles_current_endpoint",
        "runtime_web_cycles",
        ["endpoint_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_foreign_key(
        "fk_runtime_web_endpoints_current_pending",
        "runtime_web_endpoints",
        "runtime_web_requests",
        ["current_pending_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_runtime_web_endpoints_current_cycle",
        "runtime_web_endpoints",
        "runtime_web_cycles",
        ["current_cycle_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "runtime_web_operation_receipts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "actor_kind",
            postgresql.ENUM(
                "user", "agent", name="runtime_web_requester_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column(
            "operation_kind",
            postgresql.ENUM(
                "prepare",
                "request",
                "direct_create",
                "approve",
                "reject",
                "cancel",
                "close",
                name="runtime_web_operation_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("endpoint_id", sa.String(length=32), nullable=True),
        sa.Column("request_id", sa.String(length=32), nullable=True),
        sa.Column("cycle_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["runtime_web_cycles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["runtime_web_endpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["runtime_web_requests.id"], ondelete="CASCADE"
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
        "ix_runtime_web_operation_receipts_endpoint",
        "runtime_web_operation_receipts",
        ["endpoint_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_runtime_web_operation_receipts_endpoint",
        table_name="runtime_web_operation_receipts",
    )
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
    op.drop_index(
        "uq_runtime_web_cycles_current_endpoint",
        table_name="runtime_web_cycles",
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_index(
        "ix_runtime_web_cycles_expires",
        table_name="runtime_web_cycles",
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_index(
        "ix_runtime_web_cycles_endpoint_approved", table_name="runtime_web_cycles"
    )
    op.drop_table("runtime_web_cycles")
    op.drop_index(
        "ix_runtime_web_auth_tickets_expiry",
        table_name="runtime_web_auth_tickets",
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.drop_table("runtime_web_auth_tickets")
    op.drop_index(
        "uq_runtime_web_requests_pending_endpoint",
        table_name="runtime_web_requests",
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.drop_index(
        "ix_runtime_web_requests_endpoint_created", table_name="runtime_web_requests"
    )
    op.drop_table("runtime_web_requests")
    op.drop_index(
        "ix_runtime_web_auth_bindings_expiry",
        table_name="runtime_web_auth_bindings",
        postgresql_where=sa.text("settled_at IS NULL"),
    )
    op.drop_table("runtime_web_auth_bindings")
    op.drop_index(
        "ix_runtime_web_gateway_identities_expiry",
        table_name="runtime_web_gateway_identities",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "ix_runtime_web_gateway_identities_auth_session",
        table_name="runtime_web_gateway_identities",
    )
    op.drop_table("runtime_web_gateway_identities")
    op.drop_index(
        "ix_runtime_web_endpoints_session", table_name="runtime_web_endpoints"
    )
    op.drop_index("ix_runtime_web_endpoints_agent", table_name="runtime_web_endpoints")
    op.drop_table("runtime_web_endpoints")
    op.drop_table("runtime_web_quota_scopes")
    op.drop_table("runtime_web_auth_configuration")
    sa.Enum("user", "agent", name="runtime_web_requester_kind").drop(op.get_bind())
    sa.Enum(
        "pending", "approved", "rejected", "cancelled", name="runtime_web_request_state"
    ).drop(op.get_bind())
    sa.Enum(
        "closed",
        "expired",
        "replaced",
        "session_removed",
        name="runtime_web_cycle_end_reason",
    ).drop(op.get_bind())
    sa.Enum(
        "prepare",
        "request",
        "direct_create",
        "approve",
        "reject",
        "cancel",
        "close",
        name="runtime_web_operation_kind",
    ).drop(op.get_bind())
    sa.Enum("agent", "session", name="runtime_web_quota_scope_kind").drop(op.get_bind())
    sa.Enum("shared_cookie", "separate_domain", name="runtime_web_auth_mode").drop(
        op.get_bind()
    )
