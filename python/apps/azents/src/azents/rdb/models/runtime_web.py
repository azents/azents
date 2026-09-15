"""Durable Runtime Web service and authentication models."""

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


class RuntimeWebActorKind(enum.StrEnum):
    """Principal kind that performs an idempotent service operation."""

    USER = "user"
    AGENT = "agent"


class RuntimeWebAuthMode(enum.StrEnum):
    """Installation authentication mode for Runtime Web."""

    SHARED_COOKIE = "shared_cookie"
    SEPARATE_DOMAIN = "separate_domain"


class RuntimeWebOperationKind(enum.StrEnum):
    """Idempotent Runtime Web mutation kind."""

    CREATE = "create"
    REQUEST = "request"
    UPDATE = "update"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    RESET = "reset"
    DELETE = "delete"
    CLOSE = "close"


runtime_web_actor_kind_enum = ENUM(
    RuntimeWebActorKind,
    name="runtime_web_actor_kind",
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


class RDBRuntimeWebService(RDBModel):
    """Stable Runtime Web service identity for one Agent and local port."""

    __tablename__ = "runtime_web_services"

    CK_PORT = sa.CheckConstraint(
        "port >= 1 AND port <= 65535",
        name="ck_runtime_web_services_port",
    )
    CK_DURATION = sa.CheckConstraint(
        "selected_duration_seconds IN (3600, 21600, 86400)",
        name="ck_runtime_web_services_duration",
    )
    CK_REVISION = sa.CheckConstraint(
        "revision >= 0",
        name="ck_runtime_web_services_revision",
    )
    UQ_AGENT_PORT = sa.UniqueConstraint(
        "agent_id",
        "port",
        name="uq_runtime_web_services_agent_port",
    )
    UQ_HOSTNAME_KEY = sa.UniqueConstraint(
        "hostname_key",
        name="uq_runtime_web_services_hostname_key",
    )
    IX_AGENT = sa.Index(
        "ix_runtime_web_services_agent",
        "agent_id",
        "created_at",
    )
    IX_DEADLINE = sa.Index(
        "ix_runtime_web_services_deadline",
        "exposure_deadline_at",
        postgresql_where=sa.text("exposure_deadline_at IS NOT NULL"),
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
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    port: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hostname_key: Mapped[str] = mapped_column(sa.String(12), nullable=False)
    label: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    selected_duration_seconds: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=3_600,
        server_default="3600",
    )
    exposure_deadline_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    revision: Mapped[int] = mapped_column(
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

    __table_args__ = (
        CK_PORT,
        CK_DURATION,
        CK_REVISION,
        UQ_AGENT_PORT,
        UQ_HOSTNAME_KEY,
        IX_AGENT,
        IX_DEADLINE,
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
    IX_SERVICE = sa.Index(
        "ix_runtime_web_operation_receipts_service",
        "service_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    actor_kind: Mapped[RuntimeWebActorKind] = mapped_column(
        runtime_web_actor_kind_enum,
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    operation_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    operation_kind: Mapped[RuntimeWebOperationKind] = mapped_column(
        runtime_web_operation_kind_enum,
        nullable=False,
    )
    input_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    service_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_services.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (UQ_OPERATION, IX_SERVICE)


class RDBRuntimeWebQuotaScope(RDBModel):
    """Durable Agent aggregate-quota serialization row."""

    __tablename__ = "runtime_web_quota_scopes"

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )


class RDBRuntimeWebAuthConfiguration(RDBModel):
    """Current Runtime Web authentication configuration."""

    __tablename__ = "runtime_web_auth_configuration"

    CK_SINGLETON = sa.CheckConstraint(
        "id = 1",
        name="ck_runtime_web_auth_configuration_singleton",
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
    fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
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

    __table_args__ = (CK_SINGLETON,)


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
    service_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_services.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    service_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_web_services.id", ondelete="CASCADE"),
        nullable=False,
    )
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


class RDBRuntimeWebSessionRoute(RDBModel):
    """Current Owner route for one Runtime Web Runner session."""

    __tablename__ = "runtime_web_session_routes"

    CK_GENERATIONS = sa.CheckConstraint(
        "desired_generation >= 1 AND runner_generation >= 1 AND lease_generation >= 1",
        name="ck_runtime_web_session_routes_generations",
    )
    CK_DEADLINES = sa.CheckConstraint(
        "lease_expires_at > created_at "
        "AND (draining_at IS NULL OR draining_at <= lease_expires_at)",
        name="ck_runtime_web_session_routes_deadlines",
    )
    UQ_SESSION_LEASE = sa.UniqueConstraint(
        "session_lease_id",
        name="uq_runtime_web_session_routes_session_lease",
    )
    UQ_JOIN_NONCE_HASH = sa.UniqueConstraint(
        "join_nonce_hash",
        name="uq_runtime_web_session_routes_join_nonce_hash",
    )
    IX_OWNER_LEASE = sa.Index(
        "ix_runtime_web_session_routes_owner_lease",
        "owner_boot_id",
        "lease_expires_at",
    )
    IX_GENERATION = sa.Index(
        "ix_runtime_web_session_routes_generation",
        "desired_generation",
        "runner_generation",
        "lease_expires_at",
    )

    runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    desired_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    runner_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    owner_replica_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    owner_boot_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner_address: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    session_lease_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    lease_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    join_nonce_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    protocol_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    lease_expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    draining_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
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
        CK_GENERATIONS,
        CK_DEADLINES,
        UQ_SESSION_LEASE,
        UQ_JOIN_NONCE_HASH,
        IX_OWNER_LEASE,
        IX_GENERATION,
    )
