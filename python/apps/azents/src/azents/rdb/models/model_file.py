"""ModelFile model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.types import JSONValue
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ModelFileStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


model_file_status_enum = ENUM(
    ModelFileStatus,
    name="model_file_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBModelFile(RDBModel):
    """ModelFile metadata table."""

    __tablename__ = "model_files"

    IX_WORKSPACE_ID = sa.Index("ix_model_files_workspace_id", "workspace_id")
    IX_SESSION_STATUS = sa.Index(
        "ix_model_files_session_status",
        "session_id",
        "status",
    )
    IX_EXPIRATION = sa.Index(
        "ix_model_files_expiration",
        "session_id",
        "status",
        "expires_after_run_index",
    )
    IX_UNREACHABLE_GC = sa.Index(
        "ix_model_files_unreachable_gc",
        "session_id",
        "status",
        "unreachable_run_index",
    )
    UQ_STORAGE_KEY = sa.UniqueConstraint(
        "storage_key",
        name="uq_model_files_storage_key",
    )

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
    session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_run_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    expires_after_run_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(
        sa.String(1024), nullable=False, init=False
    )
    normalized_format: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    status: Mapped[ModelFileStatus] = mapped_column(
        model_file_status_enum,
        nullable=False,
        default=ModelFileStatus.AVAILABLE,
        server_default=ModelFileStatus.AVAILABLE.value,
    )
    metadata_: Mapped[dict[str, JSONValue]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default_factory=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    degraded_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    unreachable_run_index: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    unreachable_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )
    blob_deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=True,
        default=None,
    )

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_SESSION_STATUS,
        IX_EXPIRATION,
        IX_UNREACHABLE_GC,
        UQ_STORAGE_KEY,
    )
