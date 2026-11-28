"""Session-owned Vault request and value-free delivery state."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.json_value import JSONValue
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class VaultRequestStatus(enum.StrEnum):
    """Persisted state; an overdue open row is not submittable."""

    OPEN = "open"
    SUBMITTED = "submitted"
    EXPIRED = "expired"


vault_request_status_enum = ENUM(
    VaultRequestStatus,
    name="vault_request_status",
    values_callable=lambda items: [item.value for item in items],
    create_type=False,
)


class RDBAgentVaultRequest(RDBModel):
    """One immutable request specification with its terminal settlement."""

    __tablename__ = "agent_vault_requests"

    IX_SESSION_ID = sa.Index("ix_agent_vault_requests_session_id", "session_id")
    UQ_ANCHOR_EVENT_ID = sa.UniqueConstraint(
        "anchor_event_id", name="uq_agent_vault_requests_anchor_event_id"
    )
    IX_OPEN_DEADLINE = sa.Index(
        "ix_agent_vault_requests_open_deadline",
        "deadline_at",
        "id",
        postgresql_where=sa.text("status = 'open'"),
    )
    IX_UNCLAIMED_CREATE = sa.Index(
        "ix_agent_vault_requests_unclaimed_create",
        "creation_at",
        "id",
        postgresql_where=sa.text(
            "status = 'open' AND destination IS NOT NULL AND post_claimed_at IS NULL"
        ),
    )
    IX_UNCLAIMED_EDIT = sa.Index(
        "ix_agent_vault_requests_unclaimed_edit",
        "terminal_at",
        "id",
        postgresql_where=sa.text(
            "terminal_at IS NOT NULL AND receipt IS NOT NULL "
            "AND edit_claimed_at IS NULL"
        ),
    )
    CK_TERMINAL = sa.CheckConstraint(
        "(status = 'open') = (terminal_at IS NULL)",
        name="ck_agent_vault_requests_terminal",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # This placement identity is not an FK: terminal history may be collected.
    anchor_event_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(sa.Text, nullable=False)
    fields: Mapped[list[dict[str, JSONValue]]] = mapped_column(JSONB, nullable=False)
    creation_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    deadline_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    destination: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    button_label: Mapped[str | None] = mapped_column(sa.String(75), nullable=True)
    status: Mapped[VaultRequestStatus] = mapped_column(
        vault_request_status_enum,
        init=False,
        default=VaultRequestStatus.OPEN,
        server_default=VaultRequestStatus.OPEN.value,
        nullable=False,
    )
    terminal_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, init=False, default=None
    )
    post_claimed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, init=False, default=None
    )
    receipt: Mapped[dict[str, JSONValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True, init=False, default=None
    )
    edit_claimed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, init=False, default=None
    )

    __table_args__ = (
        IX_SESSION_ID,
        UQ_ANCHOR_EVENT_ID,
        IX_OPEN_DEADLINE,
        IX_UNCLAIMED_CREATE,
        IX_UNCLAIMED_EDIT,
        CK_TERMINAL,
    )
