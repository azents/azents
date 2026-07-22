"""Runtime Provider RDB model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [v.value for v in enum_cls]


runtime_provider_scope_enum = ENUM(
    RuntimeProviderScope,
    name="runtime_provider_scope",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_kind_enum = ENUM(
    RuntimeProviderKind,
    name="runtime_provider_kind",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_registration_method_enum = ENUM(
    RuntimeProviderRegistrationMethod,
    name="runtime_provider_registration_method",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_lifecycle_state_enum = ENUM(
    RuntimeProviderLifecycleState,
    name="runtime_provider_lifecycle_state",
    create_type=False,
    values_callable=_enum_values,
)
runtime_provider_availability_mode_enum = ENUM(
    RuntimeProviderAvailabilityMode,
    name="runtime_provider_availability_mode",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProvider(RDBModel):
    """Runtime Provider configuration table."""

    __tablename__ = "runtime_providers"

    UQ_PROVIDER_ID = sa.UniqueConstraint(
        "provider_id", name="uq_runtime_providers_provider_id"
    )
    CK_WORKSPACE_SCOPE = sa.CheckConstraint(
        "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
        "(scope = 'system' AND workspace_id IS NULL)",
        name="ck_runtime_providers_workspace_scope",
    )
    IX_ENABLED_SCOPE = sa.Index(
        "ix_runtime_providers_enabled_scope", "enabled", "scope"
    )
    IX_WORKSPACE_ID = sa.Index("ix_runtime_providers_workspace_id", "workspace_id")
    IX_KIND = sa.Index("ix_runtime_providers_kind", "kind")
    IX_LIFECYCLE_ENABLED = sa.Index(
        "ix_runtime_providers_lifecycle_enabled",
        "lifecycle_state",
        "enabled",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    provider_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    scope: Mapped[RuntimeProviderScope] = mapped_column(
        runtime_provider_scope_enum, nullable=False
    )
    kind: Mapped[RuntimeProviderKind] = mapped_column(
        runtime_provider_kind_enum, nullable=False
    )
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    registration_method: Mapped[RuntimeProviderRegistrationMethod] = mapped_column(
        runtime_provider_registration_method_enum,
        init=False,
        nullable=False,
        server_default=RuntimeProviderRegistrationMethod.ADMIN.value,
    )
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean, server_default=sa.true(), nullable=False
    )
    lifecycle_state: Mapped[RuntimeProviderLifecycleState] = mapped_column(
        runtime_provider_lifecycle_state_enum,
        init=False,
        nullable=False,
        server_default=RuntimeProviderLifecycleState.ACTIVE.value,
    )
    availability_mode: Mapped[RuntimeProviderAvailabilityMode] = mapped_column(
        runtime_provider_availability_mode_enum,
        init=False,
        nullable=False,
        server_default=RuntimeProviderAvailabilityMode.PLATFORM_WIDE.value,
    )
    admin_version: Mapped[int] = mapped_column(
        sa.Integer,
        init=False,
        nullable=False,
        server_default="0",
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_contract_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "runtime_provider_contract_revisions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_runtime_providers_accepted_contract_revision_id",
        ),
        nullable=True,
        default=None,
    )
    active_config_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "runtime_provider_config_revisions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_runtime_providers_active_config_revision_id",
        ),
        nullable=True,
        default=None,
    )
    config_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True, default=None
    )
    workspace_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        UQ_PROVIDER_ID,
        CK_WORKSPACE_SCOPE,
        IX_ENABLED_SCOPE,
        IX_WORKSPACE_ID,
        IX_KIND,
        IX_LIFECYCLE_ENABLED,
    )
