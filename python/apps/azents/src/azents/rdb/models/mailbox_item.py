"""chat input buffer ORM model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import MailboxItemKind, MailboxSchedulingMode
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.base import RDBModel
from azents.rdb.models.inference_profile_types import model_reasoning_effort_enum
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


mailbox_item_kind_enum = ENUM(
    MailboxItemKind,
    name="mailbox_item_kind",
    create_type=False,
    values_callable=_enum_values,
)

mailbox_item_scheduling_mode_enum = ENUM(
    MailboxSchedulingMode,
    name="mailbox_item_scheduling_mode",
    create_type=False,
    values_callable=_enum_values,
)


class RDBMailboxItem(RDBModel):
    """Chat input buffer injected before the next model turn."""

    __tablename__ = "mailbox_items"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[MailboxItemKind] = mapped_column(
        mailbox_item_kind_enum,
        nullable=False,
    )
    scheduling_mode: Mapped[MailboxSchedulingMode] = mapped_column(
        mailbox_item_scheduling_mode_enum,
        nullable=False,
    )
    requested_model_target_label: Mapped[str | None] = mapped_column(
        sa.String(80),
        nullable=True,
    )
    requested_reasoning_effort: Mapped[ModelReasoningEffort | None] = mapped_column(
        model_reasoning_effort_enum,
        nullable=True,
    )
    sender_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
    )
    order_group: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        init=False,
    )
    order_sequence: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        init=False,
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    CK_REQUESTED_PROFILE = sa.CheckConstraint(
        "requested_reasoning_effort IS NULL "
        "OR requested_model_target_label IS NOT NULL",
        name="ck_mailbox_items_requested_profile",
    )
    CK_SENDER_USER_KIND = sa.CheckConstraint(
        "sender_user_id IS NULL OR kind IN ('user_message', 'action_message')",
        name="ck_mailbox_items_sender_user_kind",
    )
    CK_ORDER_SEQUENCE = sa.CheckConstraint(
        "order_sequence >= 0",
        name="ck_mailbox_items_order_sequence",
    )
    IX_SESSION_ID = sa.Index("ix_mailbox_items_session_id", "session_id")
    IX_SESSION_ORDER = sa.Index(
        "ix_mailbox_items_session_order",
        "session_id",
        "order_group",
        "order_sequence",
        "id",
    )
    IX_SESSION_ID_SCHEDULING_MODE = sa.Index(
        "ix_mailbox_items_session_id_scheduling_mode",
        "session_id",
        "scheduling_mode",
    )
    IX_KIND = sa.Index("ix_mailbox_items_kind", "kind")
    UQ_SESSION_KIND_IDEMPOTENCY = sa.Index(
        "uq_mailbox_items_session_kind_idempotency",
        "session_id",
        "kind",
        "idempotency_key",
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    __table_args__ = (
        CK_REQUESTED_PROFILE,
        CK_SENDER_USER_KIND,
        CK_ORDER_SEQUENCE,
        IX_SESSION_ID,
        IX_SESSION_ORDER,
        IX_SESSION_ID_SCHEDULING_MODE,
        IX_KIND,
        UQ_SESSION_KIND_IDEMPOTENCY,
    )
