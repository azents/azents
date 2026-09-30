"""Typed internal Exchange browser-upload lifecycle values."""

from enum import StrEnum


class ExchangeUploadState(StrEnum):
    """Publication state independent from durable physical cleanup."""

    PENDING = "pending"
    FINALIZED = "finalized"


class ExchangeUploadError(StrEnum):
    """Bounded upload operation failure without object-store diagnostics."""

    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    EXPIRED = "expired"
    BUSY = "busy"
    FENCED = "fenced"
    MANIFEST_MISMATCH = "manifest_mismatch"
    INVALID_REQUEST = "invalid_request"
