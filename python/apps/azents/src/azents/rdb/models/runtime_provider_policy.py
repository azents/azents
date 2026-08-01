"""Runtime Provider capability and operational configuration persistence."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


runtime_provider_config_revision_state_enum = ENUM(
    RuntimeProviderConfigRevisionState,
    name="runtime_provider_config_revision_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_config_validation_status_enum = ENUM(
    RuntimeProviderConfigValidationStatus,
    name="runtime_provider_config_validation_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProviderContractRevision(RDBModel):
    """One immutable Provider capability contract revision."""

    __tablename__ = "runtime_provider_contract_revisions"

    IX_PROVIDER_CREATED = sa.Index(
        "ix_runtime_provider_contract_revisions_provider_created",
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
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    implementation_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROVIDER_CREATED,)


class RDBRuntimeProviderConfigRevision(RDBModel):
    """One immutable Provider-scoped product configuration revision."""

    __tablename__ = "runtime_provider_config_revisions"

    UQ_PROVIDER_REVISION = sa.UniqueConstraint(
        "provider_id",
        "revision",
        name="uq_runtime_provider_config_revisions_provider_revision",
    )
    IX_PROVIDER_STATE = sa.Index(
        "ix_runtime_provider_config_revisions_provider_state",
        "provider_id",
        "state",
    )
    IX_VALIDATION_REQUEST = sa.Index(
        "ix_runtime_provider_config_revisions_validation_request",
        "validation_request_id",
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
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    contract_revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_contract_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[RuntimeProviderConfigRevisionState] = mapped_column(
        runtime_provider_config_revision_state_enum,
        nullable=False,
    )
    validation_status: Mapped[RuntimeProviderConfigValidationStatus] = mapped_column(
        runtime_provider_config_validation_status_enum,
        nullable=False,
    )
    base_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "runtime_provider_config_revisions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_runtime_provider_config_revisions_base_revision_id",
        ),
        nullable=True,
        default=None,
    )
    encrypted_secrets: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    secret_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=dict,
    )
    validation_request_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    validation_code: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    validation_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    validation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    impact: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    activated_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    activated_at: Mapped[datetime.datetime | None] = mapped_column(
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

    __table_args__ = (UQ_PROVIDER_REVISION, IX_PROVIDER_STATE, IX_VALIDATION_REQUEST)
