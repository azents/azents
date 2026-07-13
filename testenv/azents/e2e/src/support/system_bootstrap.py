"""Sanitized system bootstrap evidence shared by E2E fixtures and tests."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemBootstrapEvidence:
    """Bootstrap outcomes plus the authenticated initial administrator session."""

    access_token: str
    refresh_token: str
    email: str
    initial_available: bool
    invalid_attempt_status: int
    concurrent_attempt_statuses: tuple[int, int]
    final_available: bool
