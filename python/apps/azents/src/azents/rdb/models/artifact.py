"""Artifact model."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.types import JSONValue
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ArtifactStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the DB."""
    return [value.value for value in enum_cls]


artifact_status_enum = ENUM(
    ArtifactStatus,
    name="artifact_status",
    create_type=False,
    values_callable=_enum_values,
)


class RDBArtifact(RDBModel):
    """Artifact metadata table."""

    __tablename__ = "artifacts"

    IX_WORKSPACE_ID = sa.Index("ix_artifacts_workspace_id", "workspace_id")
    IX_SESSION_STATUS = sa.Index("ix_artifacts_session_status", "session_id", "status")
    IX_STATUS_EXPIRES_AT = sa.Index(
        "ix_artifacts_status_expires_at",
        "status",
        "expires_at",
    )
    UQ_STORAGE_KEY = sa.UniqueConstraint(
        "storage_key",
        name="uq_artifacts_storage_key",
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
    created_run_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    created_run_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(
        sa.String(1024), nullable=False, init=False
    )
    status: Mapped[ArtifactStatus] = mapped_column(
        artifact_status_enum,
        nullable=False,
        default=ArtifactStatus.AVAILABLE,
        server_default=ArtifactStatus.AVAILABLE.value,
    )
    sha256: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, default=None
    )
    source_tool_name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    source_call_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    source_part_index: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    description: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
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
    expired_at: Mapped[datetime.datetime | None] = mapped_column(
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
        IX_STATUS_EXPIRES_AT,
        UQ_STORAGE_KEY,
    )
