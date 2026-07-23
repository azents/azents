"""Runtime Provider enrollment service contracts."""

import datetime
from dataclasses import dataclass

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderKind,
    RuntimeProviderScope,
)


@dataclass(frozen=True)
class RuntimeProviderEnrollmentGrantIssued:
    """One-time plaintext enrollment grant returned only at issuance."""

    grant_id: str
    provider_id: str
    secret: str
    expires_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderCredentialIssued:
    """One-time plaintext Provider credential returned only at exchange."""

    credential_id: str
    provider_id: str
    secret: str
    expires_at: datetime.datetime | None


@dataclass(frozen=True)
class RuntimeProviderCredentialAuthentication:
    """Authenticated identity bound to a durable Provider."""

    binding_id: str
    credential_id: str | None
    provider_id: str
    provider_kind: RuntimeProviderKind
    provider_scope: RuntimeProviderScope
    provider_workspace_id: str | None
    auth_method: RuntimeProviderAuthMethod
    auth_subject: str
    evidence_expires_at: datetime.datetime | None

    def __post_init__(self) -> None:
        """Enforce method-specific evidence persistence invariants."""
        if (
            self.auth_method is RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN
            and self.credential_id is None
        ):
            raise ValueError("issued-token authentication requires credential_id")
        if self.auth_method is RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT:
            if self.credential_id is not None:
                raise ValueError(
                    "Kubernetes ServiceAccount authentication cannot use credential_id"
                )
            if self.evidence_expires_at is None:
                raise ValueError(
                    "Kubernetes ServiceAccount authentication requires evidence expiry"
                )


@dataclass(frozen=True)
class KubernetesServiceAccountTokenReview:
    """Verified Kubernetes ServiceAccount identity returned by TokenReview."""

    authenticated: bool
    username: str | None
    audiences: frozenset[str]
    evidence_expires_at: datetime.datetime | None


@dataclass
class RuntimeProviderEnrollmentUnavailable(Exception):
    """Enrollment grant cannot be exchanged safely."""

    code: str

    def __post_init__(self) -> None:
        Exception.__init__(
            self,
            f"Runtime Provider enrollment unavailable: {self.code}",
        )


@dataclass
class RuntimeProviderCredentialUnavailable(Exception):
    """Provider credential cannot authenticate a control stream."""

    code: str
