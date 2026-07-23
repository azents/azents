"""Runtime Provider contract, configuration, override, and policy persistence."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    RuntimePolicySnapshotApplicationState,
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
    RuntimeProviderContractStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


runtime_provider_contract_status_enum = ENUM(
    RuntimeProviderContractStatus,
    name="runtime_provider_contract_status",
    create_type=False,
    values_callable=_enum_values,
)
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
runtime_policy_snapshot_application_state_enum = ENUM(
    RuntimePolicySnapshotApplicationState,
    name="runtime_policy_snapshot_application_state",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeProviderContractRevision(RDBModel):
    """One immutable Provider capability contract revision."""

    __tablename__ = "runtime_provider_contract_revisions"

    UQ_PROVIDER_DIGEST = sa.UniqueConstraint(
        "provider_id",
        "digest",
        name="uq_runtime_provider_contract_revisions_provider_digest",
    )
    IX_PROVIDER_CREATED = sa.Index(
        "ix_runtime_provider_contract_revisions_provider_created",
        "provider_id",
        "created_at",
    )
    IX_PROVIDER_STATUS = sa.Index(
        "ix_runtime_provider_contract_revisions_provider_status",
        "provider_id",
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
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    implementation_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    protocol_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[RuntimeProviderContractStatus] = mapped_column(
        runtime_provider_contract_status_enum,
        nullable=False,
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
    accepted_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    accepted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    rejected_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(
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

    __table_args__ = (UQ_PROVIDER_DIGEST, IX_PROVIDER_CREATED, IX_PROVIDER_STATUS)


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


class RDBAgentRuntimeProviderOverride(RDBModel):
    """Versioned Agent-scoped Provider policy override."""

    __tablename__ = "agent_runtime_provider_overrides"

    IX_PROVIDER_ID = sa.Index(
        "ix_agent_runtime_provider_overrides_provider_id",
        "provider_id",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    contract_revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_contract_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    validation_status: Mapped[RuntimeProviderConfigValidationStatus] = mapped_column(
        runtime_provider_config_validation_status_enum,
        nullable=False,
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
    updated_by_user_id: Mapped[str | None] = mapped_column(
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
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROVIDER_ID,)


class RDBRuntimePolicySnapshot(RDBModel):
    """Immutable effective policy resolved for one logical Runtime."""

    __tablename__ = "runtime_policy_snapshots"

    IX_RUNTIME_CREATED = sa.Index(
        "ix_runtime_policy_snapshots_runtime_created",
        "runtime_id",
        "created_at",
    )
    IX_PROVIDER_CREATED = sa.Index(
        "ix_runtime_policy_snapshots_provider_created",
        "provider_id",
        "created_at",
    )
    UQ_RUNTIME_DIGEST = sa.UniqueConstraint(
        "runtime_id",
        "digest",
        name="uq_runtime_policy_snapshots_runtime_digest",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_revision_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_contract_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resolved_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_desired_generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    application_state: Mapped[RuntimePolicySnapshotApplicationState] = mapped_column(
        runtime_policy_snapshot_application_state_enum,
        nullable=False,
    )
    config_revision_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_provider_config_revisions.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    override_provider_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    override_version: Mapped[int | None] = mapped_column(
        sa.Integer,
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
    provider_acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    runtime_observed_at: Mapped[datetime.datetime | None] = mapped_column(
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

    __table_args__ = (IX_RUNTIME_CREATED, IX_PROVIDER_CREATED, UQ_RUNTIME_DIGEST)
