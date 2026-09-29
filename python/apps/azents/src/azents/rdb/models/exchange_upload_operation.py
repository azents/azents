"""Durable Exchange upload manifests and deletion-independent cleanup owners."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.exchange_upload import ExchangeUploadState
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _state_values(enum_type: type[ExchangeUploadState]) -> list[str]:
    """Return persisted upload state values."""
    return [state.value for state in enum_type]


exchange_upload_state_enum = ENUM(
    ExchangeUploadState,
    name="exchange_upload_state",
    values_callable=_state_values,
    create_type=False,
)


class RDBExchangeUploadOperation(RDBModel):
    """Internal operation IDs survive deletion of their former product owners."""

    __tablename__ = "exchange_upload_operations"

    UQ_PUBLICATION_ID = sa.UniqueConstraint(
        "publication_id", name="uq_exchange_upload_operations_publication_id"
    )
    UQ_PREVIEW_FILE_ID = sa.UniqueConstraint(
        "preview_file_id", name="uq_exchange_upload_operations_preview_file_id"
    )
    IX_DUE_CLEANUP = sa.Index(
        "ix_exchange_upload_operations_due_cleanup",
        "cleanup_after",
        "cleanup_lease_until",
        "id",
    )
    CK_EXPECTED_SIZE = sa.CheckConstraint(
        "expected_size >= 0",
        name="ck_exchange_upload_operations_expected_size",
    )
    CK_DEADLINES = sa.CheckConstraint(
        "expires_at > created_at AND cleanup_after >= expires_at",
        name="ck_exchange_upload_operations_deadlines",
    )
    CK_FINALIZE_CLAIM = sa.CheckConstraint(
        "(finalize_claim_id IS NULL) = (finalize_lease_until IS NULL)",
        name="ck_exchange_upload_operations_finalize_claim",
    )
    CK_CLEANUP_CLAIM = sa.CheckConstraint(
        "(cleanup_claim_id IS NULL) = (cleanup_lease_until IS NULL)",
        name="ck_exchange_upload_operations_cleanup_claim",
    )
    CK_FINALIZED = sa.CheckConstraint(
        "(state = 'finalized') = (finalized_at IS NOT NULL)",
        name="ck_exchange_upload_operations_finalized",
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    publication_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    preview_file_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # Frozen identity evidence, deliberately not FKs: owner deletion must not
    # cascade away already-issued capability and cleanup responsibilities.
    workspace_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    agent_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    uploader_user_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    expected_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    cleanup_after: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, nullable=False
    )
    state: Mapped[ExchangeUploadState] = mapped_column(
        exchange_upload_state_enum, nullable=False
    )
    finalize_claim_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    finalize_lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    finalized_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    cleanup_claim_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    cleanup_lease_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )
    cleanup_completed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True
    )

    __table_args__ = (
        UQ_PUBLICATION_ID,
        UQ_PREVIEW_FILE_ID,
        IX_DUE_CLEANUP,
        CK_EXPECTED_SIZE,
        CK_DEADLINES,
        CK_FINALIZE_CLAIM,
        CK_CLEANUP_CLAIM,
        CK_FINALIZED,
    )
