"""Conversation-owned identity and input state over common execution Sessions."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    AgentSessionTitleSource,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

agent_session_kind_enum = ENUM(
    AgentSessionKind,
    name="agent_session_kind",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
agent_session_primary_kind_enum = ENUM(
    AgentSessionPrimaryKind,
    name="agent_session_primary_kind",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
agent_session_product_mode_enum = ENUM(
    AgentSessionProductMode,
    name="agent_session_product_mode",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
agent_session_status_enum = ENUM(
    AgentSessionStatus,
    name="agent_session_status",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)
agent_session_title_source_enum = ENUM(
    AgentSessionTitleSource,
    name="agent_session_title_source",
    create_type=False,
    values_callable=lambda cls: [value.value for value in cls],
)


class RDBConversation(RDBModel):
    """Public conversation profile; lifecycle projections are FK-constrained."""

    __tablename__ = "conversations"

    FK_SESSION_LIFECYCLE = sa.ForeignKeyConstraint(
        ["session_id", "agent_id", "session_status"],
        ["agent_sessions.id", "agent_sessions.agent_id", "agent_sessions.status"],
        name="fk_conversation_session_lifecycle",
        onupdate="CASCADE",
        ondelete="CASCADE",
    )
    IX_PENDING_COMMAND = sa.Index(
        "ix_conversations_pending_command",
        "pending_command_created_at",
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    IX_AGENT_ASSOCIATED_USER_STATUS = sa.Index(
        "ix_conversations_agent_associated_user_status",
        "agent_id",
        "associated_user_id",
        "session_status",
    )
    IX_ASSOCIATED_USER_ID = sa.Index(
        "ix_conversations_associated_user_id",
        "associated_user_id",
    )
    UQ_AGENT_ACTIVE_TEAM_PRIMARY = sa.Index(
        "uq_conversations_agent_active_team_primary",
        "agent_id",
        unique=True,
        postgresql_where=sa.text(
            "session_status = 'active' "
            "AND primary_kind = 'team_primary' "
            "AND product_mode = 'team'"
        ),
    )
    CK_PRODUCT_MODE_OWNERSHIP = sa.CheckConstraint(
        "("
        "session_kind = 'root' "
        "AND product_mode IS NOT NULL "
        "AND ("
        "("
        "product_mode = 'team' "
        "AND associated_user_id IS NULL"
        ") OR ("
        "product_mode = 'user' "
        "AND associated_user_id IS NOT NULL "
        "AND primary_kind IS NULL"
        ")"
        ")"
        ") OR ("
        "session_kind = 'subagent' "
        "AND product_mode IS NULL "
        "AND associated_user_id IS NULL "
        "AND primary_kind IS NULL"
        ")",
        name="ck_conversations_product_mode_ownership",
    )
    IX_AGENT_ACTIVE_LAST_USER_INPUT = sa.Index(
        "ix_conversations_agent_active_last_user_input",
        "agent_id",
        "primary_kind",
        "last_user_input_at",
        postgresql_where=sa.text("session_status = 'active'"),
    )
    UQ_HANDLE = sa.UniqueConstraint("handle", name="uq_conversations_handle")
    IX_ACTIVE_AUTO_ARCHIVE = sa.Index(
        "ix_conversations_active_auto_archive",
        "session_id",
        postgresql_where=sa.text(
            "session_status = 'active' AND session_kind = 'root' AND pinned = false"
        ),
    )
    IX_SESSION_KIND = sa.Index("ix_conversations_session_kind", "session_kind")

    session_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    agent_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    session_status: Mapped[AgentSessionStatus] = mapped_column(
        agent_session_status_enum, nullable=False
    )
    handle: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    session_kind: Mapped[AgentSessionKind] = mapped_column(
        agent_session_kind_enum,
        nullable=False,
        default=AgentSessionKind.ROOT,
    )
    primary_kind: Mapped[AgentSessionPrimaryKind | None] = mapped_column(
        agent_session_primary_kind_enum,
        nullable=True,
        default=None,
    )
    product_mode: Mapped[AgentSessionProductMode | None] = mapped_column(
        agent_session_product_mode_enum,
        nullable=True,
        default=None,
    )
    associated_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    title: Mapped[str | None] = mapped_column(
        sa.String(200),
        nullable=True,
        default=None,
    )
    title_source: Mapped[AgentSessionTitleSource | None] = mapped_column(
        agent_session_title_source_enum,
        nullable=True,
        default=None,
    )
    title_generated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    title_generation_event_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    primary_model_reservation: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        init=False,
        nullable=True,
        default=None,
    )
    primary_model_reservation_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        init=False,
        nullable=False,
        server_default=sa.text("0"),
    )
    title_model_operation_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        init=False,
        nullable=True,
        default=None,
    )
    last_user_input_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    pinned: Mapped[bool] = mapped_column(
        sa.Boolean,
        init=False,
        default=False,
        server_default=sa.false(),
        nullable=False,
    )
    pending_idle_continuation_run_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_name: Mapped[str | None] = mapped_column(
        sa.String(120),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_payload: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_requester_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        init=False,
        nullable=True,
        default=None,
    )
    pending_command_created_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )

    __table_args__ = (
        FK_SESSION_LIFECYCLE,
        CK_PRODUCT_MODE_OWNERSHIP,
        IX_ACTIVE_AUTO_ARCHIVE,
        IX_AGENT_ACTIVE_LAST_USER_INPUT,
        IX_AGENT_ASSOCIATED_USER_STATUS,
        IX_ASSOCIATED_USER_ID,
        IX_PENDING_COMMAND,
        IX_SESSION_KIND,
        UQ_AGENT_ACTIVE_TEAM_PRIMARY,
        UQ_HANDLE,
    )
