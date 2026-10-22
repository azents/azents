"""Typed Google grant evidence and exact unpublished authorization authority."""

import dataclasses
import datetime
import enum
from typing import assert_never

from pydantic import BaseModel, ConfigDict, Field

from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_workspace_policy import (
    GoogleWorkspaceConfig,
    GoogleWorkspaceConnectInput,
    GoogleWorkspaceFinalSettings,
)
from azents.core.toolkit_ownership import (
    AgentToolkitOwner,
    ToolkitOwner,
    ToolkitOwnerKind,
    UserToolkitOwner,
    WorkspaceToolkitOwner,
)


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

    @property
    def owner(self) -> WorkspaceToolkitOwner | AgentToolkitOwner:
        """Keep existing shared/Agent context explicit at the owner boundary."""
        if self.agent_id is not None:
            return AgentToolkitOwner(
                kind=ToolkitOwnerKind.AGENT,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
            )
        return WorkspaceToolkitOwner(
            kind=ToolkitOwnerKind.WORKSPACE, workspace_id=self.workspace_id
        )


@dataclasses.dataclass(frozen=True)
class GooglePersonalSubject:
    """Exact active account and explicit Workspace-scoped personal setup target."""

    user_id: str
    session_id: str
    owner: UserToolkitOwner

    def __post_init__(self) -> None:
        if self.owner.user_id != self.user_id:
            raise GoogleOAuthError("forbidden", "Google setup owner does not match.")

    @property
    def workspace_id(self) -> str:
        """Return the real Workspace of this personal connection."""
        return self.owner.workspace_id

    @property
    def agent_id(self) -> None:
        """Personal setup origin is not an Agent ownership relation."""
        return None


GoogleManager = GoogleSubject | GooglePersonalSubject


def google_manager_for_owner(
    user_id: str,
    session_id: str,
    owner: ToolkitOwner,
) -> GoogleManager:
    """Decode canonical ownership into the exact supported management variants."""
    match owner:
        case UserToolkitOwner():
            return GooglePersonalSubject(user_id, session_id, owner)
        case AgentToolkitOwner():
            return GoogleSubject(
                user_id, session_id, owner.workspace_id, owner.agent_id
            )
        case WorkspaceToolkitOwner():
            return GoogleSubject(user_id, session_id, owner.workspace_id, None)
        case _:
            assert_never(owner)


class GoogleIdentity(BaseModel):
    """Principal obtained only from verified signed Google identity claims."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    issuer: str
    subject: str = Field(repr=False)
    email: str | None = Field(repr=False)


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


class GoogleSavedTarget(GoogleWorkspaceConfig):
    """Reconnect authority comparison excludes routine access-token renewal."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    toolkit_id: str
    connection_id: str | None
    client_id: str | None
    subject: str | None
    granted_scopes: tuple[str, ...] | None
    status: GoogleConnectionStatus | None


class GoogleSetup(GoogleWorkspaceConnectInput):
    """Encrypted attempt inputs; OAuth state and OIDC nonce remain distinct."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    client_id: str
    effective_generation: str = Field(repr=False)
    redirect_uri: str
    state_nonce: str = Field(repr=False)
    oidc_nonce: str = Field(repr=False)
    code_verifier: str = Field(repr=False)
    target: GoogleSavedTarget | None


class GoogleFinalSettings(GoogleWorkspaceFinalSettings):
    """Complete reviewed metadata and service/request settings; never grants."""


class GoogleReconnectSettings(GoogleWorkspaceConfig):
    """Reconnect changes reviewed request intent, not unrelated saved metadata."""


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
    subject: GoogleManager
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
class GoogleSavedConnection:
    """Management-only current state; never return credentials directly."""

    toolkit_id: str
    revision: int
    services: tuple[GoogleService, ...]
    tool_groups: tuple[GoogleToolGroup, ...]
    oauth_request_scopes: tuple[str, ...]
    timeout: float
    connection: GoogleConnection | None = dataclasses.field(repr=False)
