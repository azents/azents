"""AgentSession create-request idempotency ORM model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentSessionCreateRequest(RDBModel):
    """Durable authority for one REST AgentSession create request."""

    __tablename__ = "agent_session_create_requests"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_request_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    # Deliberately not a FK: deleting the accepted AgentSession must not erase
    # the durable request authority and allow the same key to create a second
    # Session after an ambiguous client response.
    agent_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    # Deliberately not a FK: consumed InputBuffer rows are deleted, while the
    # accepted ID and snapshot must survive for response-loss retries.
    input_buffer_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    # The check constraint distinguishes a pending SQL NULL from a completed
    # JSON snapshot.  PostgreSQL JSONB otherwise serializes Python None as the
    # non-SQL JSON value `null`, which looks populated to `IS NULL` checks.
    input_buffer_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
    )

    IX_AGENT_SESSION_ID = sa.Index(
        "ix_agent_session_create_requests_agent_session_id",
        "agent_session_id",
    )
    UQ_USER_AGENT_CLIENT_REQUEST = sa.UniqueConstraint(
        "user_id",
        "agent_id",
        "client_request_id",
        name="uq_agent_session_create_requests_user_agent_client_request",
    )
    CK_COMPLETION = sa.CheckConstraint(
        "(agent_session_id IS NULL AND input_buffer_id IS NULL "
        "AND input_buffer_snapshot IS NULL AND completed_at IS NULL) OR "
        "(agent_session_id IS NOT NULL AND input_buffer_id IS NOT NULL "
        "AND input_buffer_snapshot IS NOT NULL AND completed_at IS NOT NULL)",
        name="ck_agent_session_create_requests_completion",
    )

    __table_args__ = (
        IX_AGENT_SESSION_ID,
        UQ_USER_AGENT_CLIENT_REQUEST,
        CK_COMPLETION,
    )
