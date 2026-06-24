"""ChatGPT OAuth session model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthSessionStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _connection_method_values(
    enum_cls: type[ChatGPTOAuthConnectionMethod],
) -> list[str]:
    """Return ChatGPTOAuthConnectionMethod enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _session_status_values(enum_cls: type[ChatGPTOAuthSessionStatus]) -> list[str]:
    """Return ChatGPTOAuthSessionStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


chatgpt_oauth_connection_method_enum = ENUM(
    ChatGPTOAuthConnectionMethod,
    name="chatgpt_oauth_connection_method",
    create_type=False,
    values_callable=_connection_method_values,
)
chatgpt_oauth_session_status_enum = ENUM(
    ChatGPTOAuthSessionStatus,
    name="chatgpt_oauth_session_status",
    create_type=False,
    values_callable=_session_status_values,
)


class RDBChatGPTOAuthSession(RDBModel):
    """ChatGPT OAuth callback/device session table."""

    __tablename__ = "chatgpt_oauth_sessions"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    method: Mapped[ChatGPTOAuthConnectionMethod] = mapped_column(
        chatgpt_oauth_connection_method_enum,
        nullable=False,
    )
    state: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    encrypted_code_verifier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    encrypted_device_auth_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    user_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    verification_uri: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    interval_seconds: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, default=None
    )
    status: Mapped[ChatGPTOAuthSessionStatus] = mapped_column(
        chatgpt_oauth_session_status_enum,
        nullable=False,
        default=ChatGPTOAuthSessionStatus.PENDING,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    IX_WORKSPACE_ID = sa.Index("ix_chatgpt_oauth_sessions_workspace_id", "workspace_id")
    IX_USER_ID = sa.Index("ix_chatgpt_oauth_sessions_user_id", "user_id")
    IX_STATE = sa.Index("ix_chatgpt_oauth_sessions_state", "state", unique=True)

    __table_args__ = (IX_WORKSPACE_ID, IX_USER_ID, IX_STATE)
