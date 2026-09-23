"""Error categories for completed OAuth persistence operations."""

from enum import StrEnum


class OAuthPersistenceError(StrEnum):
    """Failures that require translation at the service boundary."""

    INVALID_TARGET = "invalid_target"
    TRANSITION_FAILED = "transition_failed"
