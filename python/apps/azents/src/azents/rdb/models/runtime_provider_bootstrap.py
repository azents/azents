"""Runtime Provider bootstrap and availability persistence models."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.user as _  # noqa: F401  # Register FK target metadata.
from azents.core.enums import (
    RuntimeProviderAuditEventType,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderKind,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.runtime_provider import runtime_provider_kind_enum
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


bootstrap_adapter_kind_enum = ENUM(
    RuntimeProviderBootstrapAdapterKind,
    name="runtime_provider_bootstrap_adapter_kind",
    create_type=False,
    values_callable=_enum_values,
)
bootstrap_declaration_state_enum = ENUM(
    RuntimeProviderBootstrapDeclarationState,
    name="runtime_provider_bootstrap_declaration_state",
    create_type=False,
    values_callable=_enum_values,
)
provider_audit_event_type_enum = ENUM(
    RuntimeProviderAuditEventType,
    name="runtime_provider_audit_event_type",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProviderBootstrapSource(RDBModel):
    """Trusted source that supplies authoritative Provider declarations."""

    __tablename__ = "runtime_provider_bootstrap_sources"

    UQ_SOURCE_KEY = sa.UniqueConstraint(
        "source_key",
        name="uq_runtime_provider_bootstrap_sources_source_key",
    )
    IX_ADAPTER_KIND = sa.Index(
        "ix_runtime_provider_bootstrap_sources_adapter_kind",
        "adapter_kind",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    source_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    adapter_kind: Mapped[RuntimeProviderBootstrapAdapterKind] = mapped_column(
        bootstrap_adapter_kind_enum,
        nullable=False,
    )
    last_revision: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    last_digest: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    last_reconciled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    error_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    error_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (UQ_SOURCE_KEY, IX_ADAPTER_KIND)


class RDBRuntimeProviderBootstrapDeclaration(RDBModel):
    """One durable Provider declaration from a trusted bootstrap source."""

    __tablename__ = "runtime_provider_bootstrap_declarations"

    UQ_SOURCE_DECLARATION_KEY = sa.UniqueConstraint(
        "source_id",
        "declaration_key",
        name="uq_runtime_provider_bootstrap_declarations_source_key",
    )
    UQ_PROVIDER_ID = sa.UniqueConstraint(
        "provider_id",
        name="uq_runtime_provider_bootstrap_declarations_provider_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    source_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_bootstrap_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_logical_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    kind: Mapped[RuntimeProviderKind] = mapped_column(
        runtime_provider_kind_enum,
        nullable=False,
    )
    provider_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    declaration_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_revision: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    state: Mapped[RuntimeProviderBootstrapDeclarationState] = mapped_column(
        bootstrap_declaration_state_enum,
        nullable=False,
    )
    creation_seeds: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    conflict_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    conflict_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    withdrawn_at: Mapped[datetime.datetime | None] = mapped_column(
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
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (UQ_SOURCE_DECLARATION_KEY, UQ_PROVIDER_ID)


class RDBRuntimeProviderWorkspaceAvailability(RDBModel):
    """Explicit Workspace membership for selected-Workspace Providers."""

    __tablename__ = "runtime_provider_workspace_availability"

    IX_WORKSPACE_ID = sa.Index(
        "ix_runtime_provider_workspace_availability_workspace_id",
        "workspace_id",
    )

    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_WORKSPACE_ID,)


class RDBRuntimeProviderAuditEvent(RDBModel):
    """Append-only metadata-only audit event for Provider aggregate changes."""

    __tablename__ = "runtime_provider_audit_events"

    IX_PROVIDER_CREATED = sa.Index(
        "ix_runtime_provider_audit_events_provider_created",
        "provider_id",
        "created_at",
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
    event_type: Mapped[RuntimeProviderAuditEventType] = mapped_column(
        provider_audit_event_type_enum,
        nullable=False,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROVIDER_CREATED,)
