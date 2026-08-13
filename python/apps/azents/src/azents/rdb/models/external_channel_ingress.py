"""Durable active External Channel conversation ingress models."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressItemState,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    external_channel_conversation_scope_kind_enum,
    external_channel_ingress_profile_enum,
    external_channel_provider_enum,
    external_channel_response_mode_enum,
)
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


external_channel_ingress_authority_kind_enum = ENUM(
    ExternalChannelIngressAuthorityKind,
    name="external_channel_ingress_authority_kind",
    create_type=False,
    values_callable=_enum_values,
)
external_channel_ingress_item_state_enum = ENUM(
    ExternalChannelIngressItemState,
    name="external_channel_ingress_item_state",
    create_type=False,
    values_callable=_enum_values,
)


class RDBExternalChannelIngressOwner(RDBModel):
    """One active drain owner for an effective provider conversation."""

    __tablename__ = "external_channel_ingress_owners"

    UQ_TARGET_RESOURCE = sa.UniqueConstraint(
        "target_resource_id",
        name="uq_external_channel_ingress_owners_target_resource",
    )
    IX_RECOVERY = sa.Index(
        "ix_external_channel_ingress_owners_recovery",
        "preparation_next_attempt_at",
        "lease_expires_at",
        "updated_at",
    )
    CK_LEASE = sa.CheckConstraint(
        "(lease_owner IS NULL AND lease_acquired_at IS NULL "
        "AND lease_expires_at IS NULL) OR "
        "(lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL "
        "AND lease_expires_at IS NOT NULL)",
        name="ck_external_channel_ingress_owners_lease",
    )
    CK_BATCH = sa.CheckConstraint(
        "(current_batch_id IS NULL AND current_batch_started_at IS NULL) OR "
        "(current_batch_id IS NOT NULL AND current_batch_started_at IS NOT NULL "
        "AND lease_owner IS NOT NULL)",
        name="ck_external_channel_ingress_owners_batch",
    )
    CK_READY = sa.CheckConstraint(
        "(binding_id IS NULL AND session_id IS NULL) OR "
        "(binding_id IS NOT NULL AND session_id IS NOT NULL)",
        name="ck_external_channel_ingress_owners_ready",
    )
    CK_SETTING = sa.CheckConstraint(
        "(participation_setting_id IS NULL "
        "AND participation_settings_generation IS NULL) OR "
        "(participation_setting_id IS NOT NULL "
        "AND participation_settings_generation IS NOT NULL)",
        name="ck_external_channel_ingress_owners_setting",
    )
    CK_PREPARATION_ATTEMPTS = sa.CheckConstraint(
        "preparation_attempt_count >= 0 AND preparation_attempt_count <= 5",
        name="ck_external_channel_ingress_owners_preparation_attempt_count",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    route_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_agent_routes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    participation_setting_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "external_channel_participation_settings.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    participation_settings_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    response_mode: Mapped[ExternalChannelResponseMode] = mapped_column(
        external_channel_response_mode_enum,
        nullable=False,
    )
    binding_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    preparation_attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    preparation_next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    lease_generation: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lease_acquired_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    first_batch_pending: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.true(),
    )
    current_batch_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    current_batch_started_at: Mapped[datetime.datetime | None] = mapped_column(
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
        UQ_TARGET_RESOURCE,
        IX_RECOVERY,
        CK_LEASE,
        CK_BATCH,
        CK_READY,
        CK_SETTING,
        CK_PREPARATION_ATTEMPTS,
    )


class RDBExternalChannelIngressItem(RDBModel):
    """One active content-free provider trigger awaiting canonical admission."""

    __tablename__ = "external_channel_ingress_items"

    UQ_ACTIVE_IDENTITY = sa.UniqueConstraint(
        "owner_id",
        "deduplication_key",
        name="uq_external_channel_ingress_items_active_identity",
    )
    UQ_QUEUE_KEY = sa.UniqueConstraint(
        "queue_key",
        name="uq_external_channel_ingress_items_queue_key",
    )
    IX_OWNER_DUE_QUEUE = sa.Index(
        "ix_external_channel_ingress_items_owner_due_queue",
        "owner_id",
        "state",
        "next_attempt_at",
        "queue_key",
    )
    IX_POSITION = sa.Index(
        "ix_external_channel_ingress_items_position",
        "conversation_position_id",
        "trigger_position",
    )
    CK_SCOPE_KEY = sa.CheckConstraint(
        "(scope_kind = 'parent_channel' AND provider_thread_key IS NULL) OR "
        "(scope_kind = 'thread' AND provider_thread_key IS NOT NULL)",
        name="ck_external_channel_ingress_items_scope_key",
    )
    CK_ATTEMPT_COUNT = sa.CheckConstraint(
        "attempt_count >= 0 AND attempt_count <= 5",
        name="ck_external_channel_ingress_items_attempt_count",
    )
    CK_EXPECTED_FILE_COUNT = sa.CheckConstraint(
        "expected_file_count IS NULL OR "
        "(expected_file_count >= 0 AND expected_file_count <= 20)",
        name="ck_external_channel_ingress_items_expected_file_count",
    )
    CK_ACTIVE_STATE = sa.CheckConstraint(
        "("
        "state = 'pending' AND next_attempt_at IS NULL "
        "AND processing_owner IS NULL AND processing_generation IS NULL "
        "AND batch_id IS NULL"
        ") OR ("
        "state = 'retry_waiting' AND next_attempt_at IS NOT NULL "
        "AND processing_owner IS NULL AND processing_generation IS NULL "
        "AND batch_id IS NULL"
        ") OR ("
        "state = 'processing' AND next_attempt_at IS NULL "
        "AND processing_owner IS NOT NULL AND processing_generation IS NOT NULL "
        "AND batch_id IS NOT NULL"
        ")",
        name="ck_external_channel_ingress_items_active_state",
    )
    CK_AUTHORITY = sa.CheckConstraint(
        "(authority_kind = 'lease' AND authority_lease_owner IS NOT NULL) OR "
        "(authority_kind <> 'lease' AND authority_lease_owner IS NULL "
        "AND authority_lease_generation IS NULL)",
        name="ck_external_channel_ingress_items_authority",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    owner_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_ingress_owners.id", ondelete="CASCADE"),
        nullable=False,
    )
    queue_key: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    ingress_profile: Mapped[ExternalChannelIngressProfile] = mapped_column(
        external_channel_ingress_profile_enum,
        nullable=False,
    )
    configuration_generation: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    authority_kind: Mapped[ExternalChannelIngressAuthorityKind] = mapped_column(
        external_channel_ingress_authority_kind_enum,
        nullable=False,
    )
    authority_lease_owner: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    authority_lease_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    provider_event_type: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    provider_tenant_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    scope_kind: Mapped[ExternalChannelConversationScopeKind] = mapped_column(
        external_channel_conversation_scope_kind_enum,
        nullable=False,
    )
    provider_channel_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_parent_channel_id: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    provider_thread_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    delivery_thread_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider_resource_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_resource_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_resources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    conversation_position_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "external_channel_conversation_positions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trigger_provider_message_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trigger_provider_message_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trigger_position: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_user_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    invocation: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    expected_file_count: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    invocation_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    initial_title_eligible: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
    )
    state: Mapped[ExternalChannelIngressItemState] = mapped_column(
        external_channel_ingress_item_state_enum,
        nullable=False,
        default=ExternalChannelIngressItemState.PENDING,
        server_default=ExternalChannelIngressItemState.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    processing_owner: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    processing_generation: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    batch_id: Mapped[str | None] = mapped_column(
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
        UQ_ACTIVE_IDENTITY,
        UQ_QUEUE_KEY,
        IX_OWNER_DUE_QUEUE,
        IX_POSITION,
        CK_SCOPE_KEY,
        CK_ATTEMPT_COUNT,
        CK_EXPECTED_FILE_COUNT,
        CK_ACTIVE_STATE,
        CK_AUTHORITY,
    )
