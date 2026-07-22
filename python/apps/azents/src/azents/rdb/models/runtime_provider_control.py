"""Runtime Provider enrollment, credential, and connection persistence models."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    RuntimeProviderConnectionStatus,
    RuntimeProviderCredentialState,
    RuntimeProviderEnrollmentGrantState,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


provider_enrollment_grant_state_enum = ENUM(
    RuntimeProviderEnrollmentGrantState,
    name="runtime_provider_enrollment_grant_state",
    create_type=False,
    values_callable=_enum_values,
)
provider_credential_state_enum = ENUM(
    RuntimeProviderCredentialState,
    name="runtime_provider_credential_state",
    create_type=False,
    values_callable=_enum_values,
)
provider_connection_status_enum = ENUM(
    RuntimeProviderConnectionStatus,
    name="runtime_provider_connection_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProviderEnrollmentGrant(RDBModel):
    """One-time enrollment grant verifier bound to a known Provider."""

    __tablename__ = "runtime_provider_enrollment_grants"

    IX_PROVIDER_STATE = sa.Index(
        "ix_runtime_provider_enrollment_grants_provider_state",
        "provider_id",
        "state",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_runtime_provider_enrollment_grants_expires_at",
        "expires_at",
    )
    CK_ISSUER = sa.CheckConstraint(
        "(issued_by_user_id IS NOT NULL AND issued_by_source_id IS NULL) OR "
        "(issued_by_user_id IS NULL AND issued_by_source_id IS NOT NULL)",
        name="ck_runtime_provider_enrollment_grants_issuer",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verifier: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    state: Mapped[RuntimeProviderEnrollmentGrantState] = mapped_column(
        provider_enrollment_grant_state_enum,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    issued_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    issued_by_source_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "runtime_provider_bootstrap_sources.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        default=None,
    )
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    consumed_credential_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROVIDER_STATE, IX_EXPIRES_AT, CK_ISSUER)


class RDBRuntimeProviderCredential(RDBModel):
    """Verifier-backed credential bound to one durable Provider."""

    __tablename__ = "runtime_provider_credentials"

    IX_PROVIDER_STATE = sa.Index(
        "ix_runtime_provider_credentials_provider_state",
        "provider_id",
        "state",
    )
    IX_EXPIRES_AT = sa.Index("ix_runtime_provider_credentials_expires_at", "expires_at")

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verifier: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    state: Mapped[RuntimeProviderCredentialState] = mapped_column(
        provider_credential_state_enum,
        nullable=False,
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
    )
    issued_grant_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_enrollment_grants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROVIDER_STATE, IX_EXPIRES_AT)


class RDBRuntimeProviderConnection(RDBModel):
    """Durable authenticated Provider Control connection projection."""

    __tablename__ = "runtime_provider_connections"

    UQ_CONNECTION_ID = sa.UniqueConstraint(
        "connection_id",
        name="uq_runtime_provider_connections_connection_id",
    )
    UQ_PROVIDER_GENERATION = sa.UniqueConstraint(
        "provider_id",
        "generation",
        name="uq_runtime_provider_connections_provider_generation",
    )
    IX_PROVIDER_STATUS = sa.Index(
        "ix_runtime_provider_connections_provider_status",
        "provider_id",
        "status",
    )
    IX_CREDENTIAL_STATUS = sa.Index(
        "ix_runtime_provider_connections_credential_status",
        "credential_id",
        "status",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    credential_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    connection_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[RuntimeProviderConnectionStatus] = mapped_column(
        provider_connection_status_enum,
        nullable=False,
    )
    reported_provider_type: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    reported_protocol_version: Mapped[str] = mapped_column(
        sa.String(120),
        nullable=False,
    )
    connected_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    last_heartbeat_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    disconnected_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        UQ_CONNECTION_ID,
        UQ_PROVIDER_GENERATION,
        IX_PROVIDER_STATUS,
        IX_CREDENTIAL_STATUS,
    )
