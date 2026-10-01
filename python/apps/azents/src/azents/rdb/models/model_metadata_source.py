"""Durable model metadata source authority and snapshots."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBModelMetadataSource(RDBModel):
    """Logical current model metadata source authority."""

    __tablename__ = "model_metadata_sources"

    source_key: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    current_snapshot_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    latest_attempt_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class RDBModelMetadataSourceSnapshot(RDBModel):
    """One immutable content-addressed model metadata source snapshot."""

    __tablename__ = "model_metadata_source_snapshots"

    UQ_SOURCE_CONTENT = sa.UniqueConstraint(
        "source_key",
        "source_schema_version",
        "source_hash",
        name="uq_model_metadata_source_snapshots_content",
    )
    IX_SOURCE_CREATED = sa.Index(
        "ix_model_metadata_source_snapshots_source_created",
        "source_key",
        "created_at",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(
        sa.String(120),
        sa.ForeignKey("model_metadata_sources.source_key", ondelete="CASCADE"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    source_schema_version: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    producer_name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    producer_version: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    provider_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    model_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )

    __table_args__ = (UQ_SOURCE_CONTENT, IX_SOURCE_CREATED)
