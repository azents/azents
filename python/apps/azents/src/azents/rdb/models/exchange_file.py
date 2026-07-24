"""ExchangeFile model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _exchange_file_origin_values(
    enum_cls: type[ExchangeFileOrigin],
) -> list[str]:
    """Return ExchangeFileOrigin enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _exchange_file_status_values(
    enum_cls: type[ExchangeFileStatus],
) -> list[str]:
    """Return ExchangeFileStatus enum values stored in the DB."""
    return [v.value for v in enum_cls]


def _exchange_file_provenance_kind_values(
    enum_cls: type[ExchangeFileProvenanceKind],
) -> list[str]:
    """Return provenance enum values stored in the DB."""
    return [v.value for v in enum_cls]


exchange_file_origin_enum = ENUM(
    ExchangeFileOrigin,
    name="exchange_file_origin",
    create_type=False,
    values_callable=_exchange_file_origin_values,
)

exchange_file_status_enum = ENUM(
    ExchangeFileStatus,
    name="exchange_file_status",
    create_type=False,
    values_callable=_exchange_file_status_values,
)
exchange_file_provenance_kind_enum = ENUM(
    ExchangeFileProvenanceKind,
    name="exchange_file_provenance_kind",
    create_type=False,
    values_callable=_exchange_file_provenance_kind_values,
)


class RDBExchangeFile(RDBModel):
    """Exchange file metadata table."""

    __tablename__ = "exchange_files"

    IX_WORKSPACE_ID = sa.Index("ix_exchange_files_workspace_id", "workspace_id")
    IX_ORIGIN_TYPE = sa.Index("ix_exchange_files_origin_type", "origin_type")
    IX_STATUS_EXPIRES_AT = sa.Index(
        "ix_exchange_files_status_expires_at",
        "status",
        "expires_at",
    )
    IX_PREVIEW_THUMBNAIL_FILE_ID = sa.Index(
        "ix_exchange_files_preview_thumbnail_file_id",
        "preview_thumbnail_file_id",
    )
    IX_RETENTION_ROOT_STATUS = sa.Index(
        "ix_exchange_files_retention_root_status",
        "retention_root_session_id",
        "status",
        "id",
        postgresql_where=sa.text("retention_root_session_id IS NOT NULL"),
    )
    UQ_OBJECT_KEY = sa.UniqueConstraint(
        "object_key",
        name="uq_exchange_files_object_key",
    )
    CK_PROVENANCE = sa.CheckConstraint(
        """
        (provenance_kind = 'human' AND source_user_id IS NOT NULL)
        OR (provenance_kind = 'agent' AND source_agent_id IS NOT NULL)
        OR (
            provenance_kind = 'tool'
            AND source_agent_id IS NOT NULL
            AND source_run_id IS NOT NULL
            AND source_tool_name IS NOT NULL
        )
        OR (
            provenance_kind = 'provider'
            AND source_agent_id IS NOT NULL
            AND source_run_id IS NOT NULL
            AND source_provider IS NOT NULL
        )
        OR (provenance_kind IN ('system', 'migration'))
        OR (
            provenance_kind = 'preview'
            AND source_exchange_file_id IS NOT NULL
        )
        """,
        name="ck_exchange_files_provenance",
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
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_type: Mapped[ExchangeFileOrigin] = mapped_column(
        exchange_file_origin_enum,
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(sa.String(1024), nullable=False, init=False)
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provenance_kind: Mapped[ExchangeFileProvenanceKind] = mapped_column(
        exchange_file_provenance_kind_enum,
        nullable=False,
    )
    source_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_run_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_tool_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    source_provider: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    source_exchange_file_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("exchange_files.id", ondelete="RESTRICT"),
        nullable=True,
    )
    retention_root_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    retention_bound_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
        server_default=sa.text("now() + interval '30 days'"),
    )
    status: Mapped[ExchangeFileStatus] = mapped_column(
        exchange_file_status_enum,
        nullable=False,
        default=ExchangeFileStatus.AVAILABLE,
        server_default=ExchangeFileStatus.AVAILABLE.value,
    )
    preview_thumbnail_file_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("exchange_files.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    preview_title: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    preview_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    preview_thumbnail_media_type: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        default=None,
    )
    preview_thumbnail_width: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    preview_thumbnail_height: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        default=None,
    )
    preview_generated_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
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
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        nullable=False,
    )
    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_ORIGIN_TYPE,
        IX_STATUS_EXPIRES_AT,
        IX_PREVIEW_THUMBNAIL_FILE_ID,
        IX_RETENTION_ROOT_STATUS,
        UQ_OBJECT_KEY,
        CK_PROVENANCE,
    )
