"""Durable Runtime Web endpoint, approval, and authentication models."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


class RuntimeWebRequestState(enum.StrEnum):
    """Durable Runtime Web request outcome."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RuntimeWebRequesterKind(enum.StrEnum):
    """Principal kind that created a Runtime Web request."""

    USER = "user"
    AGENT = "agent"


class RuntimeWebCycleEndReason(enum.StrEnum):
    """Reason an approved exposure cycle stopped being current."""

    CLOSED = "closed"
    EXPIRED = "expired"
    REPLACED = "replaced"
    SESSION_REMOVED = "session_removed"


class RuntimeWebAuthMode(enum.StrEnum):
    """Installation authentication mode for Runtime Web."""

    SHARED_COOKIE = "shared_cookie"
    SEPARATE_DOMAIN = "separate_domain"


class RuntimeWebOperationKind(enum.StrEnum):
    """Idempotent Runtime Web mutation kind."""

    PREPARE = "prepare"
    REQUEST = "request"
    DIRECT_CREATE = "direct_create"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    CLOSE = "close"


class RuntimeWebQuotaScopeKind(enum.StrEnum):
    """Logical quota serialization scope."""

    AGENT = "agent"
    SESSION = "session"


runtime_web_request_state_enum = ENUM(
    RuntimeWebRequestState,
    name="runtime_web_request_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_web_requester_kind_enum = ENUM(
    RuntimeWebRequesterKind,
    name="runtime_web_requester_kind",
    create_type=False,
    values_callable=_enum_values,
)
runtime_web_cycle_end_reason_enum = ENUM(
    RuntimeWebCycleEndReason,
    name="runtime_web_cycle_end_reason",
    create_type=False,
    values_callable=_enum_values,
)
runtime_web_auth_mode_enum = ENUM(
    RuntimeWebAuthMode,
    name="runtime_web_auth_mode",
    create_type=False,
    values_callable=_enum_values,
)
runtime_web_operation_kind_enum = ENUM(
    RuntimeWebOperationKind,
    name="runtime_web_operation_kind",
    create_type=False,
    values_callable=_enum_values,
)
runtime_web_quota_scope_kind_enum = ENUM(
    RuntimeWebQuotaScopeKind,
    name="runtime_web_quota_scope_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeWebEndpoint(RDBModel):
    """Stable Runtime Web endpoint identity for one concrete Session and port."""

    __tablename__ = "runtime_web_endpoints"

    CK_PORT = sa.CheckConstraint(
        "port >= 1 AND port <= 65535",
        name="ck_runtime_web_endpoints_port",
    )
    CK_REVISIONS = sa.CheckConstraint(
        "authority_revision >= 0 AND close_barrier >= 0",
        name="ck_runtime_web_endpoints_revisions",
    )
    UQ_SESSION_PORT = sa.UniqueConstraint(
        "agent_session_id",
        "port",
        name="uq_runtime_web_endpoints_session_port",
    )
    UQ_HOSTNAME_KEY = sa.UniqueConstraint(
        "hostname_key",
        name="uq_runtime_web_endpoints_hostname_key",
    )
    FK_CURRENT_PENDING = sa.ForeignKeyConstraint(
        ["current_pending_request_id"],
        ["runtime_web_requests.id"],
        name="fk_runtime_web_endpoints_current_pending",
        use_alter=True,
        ondelete="SET NULL",
    )
    FK_CURRENT_CYCLE = sa.ForeignKeyConstraint(
        ["current_cycle_id"],
        ["runtime_web_cycles.id"],
        name="fk_runtime_web_endpoints_current_cycle",
        use_alter=True,
        ondelete="SET NULL",
    )
    IX_SESSION = sa.Index(
        "ix_runtime_web_endpoints_session",
        "agent_session_id",
        "created_at",
    )
    IX_AGENT = sa.Index(
        "ix_runtime_web_endpoints_agent",
        "agent_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    port: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hostname_key: Mapped[str] = mapped_column(sa.String(52), nullable=False)
    label: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    authority_revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    close_barrier: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    current_pending_request_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    current_cycle_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_PORT,
        CK_REVISIONS,
        UQ_SESSION_PORT,
        UQ_HOSTNAME_KEY,
        FK_CURRENT_PENDING,
        FK_CURRENT_CYCLE,
        IX_SESSION,
        IX_AGENT,
    )


class RDBRuntimeWebRequest(RDBModel):
    """One durable exposure request for a stable endpoint."""

    __tablename__ = "runtime_web_requests"

    CK_REVISION = sa.CheckConstraint(
        "revision >= 1",
        name="ck_runtime_web_requests_revision",
    )
    CK_REQUESTER = sa.CheckConstraint(
        "(requester_kind = 'user' AND requester_user_id IS NOT NULL "
        "AND requester_agent_id IS NULL) OR "
        "(requester_kind = 'agent' AND requester_user_id IS NULL "
        "AND requester_agent_id IS NOT NULL)",
        name="ck_runtime_web_requests_requester",
    )
    CK_DECISION = sa.CheckConstraint(
        "(state = 'pending' AND decided_at IS NULL "
        "AND decided_by_user_id IS NULL) OR "
        "(state <> 'pending' AND decided_at IS NOT NULL)",
        name="ck_runtime_web_requests_decision",
    )
    UQ_PENDING_ENDPOINT = sa.Index(
        "uq_runtime_web_requests_pending_endpoint",
        "endpoint_id",
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    IX_ENDPOINT_CREATED = sa.Index(
        "ix_runtime_web_requests_endpoint_created",
        "endpoint_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    endpoint_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_kind: Mapped[RuntimeWebRequesterKind] = mapped_column(
        runtime_web_requester_kind_enum,
        nullable=False,
    )
    operation_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    state: Mapped[RuntimeWebRequestState] = mapped_column(
        runtime_web_request_state_enum,
        nullable=False,
        default=RuntimeWebRequestState.PENDING,
    )
    revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    requester_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    requester_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    requester_execution_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    requester_call_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    label_snapshot: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    decided_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_REVISION,
        CK_REQUESTER,
        CK_DECISION,
        UQ_PENDING_ENDPOINT,
        IX_ENDPOINT_CREATED,
    )


class RDBRuntimeWebCycle(RDBModel):
    """One finite approved exposure cycle."""

    __tablename__ = "runtime_web_cycles"

    CK_DURATION = sa.CheckConstraint(
        "duration_seconds >= 300 AND duration_seconds <= 28800",
        name="ck_runtime_web_cycles_duration",
    )
    CK_CONFIG_REVISION = sa.CheckConstraint(
        "duration_configuration_revision >= 1",
        name="ck_runtime_web_cycles_duration_configuration_revision",
    )
    CK_DEADLINE = sa.CheckConstraint(
        "expires_at > approved_at",
        name="ck_runtime_web_cycles_deadline",
    )
    CK_END = sa.CheckConstraint(
        "(ended_at IS NULL AND end_reason IS NULL) OR "
        "(ended_at IS NOT NULL AND end_reason IS NOT NULL)",
        name="ck_runtime_web_cycles_end",
    )
    CK_CLOSE_BARRIER = sa.CheckConstraint(
        "close_barrier >= 0",
        name="ck_runtime_web_cycles_close_barrier",
    )
    UQ_CURRENT_ENDPOINT = sa.Index(
        "uq_runtime_web_cycles_current_endpoint",
        "endpoint_id",
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    IX_ENDPOINT_APPROVED = sa.Index(
        "ix_runtime_web_cycles_endpoint_approved",
        "endpoint_id",
        "approved_at",
    )
    IX_EXPIRES = sa.Index(
        "ix_runtime_web_cycles_expires",
        "expires_at",
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    endpoint_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approver_user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    duration_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    duration_configuration_revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    approved_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    close_barrier: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    ended_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    end_reason: Mapped[RuntimeWebCycleEndReason | None] = mapped_column(
        runtime_web_cycle_end_reason_enum,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        CK_DURATION,
        CK_CONFIG_REVISION,
        CK_DEADLINE,
        CK_END,
        CK_CLOSE_BARRIER,
        UQ_CURRENT_ENDPOINT,
        IX_ENDPOINT_APPROVED,
        IX_EXPIRES,
    )


class RDBRuntimeWebOperationReceipt(RDBModel):
    """Idempotent Runtime Web operation outcome."""

    __tablename__ = "runtime_web_operation_receipts"

    UQ_OPERATION = sa.UniqueConstraint(
        "actor_kind",
        "actor_id",
        "execution_id",
        "operation_key",
        "operation_kind",
        name="uq_runtime_web_operation_receipts_operation",
    )
    IX_ENDPOINT = sa.Index(
        "ix_runtime_web_operation_receipts_endpoint",
        "endpoint_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    actor_kind: Mapped[RuntimeWebRequesterKind] = mapped_column(
        runtime_web_requester_kind_enum,
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    operation_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    operation_kind: Mapped[RuntimeWebOperationKind] = mapped_column(
        runtime_web_operation_kind_enum,
        nullable=False,
    )
    result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    endpoint_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    request_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_requests.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    cycle_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_cycles.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (UQ_OPERATION, IX_ENDPOINT)


class RDBRuntimeWebQuotaScope(RDBModel):
    """Durable aggregate-quota serialization row."""

    __tablename__ = "runtime_web_quota_scopes"

    scope_kind: Mapped[RuntimeWebQuotaScopeKind] = mapped_column(
        runtime_web_quota_scope_kind_enum,
        primary_key=True,
    )
    subject_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )


class RDBRuntimeWebAuthConfiguration(RDBModel):
    """Monotonic Runtime Web authentication and duration configuration."""

    __tablename__ = "runtime_web_auth_configuration"

    CK_SINGLETON = sa.CheckConstraint(
        "id = 1",
        name="ck_runtime_web_auth_configuration_singleton",
    )
    CK_VERSION = sa.CheckConstraint(
        "configuration_version >= 1 AND active_epoch >= 1 "
        "AND duration_configuration_revision >= 1",
        name="ck_runtime_web_auth_configuration_versions",
    )
    CK_DURATION = sa.CheckConstraint(
        "active_duration_seconds >= 300 AND active_duration_seconds <= 28800",
        name="ck_runtime_web_auth_configuration_duration",
    )

    id: Mapped[int] = mapped_column(
        sa.SmallInteger,
        primary_key=True,
        init=False,
        default=1,
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    mode: Mapped[RuntimeWebAuthMode] = mapped_column(
        runtime_web_auth_mode_enum,
        nullable=False,
    )
    configuration_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    active_epoch: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    duration_configuration_revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    active_duration_seconds: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (CK_SINGLETON, CK_VERSION, CK_DURATION)


class RDBRuntimeWebGatewayIdentity(RDBModel):
    """Server-side authority for one opaque Gateway identity cookie."""

    __tablename__ = "runtime_web_gateway_identities"

    CK_DEADLINE = sa.CheckConstraint(
        "expires_at > issued_at",
        name="ck_runtime_web_gateway_identities_deadline",
    )
    UQ_SECRET_HASH = sa.UniqueConstraint(
        "secret_hash",
        name="uq_runtime_web_gateway_identities_secret_hash",
    )
    IX_AUTH_SESSION = sa.Index(
        "ix_runtime_web_gateway_identities_auth_session",
        "auth_session_id",
        "expires_at",
    )
    IX_EXPIRY = sa.Index(
        "ix_runtime_web_gateway_identities_expiry",
        "expires_at",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    secret_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auth_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[RuntimeWebAuthMode] = mapped_column(
        runtime_web_auth_mode_enum,
        nullable=False,
    )
    epoch: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    browser_profile: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        CK_DEADLINE,
        UQ_SECRET_HASH,
        IX_AUTH_SESSION,
        IX_EXPIRY,
    )


class RDBRuntimeWebAuthBinding(RDBModel):
    """Short-lived browser binding for separate-domain authentication."""

    __tablename__ = "runtime_web_auth_bindings"

    CK_DEADLINE = sa.CheckConstraint(
        "expires_at > created_at",
        name="ck_runtime_web_auth_bindings_deadline",
    )
    UQ_INITIATION = sa.UniqueConstraint(
        "initiation_id",
        name="uq_runtime_web_auth_bindings_initiation",
    )
    UQ_MAIN_HASH = sa.UniqueConstraint(
        "main_binding_hash",
        name="uq_runtime_web_auth_bindings_main_hash",
    )
    UQ_BROKER_HASH = sa.UniqueConstraint(
        "broker_binding_hash",
        name="uq_runtime_web_auth_bindings_broker_hash",
    )
    IX_EXPIRY = sa.Index(
        "ix_runtime_web_auth_bindings_expiry",
        "expires_at",
        postgresql_where=sa.text("settled_at IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    initiation_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    main_binding_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auth_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    epoch: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    broker_binding_hash: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    broker_bound_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    settled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        CK_DEADLINE,
        UQ_INITIATION,
        UQ_MAIN_HASH,
        UQ_BROKER_HASH,
        IX_EXPIRY,
    )


class RDBRuntimeWebAuthTicket(RDBModel):
    """Single-use authentication ticket for separate-domain exchange."""

    __tablename__ = "runtime_web_auth_tickets"

    CK_DEADLINE = sa.CheckConstraint(
        "expires_at > issued_at",
        name="ck_runtime_web_auth_tickets_deadline",
    )
    UQ_SECRET_HASH = sa.UniqueConstraint(
        "secret_hash",
        name="uq_runtime_web_auth_tickets_secret_hash",
    )
    IX_EXPIRY = sa.Index(
        "ix_runtime_web_auth_tickets_expiry",
        "expires_at",
        postgresql_where=sa.text("consumed_at IS NULL"),
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_auth_bindings.id", ondelete="CASCADE"),
        nullable=False,
    )
    secret_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auth_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    epoch: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (CK_DEADLINE, UQ_SECRET_HASH, IX_EXPIRY)


class RDBRuntimeWebTunnelRoute(RDBModel):
    """Short-lived owner route for one exact Runtime Web tunnel."""

    __tablename__ = "runtime_web_tunnel_routes"

    CK_REVISIONS = sa.CheckConstraint(
        "endpoint_authority_revision >= 0 AND close_barrier >= 0 "
        "AND lease_generation >= 1",
        name="ck_runtime_web_tunnel_routes_revisions",
    )
    CK_GENERATIONS = sa.CheckConstraint(
        "desired_generation >= 1 AND runner_generation >= 1",
        name="ck_runtime_web_tunnel_routes_generations",
    )
    CK_PORT = sa.CheckConstraint(
        "port >= 1 AND port <= 65535",
        name="ck_runtime_web_tunnel_routes_port",
    )
    CK_DEADLINES = sa.CheckConstraint(
        "registration_deadline_at <= transport_deadline_at "
        "AND approval_deadline_at <= transport_deadline_at "
        "AND lease_expires_at <= transport_deadline_at",
        name="ck_runtime_web_tunnel_routes_deadlines",
    )
    UQ_JOIN_NONCE = sa.UniqueConstraint(
        "join_nonce",
        name="uq_runtime_web_tunnel_routes_join_nonce",
    )
    UQ_ROUTE_LEASE = sa.UniqueConstraint(
        "route_lease_id",
        name="uq_runtime_web_tunnel_routes_route_lease",
    )
    IX_OWNER_LEASE = sa.Index(
        "ix_runtime_web_tunnel_routes_owner_lease",
        "owner_boot_id",
        "lease_expires_at",
    )
    IX_RUNTIME_GENERATION = sa.Index(
        "ix_runtime_web_tunnel_routes_runtime_generation",
        "runtime_id",
        "runner_generation",
        "lease_expires_at",
    )

    tunnel_id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_authority_revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    close_barrier: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    desired_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    runner_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    port: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    join_nonce: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner_replica_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    owner_boot_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner_address: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    route_lease_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    lease_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    registration_deadline_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    approval_deadline_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    transport_deadline_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    lease_expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        CK_REVISIONS,
        CK_GENERATIONS,
        CK_PORT,
        CK_DEADLINES,
        UQ_JOIN_NONCE,
        UQ_ROUTE_LEASE,
        IX_OWNER_LEASE,
        IX_RUNTIME_GENERATION,
    )


class RDBRuntimeWebAdmissionLease(RDBModel):
    """Shared connection admission lease for one Runtime Web tunnel."""

    __tablename__ = "runtime_web_admission_leases"

    CK_LEASE = sa.CheckConstraint(
        "lease_generation >= 1 AND reserved_bytes >= 0 "
        "AND lease_expires_at > created_at",
        name="ck_runtime_web_admission_leases_lease",
    )
    UQ_TUNNEL = sa.UniqueConstraint(
        "tunnel_id",
        name="uq_runtime_web_admission_leases_tunnel",
    )
    IX_EXPIRY = sa.Index(
        "ix_runtime_web_admission_leases_expiry",
        "lease_expires_at",
    )
    IX_OWNER = sa.Index(
        "ix_runtime_web_admission_leases_owner",
        "owner_boot_id",
        "lease_expires_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    tunnel_id: Mapped[str] = mapped_column(
        sa.String(128),
        sa.ForeignKey("runtime_web_tunnel_routes.tunnel_id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_boot_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    lease_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    lease_expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    reserved_bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (CK_LEASE, UQ_TUNNEL, IX_EXPIRY, IX_OWNER)
