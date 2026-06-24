"""events table model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import EventKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


event_kind_enum = ENUM(
    EventKind,
    name="event_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBEvent(RDBModel):
    """events tablet event transcript event row."""

    __tablename__ = "events"

    IX_SESSION_ID = sa.Index("ix_events_session_id", "session_id")
    IX_SESSION_CREATED = sa.Index("ix_events_session_created", "session_id", "id")
    IX_SESSION_MODEL_ORDER = sa.Index(
        "ix_events_session_model_order",
        "session_id",
        "model_order",
        unique=True,
    )
    UQ_SESSION_EXTERNAL = sa.Index(
        "uq_events_session_external",
        "session_id",
        "external_id",
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

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
    kind: Mapped[EventKind] = mapped_column(
        event_kind_enum,
        nullable=False,
    )
    payload: Mapped[dict[str, JSONValue]] = mapped_column(JSONB, nullable=False)
    model_order: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    external_id: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    adapter: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    model: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    native_format: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    schema_version: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        default="1",
        server_default="1",
    )
    reverted: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        IX_SESSION_ID,
        IX_SESSION_CREATED,
        IX_SESSION_MODEL_ORDER,
        UQ_SESSION_EXTERNAL,
    )
