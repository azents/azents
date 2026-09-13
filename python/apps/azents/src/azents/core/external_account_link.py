"""External account linking domain contracts."""

import dataclasses
import datetime
import enum

from azents.core.enums import ExternalChannelProvider


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


class ExternalAccountLinkConflict(ExternalAccountLinkError):
    """An active ownership or immutable-state conflict prevents the operation."""


class ExternalAccountLinkUnavailable(ExternalAccountLinkError):
    """Connection, User, Session, or provider authority is no longer active."""


class ExternalAccountLinkBusy(ExternalAccountLinkError):
    """Bounded transaction retry was exhausted."""
