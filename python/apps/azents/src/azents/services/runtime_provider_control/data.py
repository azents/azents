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
