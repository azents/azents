"""Workspace Runtime Profile and Provider infrastructure Profile persistence."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent_runtime as _agent_runtime  # noqa: F401
import azents.rdb.models.runtime_provider as _runtime_provider  # noqa: F401
import azents.rdb.models.user as _user  # noqa: F401
import azents.rdb.models.workspace as _workspace  # noqa: F401
import azents.rdb.models.workspace_user as _workspace_user  # noqa: F401
from azents.core.runtime_profile import (
    RuntimeConfigurationStateStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    RuntimeReconcileTaskStatus,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


runtime_infrastructure_profile_kind_enum = ENUM(
    RuntimeInfrastructureProfileKind,
    name="runtime_infrastructure_profile_kind",
    create_type=False,
    values_callable=_enum_values,
)
runtime_profile_lifecycle_enum = ENUM(
    RuntimeProfileLifecycle,
    name="runtime_profile_lifecycle",
    create_type=False,
    values_callable=_enum_values,
)
runtime_configuration_state_status_enum = ENUM(
    RuntimeConfigurationStateStatus,
    name="runtime_configuration_state_status",
    create_type=False,
    values_callable=_enum_values,
)
runtime_reconcile_task_status_enum = ENUM(
    RuntimeReconcileTaskStatus,
    name="runtime_reconcile_task_status",
    create_type=False,
    values_callable=_enum_values,
)
runtime_reconcile_source_kind_enum = ENUM(
    RuntimeReconcileSourceKind,
    name="runtime_reconcile_source_kind",
    create_type=False,
    values_callable=_enum_values,
)
runtime_recreation_operation_status_enum = ENUM(
    RuntimeRecreationOperationStatus,
    name="runtime_recreation_operation_status",
    create_type=False,
    values_callable=_enum_values,
)
runtime_recreation_item_status_enum = ENUM(
    RuntimeRecreationItemStatus,
    name="runtime_recreation_item_status",
    create_type=False,
    values_callable=_enum_values,
)
runtime_recreation_target_kind_enum = ENUM(
    RuntimeRecreationTargetKind,
    name="runtime_recreation_target_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeInfrastructureProfile(RDBModel):
    """One mutable infrastructure Profile owned by an exact Provider."""

    __tablename__ = "runtime_infrastructure_profiles"

    UQ_PROVIDER_NAME = sa.UniqueConstraint(
        "provider_id",
        "display_name",
        name="uq_runtime_infrastructure_profiles_provider_name",
    )
    UQ_PROVIDER_ID = sa.UniqueConstraint(
        "provider_id",
        "id",
        name="uq_runtime_infrastructure_profiles_provider_id",
    )
    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1",
        name="ck_runtime_infrastructure_profiles_version_positive",
    )
    IX_PROVIDER_LIFECYCLE = sa.Index(
        "ix_runtime_infrastructure_profiles_provider_lifecycle",
        "provider_id",
        "lifecycle",
    )
    IX_KIND = sa.Index("ix_runtime_infrastructure_profiles_kind", "profile_kind")

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    provider_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    profile_kind: Mapped[RuntimeInfrastructureProfileKind] = mapped_column(
        runtime_infrastructure_profile_kind_enum,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lifecycle: Mapped[RuntimeProfileLifecycle] = mapped_column(
        runtime_profile_lifecycle_enum,
        nullable=False,
    )
    contract_family: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required_capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    terminal_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
        UQ_PROVIDER_NAME,
        UQ_PROVIDER_ID,
        CK_VERSION_POSITIVE,
        IX_PROVIDER_LIFECYCLE,
        IX_KIND,
    )


class RDBWorkspaceRuntimeProfile(RDBModel):
    """One complete Runtime choice owned by one Workspace."""

    __tablename__ = "workspace_runtime_profiles"

    UQ_WORKSPACE_NAME = sa.UniqueConstraint(
        "workspace_id", "display_name", name="uq_workspace_runtime_profiles_name"
    )
    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1", name="ck_workspace_runtime_profiles_version_positive"
    )
    IX_WORKSPACE_LIFECYCLE = sa.Index(
        "ix_workspace_runtime_profiles_workspace_lifecycle",
        "workspace_id",
        "lifecycle",
    )
    IX_PROVIDER = sa.Index("ix_workspace_runtime_profiles_provider_id", "provider_id")
    IX_INFRASTRUCTURE = sa.Index(
        "ix_workspace_runtime_profiles_infrastructure_profile_id",
        "infrastructure_profile_id",
    )
    FK_PROVIDER_INFRASTRUCTURE = sa.ForeignKeyConstraint(
        ["provider_id", "infrastructure_profile_id"],
        [
            "runtime_infrastructure_profiles.provider_id",
            "runtime_infrastructure_profiles.id",
        ],
        name="fk_workspace_runtime_profiles_provider_infrastructure",
        ondelete="RESTRICT",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    infrastructure_profile_id: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lifecycle: Mapped[RuntimeProfileLifecycle] = mapped_column(
        runtime_profile_lifecycle_enum,
        nullable=False,
    )
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terminal_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
        nullable=True,
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
        UQ_WORKSPACE_NAME,
        CK_VERSION_POSITIVE,
        IX_WORKSPACE_LIFECYCLE,
        IX_PROVIDER,
        IX_INFRASTRUCTURE,
        FK_PROVIDER_INFRASTRUCTURE,
    )


class RDBRuntimeConfigurationState(RDBModel):
    """One bounded desired/applied Runtime configuration state row."""

    __tablename__ = "runtime_configuration_states"

    runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    desired_sequence: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    desired_status: Mapped[RuntimeConfigurationStateStatus] = mapped_column(
        runtime_configuration_state_status_enum,
        nullable=False,
    )
    desired_target_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    desired_digest: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    desired_document: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True, default=None
    )
    desired_reason_code: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
    )
    provider_reported_digest: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    runner_reported_digest: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    provider_acknowledged_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )
    runner_observed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )
    applied_sequence: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, default=None
    )
    applied_target_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, default=None
    )
    applied_digest: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    applied_document: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True, default=None
    )
    applied_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
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

    CK_DESIRED = sa.CheckConstraint(
        "(desired_status = 'unconfigured' AND desired_digest IS NULL "
        "AND desired_document IS NULL "
        "AND desired_reason_code = 'runtime_profile_required') "
        "OR (desired_status = 'blocked' AND desired_reason_code IS NOT NULL) "
        "OR (desired_status = 'ready' AND desired_digest IS NOT NULL "
        "AND desired_document IS NOT NULL AND desired_reason_code IS NULL)",
        name="ck_runtime_configuration_states_desired",
    )
    CK_SEQUENCE = sa.CheckConstraint(
        "desired_sequence >= 1 AND (applied_sequence IS NULL OR applied_sequence >= 1)",
        name="ck_runtime_configuration_states_sequence",
    )
    CK_APPLIED = sa.CheckConstraint(
        "(applied_sequence IS NULL AND applied_target_generation IS NULL "
        "AND applied_digest IS NULL "
        "AND applied_document IS NULL AND applied_at IS NULL) "
        "OR (applied_sequence IS NOT NULL AND applied_target_generation IS NOT NULL "
        "AND applied_digest IS NOT NULL AND applied_document IS NOT NULL "
        "AND applied_at IS NOT NULL)",
        name="ck_runtime_configuration_states_applied",
    )

    __table_args__ = (CK_DESIRED, CK_SEQUENCE, CK_APPLIED)


class RDBRuntimeConfigurationReconcileTask(RDBModel):
    """Durable bounded fan-out task for authoritative desired configuration."""

    __tablename__ = "runtime_configuration_reconcile_tasks"

    UQ_SOURCE_VERSION = sa.UniqueConstraint(
        "source_type",
        "source_id",
        "source_version",
        name="uq_runtime_configuration_reconcile_tasks_source_version",
    )
    CK_ATTEMPT = sa.CheckConstraint(
        "attempt >= 0",
        name="ck_runtime_configuration_reconcile_tasks_attempt",
    )
    IX_STATUS_AVAILABLE = sa.Index(
        "ix_runtime_configuration_reconcile_tasks_status_available",
        "status",
        "available_at",
    )
    IX_SOURCE = sa.Index(
        "ix_runtime_configuration_reconcile_tasks_source", "source_type", "source_id"
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    source_type: Mapped[RuntimeReconcileSourceKind] = mapped_column(
        runtime_reconcile_source_kind_enum,
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    source_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    status: Mapped[RuntimeReconcileTaskStatus] = mapped_column(
        runtime_reconcile_task_status_enum,
        nullable=False,
    )
    available_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    cursor: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
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
        UQ_SOURCE_VERSION,
        CK_ATTEMPT,
        IX_STATUS_AVAILABLE,
        IX_SOURCE,
    )


class RDBRuntimeRecreationOperation(RDBModel):
    """One authority-scoped durable Runtime recreation operation."""

    __tablename__ = "runtime_recreation_operations"

    CK_CONCURRENCY = sa.CheckConstraint(
        "concurrency_limit >= 1",
        name="ck_runtime_recreation_operations_concurrency",
    )
    CK_COUNTS = sa.CheckConstraint(
        "total_count >= 0 AND pending_count >= 0 AND running_count >= 0 "
        "AND succeeded_count >= 0 AND skipped_count >= 0 AND failed_count >= 0",
        name="ck_runtime_recreation_operations_counts",
    )
    CK_ACTOR_SCOPE = sa.CheckConstraint(
        "actor_user_id IS NULL OR actor_workspace_user_id IS NULL",
        name="ck_runtime_recreation_operations_actor_scope",
    )
    IX_STATUS = sa.Index("ix_runtime_recreation_operations_status", "status")
    IX_TARGET = sa.Index(
        "ix_runtime_recreation_operations_target", "target_kind", "target_id"
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    target_kind: Mapped[RuntimeRecreationTargetKind] = mapped_column(
        runtime_recreation_target_kind_enum,
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    target_version: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    status: Mapped[RuntimeRecreationOperationStatus] = mapped_column(
        runtime_recreation_operation_status_enum,
        nullable=False,
    )
    concurrency_limit: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    running_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now(), nullable=False
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )

    __table_args__ = (
        CK_CONCURRENCY,
        CK_COUNTS,
        CK_ACTOR_SCOPE,
        IX_STATUS,
        IX_TARGET,
    )


class RDBRuntimeRecreationOperationItem(RDBModel):
    """One Runtime item in a durable recreation operation."""

    __tablename__ = "runtime_recreation_operation_items"

    UQ_OPERATION_RUNTIME = sa.UniqueConstraint(
        "operation_id",
        "runtime_id",
        name="uq_runtime_recreation_operation_items_operation_runtime",
    )
    CK_ATTEMPT = sa.CheckConstraint(
        "attempt >= 0",
        name="ck_runtime_recreation_operation_items_attempt",
    )
    IX_OPERATION_STATUS = sa.Index(
        "ix_runtime_recreation_operation_items_operation_status",
        "operation_id",
        "status",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    operation_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_recreation_operations.id", ondelete="CASCADE"),
        nullable=False,
    )
    runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expected_configuration_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_configuration_digest: Mapped[str] = mapped_column(
        sa.String(64), nullable=False
    )
    expected_desired_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    status: Mapped[RuntimeRecreationItemStatus] = mapped_column(
        runtime_recreation_item_status_enum,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    dispatched_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    failure_code: Mapped[str | None] = mapped_column(
        sa.String(120), nullable=True, default=None
    )
    failure_message: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
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

    CK_EXPECTED_EVIDENCE = sa.CheckConstraint(
        "expected_configuration_sequence >= 1 AND expected_desired_generation >= 0",
        name="ck_runtime_recreation_operation_items_expected_evidence",
    )

    __table_args__ = (
        UQ_OPERATION_RUNTIME,
        CK_ATTEMPT,
        IX_OPERATION_STATUS,
        CK_EXPECTED_EVIDENCE,
    )
