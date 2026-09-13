"""External account linking domain contracts."""

import dataclasses
import datetime
import enum

from azents.core.enums import ExternalChannelProvider

EXTERNAL_ACCOUNT_LINK_ORIGIN_TTL = datetime.timedelta(minutes=10)
EXTERNAL_ACCOUNT_LINK_CLEANUP_RETENTION = datetime.timedelta(hours=24)
EXTERNAL_ACCOUNT_LINK_MAX_CANDIDATES = 5
EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES = 5


class ExternalAccountLinkState(enum.StrEnum):
    """User-visible state of an external account link."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


class ExternalAccountLinkRevocationReason(enum.StrEnum):
    """Terminal reason retained for link history and migration audit."""

    OWNER_DISCONNECTED = "owner_disconnected"
    LEGACY_REDUNDANT = "legacy_redundant"
    LEGACY_CONFLICT = "legacy_conflict"


class ExternalAccountLinkOriginState(enum.StrEnum):
    """Current state of an external account link origin."""

    OPEN = "open"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class ExternalAccountLinkCandidateStatus(enum.StrEnum):
    """Current state of an immutable browser candidate."""

    PENDING_PROVIDER_PROOF = "pending_provider_proof"
    PROVIDER_VERIFIED = "provider_verified"
    CONNECTED = "connected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ExternalAccountLinkReturnKind(enum.StrEnum):
    """Provider-native return navigation kind."""

    SLACK_CONVERSATION = "slack_conversation"
    DISCORD_CONVERSATION = "discord_conversation"


@dataclasses.dataclass(frozen=True)
class VerifiedExternalAccountActor:
    """Provider actor context constructed only after verified ingress."""

    connection_id: str
    connection_configuration_generation: int
    principal_id: str
    provider: ExternalChannelProvider
    provider_tenant_id: str
    provider_tenant_display_label: str | None
    provider_user_id: str
    provider_display_label: str
    provider_interaction_id: str
    provider_channel_id: str
    provider_thread_id: str | None


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkView:
    """Detached personal projection of one global link."""

    id: str
    workspace_id: str | None
    workspace_name: str | None
    workspace_handle: str | None
    user_id: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_user_id: str
    provider_tenant_display_label: str | None
    provider_display_label: str
    linked_at: datetime.datetime
    state: ExternalAccountLinkState
    revocation_reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ExternalAccountNativeLinkState:
    """Actor-private link state for a verified provider interaction."""

    link: ExternalAccountLinkView | None
    management_path: str


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkReturnContext:
    """Sanitized provider return navigation."""

    kind: ExternalAccountLinkReturnKind
    provider_tenant_display_label: str
    provider_url: str | None


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkOriginView:
    """Browser-safe confirmation context for one origin."""

    id: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str
    provider: ExternalChannelProvider
    identity_scope: str
    provider_tenant_id: str
    provider_tenant_display_label: str
    provider_display_label: str
    expires_at: datetime.datetime
    state: ExternalAccountLinkOriginState
    candidate_count: int
    invalid_code_count: int
    return_context: ExternalAccountLinkReturnContext


@dataclasses.dataclass(frozen=True)
class ExternalAccountOriginCreated:
    """Native result for a newly created or replayed origin."""

    origin_id: str
    expires_at: datetime.datetime
    web_path: str
    management_path: str


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkCandidateView:
    """Browser-safe status of one immutable candidate."""

    id: str
    origin_id: str
    expires_at: datetime.datetime
    status: ExternalAccountLinkCandidateStatus
    link_id: str | None


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkCandidateCreated:
    """One-time browser result containing the plaintext rendezvous code."""

    id: str
    origin_id: str
    code: str = dataclasses.field(repr=False)
    expires_at: datetime.datetime
    status: ExternalAccountLinkCandidateStatus


@dataclasses.dataclass(frozen=True)
class ExternalAccountProviderProofResult:
    """Provider proof result after matching a candidate code."""

    candidate_id: str
    status: ExternalAccountLinkCandidateStatus
    remaining_attempts: int


@dataclasses.dataclass(frozen=True)
class ExternalAccountLinkCleanupSummary:
    """Bounded proof cleanup result."""

    deleted_origin_count: int
    deleted_candidate_count: int


class ExternalAccountLinkError(Exception):
    """Base class for expected account-link failures."""


class ExternalAccountOAuthError(ExternalAccountLinkError):
    """Base class for sanitized authenticated OAuth failures."""

    code = "oauth_failed"


class ExternalAccountOAuthProviderUnavailable(ExternalAccountOAuthError):
    """Provider configuration is not ready for a new OAuth attempt."""

    code = "provider_unavailable"


class ExternalAccountOAuthInvalidAttempt(ExternalAccountOAuthError):
    """OAuth state or callback does not match a live authenticated attempt."""

    code = "invalid_attempt"


class ExternalAccountOAuthExpired(ExternalAccountOAuthError):
    """OAuth attempt existed but its bounded lifetime elapsed."""

    code = "expired"


class ExternalAccountOAuthAlreadyConsumed(ExternalAccountOAuthError):
    """OAuth attempt was already claimed or terminalized."""

    code = "already_consumed"


class ExternalAccountOAuthAuthSessionMismatch(ExternalAccountOAuthError):
    """OAuth attempt belongs to a different or no longer live auth Session."""

    code = "auth_session_mismatch"


class ExternalAccountOAuthProviderMismatch(ExternalAccountOAuthError):
    """OAuth state belongs to a different provider."""

    code = "provider_mismatch"


class ExternalAccountOAuthInvalidCallback(ExternalAccountOAuthError):
    """OAuth callback does not match the exact registered redirect URI."""

    code = "invalid_callback"


class ExternalAccountOAuthConfigurationChanged(ExternalAccountOAuthError):
    """Provider OAuth settings changed during an in-flight attempt."""

    code = "configuration_changed"


class ExternalAccountOAuthProviderRejected(ExternalAccountOAuthError):
    """Provider rejected or could not complete identity verification."""

    code = "provider_rejected"


class ExternalAccountLinkNotFound(ExternalAccountLinkError):
    """Requested account-link resource is unavailable to this actor."""


class ExternalAccountLinkActorMismatch(ExternalAccountLinkNotFound):
    """Verified provider actor does not own the requested origin."""


class ExternalAccountLinkExpired(ExternalAccountLinkError):
    """Origin or candidate is expired."""


@dataclasses.dataclass
class ExternalAccountLinkInvalidCode(ExternalAccountLinkError):
    """Submitted code does not match an eligible candidate."""

    remaining_attempts: int


class ExternalAccountLinkAttemptLimitReached(ExternalAccountLinkError):
    """Origin exhausted its invalid-code budget."""


class ExternalAccountLinkConflict(ExternalAccountLinkError):
    """An active ownership or immutable-state conflict prevents the operation."""


class ExternalAccountLinkCandidateNotReady(ExternalAccountLinkConflict):
    """Candidate has not completed original-provider proof."""


class ExternalAccountLinkCandidateTerminal(ExternalAccountLinkConflict):
    """Candidate is already cancelled, consumed, or otherwise terminal."""


class ExternalAccountLinkMembershipRequired(ExternalAccountLinkError):
    """Current User is not a member of the origin Workspace."""


class ExternalAccountLinkUnavailable(ExternalAccountLinkError):
    """Connection, User, Session, or provider authority is no longer active."""


class ExternalAccountLinkBusy(ExternalAccountLinkError):
    """Bounded transaction retry was exhausted."""
