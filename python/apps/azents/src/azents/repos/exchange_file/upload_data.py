"""Detached, immutable manifests for feature-owned Exchange upload operations."""

import datetime
from dataclasses import dataclass

from azents.core.exchange_upload import ExchangeUploadState


@dataclass(frozen=True)
class ExchangeUploadOperation:
    """Exact browser upload manifest and reserved cleanup identities.

    Reserved IDs derive private ingress/source/preview keys in the trusted service.
    Neither these identities nor a persisted operation confer current permission.
    """

    upload_id: str
    publication_id: str
    preview_file_id: str
    workspace_id: str
    agent_id: str
    uploader_user_id: str
    filename: str
    media_type: str
    expected_size: int
    expected_sha256: str
    created_at: datetime.datetime
    expires_at: datetime.datetime
    cleanup_after: datetime.datetime
    state: ExchangeUploadState
    finalize_claim_id: str | None
    finalize_lease_until: datetime.datetime | None
    finalized_at: datetime.datetime | None
    cleanup_claim_id: str | None
    cleanup_lease_until: datetime.datetime | None
    cleanup_completed_at: datetime.datetime | None

    def __post_init__(self) -> None:
        """Validate immutable manifests, bounded claims, and aware deadlines."""
        for value in (
            self.upload_id,
            self.publication_id,
            self.preview_file_id,
            self.workspace_id,
            self.agent_id,
            self.uploader_user_id,
        ):
            if not value or len(value) > 32:
                raise ValueError("Upload identity must be nonempty and bounded")
        if not self.filename or len(self.filename) > 255:
            raise ValueError("Upload filename must be nonempty and bounded")
        if not self.media_type or len(self.media_type) > 255:
            raise ValueError("Upload media type must be nonempty and bounded")
        if self.expected_size < 0:
            raise ValueError("Upload size must not be negative")
        if len(self.expected_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.expected_sha256
        ):
            raise ValueError("Upload SHA-256 must be lowercase hexadecimal")
        for value in (
            self.created_at,
            self.expires_at,
            self.cleanup_after,
            self.finalize_lease_until,
            self.finalized_at,
            self.cleanup_lease_until,
            self.cleanup_completed_at,
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("Upload timestamps must be timezone-aware")
        if self.expires_at <= self.created_at or self.cleanup_after < self.expires_at:
            raise ValueError("Upload expiry and cleanup deadlines are invalid")
        for claim_id, lease_until in (
            (self.finalize_claim_id, self.finalize_lease_until),
            (self.cleanup_claim_id, self.cleanup_lease_until),
        ):
            if (claim_id is None) != (lease_until is None):
                raise ValueError("Upload claims require complete lease evidence")
            if claim_id is not None and not 1 <= len(claim_id) <= 128:
                raise ValueError("Upload claim identity must be bounded")
        if (self.state is ExchangeUploadState.FINALIZED) != (
            self.finalized_at is not None
        ):
            raise ValueError("Upload finalization state and evidence must agree")
