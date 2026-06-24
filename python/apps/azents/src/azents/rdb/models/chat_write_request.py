"""chat REST write request ORM model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


class ChatWriteRequestType(enum.StrEnum):
    """REST write request type."""

    EDIT_MESSAGE = "edit_message"
    COMMAND = "command"


chat_write_request_type_enum = ENUM(
    ChatWriteRequestType,
    name="chat_write_request_type",
    create_type=False,
    values_callable=_enum_values,
)


class RDBChatWriteRequest(RDBModel):
    """REST write idempotency record."""

    __tablename__ = "chat_write_requests"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_request_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    write_type: Mapped[ChatWriteRequestType] = mapped_column(
        chat_write_request_type_enum,
        nullable=False,
    )
    accepted_type: Mapped[ChatWriteRequestType] = mapped_column(
        chat_write_request_type_enum,
        nullable=False,
    )
    accepted_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    history_reload_required: Mapped[bool] = mapped_column(nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    IX_SESSION_ID = sa.Index("ix_chat_write_requests_session_id", "session_id")
    UQ_RUNTIME_USER_CLIENT_REQUEST = sa.UniqueConstraint(
        "agent_runtime_id",
        "user_id",
        "client_request_id",
        name="uq_chat_write_requests_runtime_user_client_request",
    )

    __table_args__ = (IX_SESSION_ID, UQ_RUNTIME_USER_CLIENT_REQUEST)
