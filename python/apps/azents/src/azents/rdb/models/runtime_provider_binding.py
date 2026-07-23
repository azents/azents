"""Durable Runtime Provider authentication binding persistence model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


provider_binding_state_enum = ENUM(
    RuntimeProviderBindingState,
    name="runtime_provider_binding_state",
    create_type=False,
    values_callable=_enum_values,
)
provider_binding_owner_enum = ENUM(
    RuntimeProviderBindingOwner,
    name="runtime_provider_binding_owner",
    create_type=False,
    values_callable=_enum_values,
)
provider_binding_auth_method_enum = ENUM(
    RuntimeProviderAuthMethod,
    name="runtime_provider_auth_method",
    create_type=False,
    values_callable=_enum_values,
)
provider_binding_audit_event_type_enum = ENUM(
    RuntimeProviderBindingAuditEventType,
    name="runtime_provider_binding_audit_event_type",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProviderAuthBinding(RDBModel):
    """One durable authentication identity bound to one Runtime Provider."""

    __tablename__ = "runtime_provider_auth_bindings"

    UQ_METHOD_SUBJECT_ACTIVE = sa.Index(
        "uq_runtime_provider_auth_bindings_method_subject_active",
        "auth_method",
        "subject",
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    UQ_BOOTSTRAP_DECLARATION_ACTIVE = sa.Index(
        "uq_runtime_provider_auth_bindings_bootstrap_declaration_active",
        "bootstrap_declaration_id",
        unique=True,
        postgresql_where=sa.text(
            "state = 'active' AND bootstrap_declaration_id IS NOT NULL"
        ),
    )
    IX_PROVIDER_STATE = sa.Index(
        "ix_runtime_provider_auth_bindings_provider_state",
        "provider_id",
        "state",
    )
    IX_METHOD_SUBJECT_STATE = sa.Index(
        "ix_runtime_provider_auth_bindings_method_subject_state",
        "auth_method",
        "subject",
        "state",
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
    auth_method: Mapped[RuntimeProviderAuthMethod] = mapped_column(
        provider_binding_auth_method_enum,
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    state: Mapped[RuntimeProviderBindingState] = mapped_column(
        provider_binding_state_enum,
        nullable=False,
    )
    owner: Mapped[RuntimeProviderBindingOwner] = mapped_column(
        provider_binding_owner_enum,
        nullable=False,
    )
    bootstrap_declaration_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "runtime_provider_bootstrap_declarations.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        default=None,
    )
    config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    admin_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default=sa.text("1"),
    )
    last_authenticated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    last_connected_at: Mapped[datetime.datetime | None] = mapped_column(
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
    revocation_reason: Mapped[str | None] = mapped_column(
        sa.String(255),
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

    __table_args__ = (
        UQ_METHOD_SUBJECT_ACTIVE,
        UQ_BOOTSTRAP_DECLARATION_ACTIVE,
        IX_PROVIDER_STATE,
        IX_METHOD_SUBJECT_STATE,
    )


class RDBRuntimeProviderAuthBindingAuditEvent(RDBModel):
    """Append-only metadata-only authentication binding audit event."""

    __tablename__ = "runtime_provider_auth_binding_audit_events"

    IX_BINDING_CREATED = sa.Index(
        "ix_runtime_provider_auth_binding_audit_events_binding_created",
        "binding_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_auth_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[RuntimeProviderBindingAuditEventType] = mapped_column(
        provider_binding_audit_event_type_enum,
        nullable=False,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    previous_admin_version: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    new_admin_version: Mapped[int | None] = mapped_column(
        sa.Integer,
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

    __table_args__ = (IX_BINDING_CREATED,)
