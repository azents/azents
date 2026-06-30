"""chat input buffer ORM model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import InputBufferKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


input_buffer_kind_enum = ENUM(
    InputBufferKind,
    name="input_buffer_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBInputBuffer(RDBModel):
    """Chat input buffer injected before the next model turn."""

    __tablename__ = "input_buffers"

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
    kind: Mapped[InputBufferKind] = mapped_column(
        input_buffer_kind_enum,
        nullable=False,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
    )
    metadata_: Mapped[dict[str, str]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
    )
    action: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    attachments: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    file_parts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )

    IX_SESSION_ID = sa.Index("ix_input_buffers_session_id", "session_id")
    IX_SESSION_ID_ID = sa.Index("ix_input_buffers_session_id_id", "session_id", "id")
    IX_KIND = sa.Index("ix_input_buffers_kind", "kind")
    UQ_SESSION_KIND_IDEMPOTENCY = sa.Index(
        "uq_input_buffers_session_kind_idempotency",
        "session_id",
        "kind",
        "idempotency_key",
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    __table_args__ = (
        IX_SESSION_ID,
        IX_SESSION_ID_ID,
        IX_KIND,
        UQ_SESSION_KIND_IDEMPOTENCY,
    )
