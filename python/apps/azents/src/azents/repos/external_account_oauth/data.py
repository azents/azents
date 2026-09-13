"""Provider identity OAuth attempt repository data."""

import datetime
from dataclasses import dataclass

from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelProvider,
)


@dataclass(frozen=True)
class ExternalAccountOAuthAttempt:
    """Detached OAuth attempt projection."""

    id: str
    state_hash: str
    user_id: str
    auth_session_id: str
    provider: ExternalChannelProvider
    setting_generation: str
    redirect_uri: str
    encrypted_pkce_verifier: str | None
    status: ExternalAccountOAuthAttemptStatus
    expires_at: datetime.datetime
    claimed_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    failed_at: datetime.datetime | None
    failure_code: str | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class ExternalAccountOAuthAttemptCreate:
    """Values required to create one open OAuth attempt."""

    id: str
    state_hash: str
    user_id: str
    auth_session_id: str
    provider: ExternalChannelProvider
    setting_generation: str
    redirect_uri: str
    encrypted_pkce_verifier: str | None
    expires_at: datetime.datetime


@dataclass(frozen=True)
class ExternalAccountOAuthAttemptCleanupSummary:
    """Bounded OAuth attempt cleanup result."""

    deleted_count: int
