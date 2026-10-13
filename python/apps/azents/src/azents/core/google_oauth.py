"""Typed Google grant evidence and exact unpublished authorization authority."""

import dataclasses
import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field

from azents.core.google_policy import GoogleTask


class GoogleOAuthError(ValueError):
    """Normalized Google lifecycle error; never retain raw provider payloads."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class GoogleAttemptStatus(enum.StrEnum):
    """Unpublished phases and minimal terminal publication outcome."""

    PENDING = "pending"
    EXCHANGING = "exchanging"
    REVIEW = "review"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    FAILED = "failed"


class GoogleConnectionStatus(enum.StrEnum):
    """Current local renewal eligibility, not a claim of resource access."""

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


@dataclasses.dataclass(frozen=True)
class GoogleSubject:
    """Exact authenticated manager and immutable desired ownership context."""

    user_id: str
    session_id: str
    workspace_id: str
    agent_id: str | None


class GoogleIdentity(BaseModel):
    """Principal obtained only from verified signed Google identity claims."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    issuer: str
    subject: str
    email: str | None


class GoogleTokens(BaseModel):
    """Token receipt with actual scope absence distinct from verified empty scope."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    access_token: str = Field(repr=False, min_length=1)
    refresh_token: str | None = Field(repr=False, min_length=1)
    expires_at: datetime.datetime
    granted_scopes: tuple[str, ...] | None


class GoogleCandidate(BaseModel):
    """Verified staged evidence, never an executable Toolkit credential."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    identity: GoogleIdentity
    tokens: GoogleTokens = Field(repr=False)
    requested_scopes: tuple[str, ...]


class GoogleSavedTarget(BaseModel):
    """Reconnect authority comparison excludes routine access-token renewal."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    toolkit_id: str
    connection_id: str | None
    client_id: str | None
    subject: str | None
    granted_scopes: tuple[str, ...] | None
    status: GoogleConnectionStatus | None
    tasks: tuple[GoogleTask, ...]
    timeout: float
    security_risk_acknowledged: bool


class GoogleSetup(BaseModel):
    """Encrypted attempt inputs; OAuth state and OIDC nonce remain distinct."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    client_id: str
    effective_generation: str = Field(repr=False)
    redirect_uri: str
    state_nonce: str = Field(repr=False)
    oidc_nonce: str = Field(repr=False)
    code_verifier: str = Field(repr=False)
    tasks: tuple[GoogleTask, ...]
    timeout: float
    target: GoogleSavedTarget | None


class GoogleFinalSettings(BaseModel):
    """Complete final reviewed settings; no provider permission booleans accepted."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str | None = Field(max_length=255)
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool
    always_expose_tools: bool
    tasks: tuple[GoogleTask, ...]
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False)
    security_risk_acknowledged: bool = Field(strict=True)


class GoogleReconnectSettings(BaseModel):
    """Reconnect changes authentication selection, not unrelated saved metadata."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tasks: tuple[GoogleTask, ...]
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False)
    security_risk_acknowledged: bool = Field(strict=True)


@dataclasses.dataclass(frozen=True)
class GooglePublication:
    """Historical outcome identity; current does not itself assert readiness."""

    toolkit_id: str
    connection_id: str
    current: bool


@dataclasses.dataclass(frozen=True)
class GoogleAttempt:
    """Detached exact attempt; published outcomes retain no candidate secrets."""

    id: str
    subject: GoogleSubject
    status: GoogleAttemptStatus
    expires_at: datetime.datetime
    setup: GoogleSetup | None = dataclasses.field(repr=False)
    candidate: GoogleCandidate | None = dataclasses.field(repr=False)
    published_toolkit_id: str | None
    published_connection_id: str | None
    final_settings: GoogleFinalSettings | GoogleReconnectSettings | None


@dataclasses.dataclass(frozen=True)
class GoogleConnection:
    """Detached current grant snapshot for exact renewal CAS."""

    id: str
    toolkit_id: str
    client_id: str
    candidate: GoogleCandidate = dataclasses.field(repr=False)
    status: GoogleConnectionStatus
    updated_at: datetime.datetime
    encrypted_payload: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class GoogleAuthorization:
    """Call-local current admission; do not expose credentials in tool metadata."""

    access_token: str = dataclasses.field(repr=False)
    connection_id: str


@dataclasses.dataclass(frozen=True)
class GoogleSavedConnection:
    """Management-only current state; never return credentials directly."""

    toolkit_id: str
    tasks: tuple[GoogleTask, ...]
    timeout: float
    connection: GoogleConnection | None = dataclasses.field(repr=False)
