"""Private external-channel model drafts and immutable mutation audit."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ExternalChannelProvider
from azents.core.external_model_settings import ExternalModelNoticeOutcome
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import external_channel_provider_enum
from azents.rdb.models.inference_profile_types import model_reasoning_effort_enum
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[ExternalModelNoticeOutcome]) -> list[str]:
    """Return string values stored for the notice outcome enum."""
    return [value.value for value in enum_cls]


external_model_notice_outcome_enum = ENUM(
    ExternalModelNoticeOutcome,
    name="external_model_notice_outcome",
    create_type=False,
    values_callable=_enum_values,
)


class RDBExternalModelDraft(RDBModel):
    """Bounded actor- and interaction-owned private model draft."""

    __tablename__ = "external_model_drafts"

    UQ_CONNECTION_INTERACTION = sa.UniqueConstraint(
        "connection_id",
        "owner_interaction_key",
        name="uq_external_model_drafts_connection_interaction",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_model_drafts_expires_at",
        "expires_at",
    )
    IX_SESSION_ID = sa.Index(
        "ix_external_model_drafts_session_id",
        "session_id",
    )
    CK_GENERATION = sa.CheckConstraint(
        "expected_generation >= 0",
        name="ck_external_model_drafts_generation",
    )
    CK_TERMINAL_TIMES = sa.CheckConstraint(
        "num_nonnulls(cancelled_at, applied_at) <= 1",
        name="ck_external_model_drafts_terminal_times",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    link_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_account_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    link_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    binding_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_interaction_key: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
    )
    expected_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    options_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
    )
    selected_option_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    selected_model_target_label: Mapped[str] = mapped_column(
        sa.String(80),
        nullable=False,
    )
    selected_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    selected_enabled_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    scope_label: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    applied_at: Mapped[datetime.datetime | None] = mapped_column(
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
        UQ_CONNECTION_INTERACTION,
        IX_EXPIRES_AT,
        IX_SESSION_ID,
        CK_GENERATION,
        CK_TERMINAL_TIMES,
    )


class RDBExternalModelMutation(RDBModel):
    """Immutable external actor audit for one shared model mutation."""

    __tablename__ = "external_model_mutations"

    UQ_PROVIDER_CONNECTION_INTERACTION = sa.UniqueConstraint(
        "provider",
        "connection_id",
        "apply_interaction_key",
        name="uq_external_model_mutations_provider_connection_interaction",
    )
    IX_SESSION_ID = sa.Index(
        "ix_external_model_mutations_session_id",
        "session_id",
    )
    IX_LINK_ID_SNAPSHOT = sa.Index(
        "ix_external_model_mutations_link_id_snapshot",
        "link_id_snapshot",
    )
    CK_GENERATIONS = sa.CheckConstraint(
        "expected_generation >= 0 AND resulting_generation = expected_generation + 1",
        name="ck_external_model_mutations_generations",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    apply_interaction_key: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
    )
    principal_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="SET NULL"),
        nullable=True,
    )
    principal_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_tenant_id_snapshot: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_user_id_snapshot: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_tenant_display_label_snapshot: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    actor_display_name_snapshot: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    link_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_account_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    link_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    binding_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_bindings.id", ondelete="SET NULL"),
        nullable=True,
    )
    binding_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id_snapshot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    old_model_target_label: Mapped[str | None] = mapped_column(
        sa.String(80),
        nullable=True,
    )
    old_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    old_enabled_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    new_model_target_label: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    new_model_display_name: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    new_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    new_enabled_execution_options: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    expected_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    resulting_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    provider_conversation_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_thread_id: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    notice_outcome: Mapped[ExternalModelNoticeOutcome] = mapped_column(
        external_model_notice_outcome_enum,
        nullable=False,
        server_default=ExternalModelNoticeOutcome.UNKNOWN.value,
    )
    notice_attempted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    notice_error_summary: Mapped[str | None] = mapped_column(
        sa.String(255),
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
        UQ_PROVIDER_CONNECTION_INTERACTION,
        IX_SESSION_ID,
        IX_LINK_ID_SNAPSHOT,
        CK_GENERATIONS,
    )
