"""Runtime execution policy persistence models."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent as _agent  # noqa: F401  # pyright: ignore[reportUnusedImport]
import azents.rdb.models.agent_runtime as _agent_runtime  # noqa: F401  # pyright: ignore[reportUnusedImport]
import azents.rdb.models.user as _user  # noqa: F401  # pyright: ignore[reportUnusedImport]
import azents.rdb.models.workspace as _workspace  # noqa: F401  # pyright: ignore[reportUnusedImport]
import azents.rdb.models.workspace_user as _workspace_user  # noqa: F401  # pyright: ignore[reportUnusedImport]
from azents.core.runtime_execution_policy import (
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionProfileLifecycle,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


runtime_execution_profile_lifecycle_enum = ENUM(
    RuntimeExecutionProfileLifecycle,
    name="runtime_execution_profile_lifecycle",
    create_type=False,
    values_callable=_enum_values,
)
runtime_execution_audit_event_type_enum = ENUM(
    RuntimeExecutionAuditEventType,
    name="runtime_execution_audit_event_type",
    create_type=False,
    values_callable=_enum_values,
)
runtime_execution_management_layer_enum = ENUM(
    RuntimeExecutionManagementLayer,
    name="runtime_execution_management_layer",
    create_type=False,
    values_callable=_enum_values,
)
runtime_execution_change_direction_enum = ENUM(
    RuntimeExecutionChangeDirection,
    name="runtime_execution_change_direction",
    create_type=False,
    values_callable=_enum_values,
)


class RDBRuntimeExecutionPlatformPolicy(RDBModel):
    """Current installation-wide execution-policy ceiling."""

    __tablename__ = "runtime_execution_platform_policies"

    CK_SINGLETON_ID = sa.CheckConstraint(
        "id = 'platform'",
        name="ck_runtime_execution_platform_policies_singleton_id",
    )
    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1",
        name="ck_runtime_execution_platform_policies_version_positive",
    )
    IX_UPDATED_BY_USER_ID = sa.Index(
        "ix_runtime_execution_platform_policies_updated_by_user_id",
        "updated_by_user_id",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
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

    __table_args__ = (
        CK_SINGLETON_ID,
        CK_VERSION_POSITIVE,
        IX_UPDATED_BY_USER_ID,
    )


class RDBRuntimeExecutionProfile(RDBModel):
    """Stable mutable named Runtime execution Profile."""

    __tablename__ = "runtime_execution_profiles"

    UQ_SYSTEM_KEY = sa.UniqueConstraint(
        "system_key",
        name="uq_runtime_execution_profiles_system_key",
    )
    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1",
        name="ck_runtime_execution_profiles_version_positive",
    )
    IX_LIFECYCLE = sa.Index(
        "ix_runtime_execution_profiles_lifecycle",
        "lifecycle",
    )
    IX_UPDATED_BY_USER_ID = sa.Index(
        "ix_runtime_execution_profiles_updated_by_user_id",
        "updated_by_user_id",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lifecycle: Mapped[RuntimeExecutionProfileLifecycle] = mapped_column(
        runtime_execution_profile_lifecycle_enum,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    reserved: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    system_key: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
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

    __table_args__ = (
        UQ_SYSTEM_KEY,
        CK_VERSION_POSITIVE,
        IX_LIFECYCLE,
        IX_UPDATED_BY_USER_ID,
    )


class RDBWorkspaceRuntimeExecutionPolicy(RDBModel):
    """Current restrictive Runtime execution policy for one Workspace."""

    __tablename__ = "workspace_runtime_execution_policies"

    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1",
        name="ck_workspace_runtime_execution_policies_version_positive",
    )
    IX_UPDATED_BY_WORKSPACE_USER_ID = sa.Index(
        "ix_workspace_runtime_exec_policies_updated_by_workspace_user",
        "updated_by_workspace_user_id",
    )

    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    restriction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    updated_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
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

    __table_args__ = (CK_VERSION_POSITIVE, IX_UPDATED_BY_WORKSPACE_USER_ID)


class RDBWorkspaceRuntimeExecutionProfileAllowance(RDBModel):
    """One Profile explicitly available to one Workspace."""

    __tablename__ = "workspace_runtime_execution_profile_allowances"

    IX_PROFILE_ID = sa.Index(
        "ix_workspace_runtime_execution_profile_allowances_profile_id",
        "profile_id",
    )

    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "workspace_runtime_execution_policies.workspace_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    profile_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_execution_profiles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (IX_PROFILE_ID,)


class RDBAgentRuntimeExecutionSetting(RDBModel):
    """Current Agent Profile selection and restrictive overrides."""

    __tablename__ = "agent_runtime_execution_settings"

    CK_VERSION_POSITIVE = sa.CheckConstraint(
        "version >= 1",
        name="ck_agent_runtime_execution_settings_version_positive",
    )
    IX_PROFILE_ID = sa.Index(
        "ix_agent_runtime_execution_settings_profile_id",
        "profile_id",
    )
    IX_UPDATED_BY_WORKSPACE_USER_ID = sa.Index(
        "ix_agent_runtime_exec_settings_updated_by_workspace_user",
        "updated_by_workspace_user_id",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    profile_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("runtime_execution_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    restriction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    updated_by_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
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
        CK_VERSION_POSITIVE,
        IX_PROFILE_ID,
        IX_UPDATED_BY_WORKSPACE_USER_ID,
    )


class RDBRuntimeExecutionPolicyAuditEvent(RDBModel):
    """Append-only metadata-only execution-policy audit event."""

    __tablename__ = "runtime_execution_policy_audit_events"

    IX_TARGET_CREATED = sa.Index(
        "ix_runtime_execution_policy_audit_events_target_created",
        "target_id",
        "created_at",
    )
    IX_WORKSPACE_CREATED = sa.Index(
        "ix_runtime_execution_policy_audit_events_workspace_created",
        "workspace_id",
        "created_at",
    )
    IX_AGENT_CREATED = sa.Index(
        "ix_runtime_execution_policy_audit_events_agent_created",
        "agent_id",
        "created_at",
    )
    IX_RUNTIME_CREATED = sa.Index(
        "ix_runtime_execution_policy_audit_events_runtime_created",
        "runtime_id",
        "created_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    event_type: Mapped[RuntimeExecutionAuditEventType] = mapped_column(
        runtime_execution_audit_event_type_enum,
        nullable=False,
    )
    management_layer: Mapped[RuntimeExecutionManagementLayer] = mapped_column(
        runtime_execution_management_layer_enum,
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    correlation_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    classification: Mapped[RuntimeExecutionChangeDirection] = mapped_column(
        runtime_execution_change_direction_enum,
        nullable=False,
    )
    changed_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    impact_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    reason_code: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    outcome_code: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
    )
    workspace_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    runtime_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    actor_workspace_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    system_authority: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
    )
    before_digest: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        default=None,
    )
    after_digest: Mapped[str | None] = mapped_column(
        sa.String(64),
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
        IX_TARGET_CREATED,
        IX_WORKSPACE_CREATED,
        IX_AGENT_CREATED,
        IX_RUNTIME_CREATED,
    )
