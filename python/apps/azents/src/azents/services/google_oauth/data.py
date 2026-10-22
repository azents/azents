"""Token-free Google management contracts with independent service/grant evidence."""

import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from azents.core.google_oauth import GoogleIdentity
from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_workspace_policy import (
    GoogleDriveAccess,
    GoogleWorkspaceConnectInput,
)
from azents.services.google_oauth.workspace_projection import GoogleServiceAccess


class GoogleConnectInput(GoogleWorkspaceConnectInput):
    """Explicit service/scope intent before consent; requested scopes are not grants."""


class GoogleConnectOutput(BaseModel):
    """Browser navigation receipt, not a saved/executable connection."""

    attempt_id: str
    authorization_url: str
    expires_at: datetime.datetime


class GoogleServicesUpdateInput(BaseModel):
    """Revision-fenced local switch save; empty services is a valid inactive state."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_revision: int = Field(ge=0, strict=True)
    services: tuple[GoogleService, ...]
    tool_groups: tuple[GoogleToolGroup, ...]

    @field_validator("services")
    @classmethod
    def canonical_services(
        cls, value: tuple[GoogleService, ...]
    ) -> tuple[GoogleService, ...]:
        return tuple(sorted(set(value)))


class GooglePickerTokenInput(BaseModel):
    """Only the expected current target is accepted; scope/token inputs are closed."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_revision: int = Field(ge=0, strict=True)
    connection_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class GooglePickerTokenOutput(BaseModel):
    """Transient manager-browser bearer receipt, never an Agent/model response."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_token: str = Field(min_length=1, repr=False)
    expires_at: AwareDatetime
    api_key: str = Field(min_length=1, repr=False)
    app_id: str = Field(min_length=1)


class GoogleReview(BaseModel):
    """Actual grant and reviewed intent remain separate, with no token projection."""

    attempt_id: str
    expires_at: datetime.datetime
    identity: GoogleIdentity
    client_id: str
    ownership: Literal["agent_only", "workspace_shared", "personal"]
    reconnect_toolkit_id: str | None
    services: tuple[GoogleService, ...]
    tool_groups: tuple[GoogleToolGroup, ...]
    oauth_request_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...] | None
    timeout: float
    accesses: tuple[GoogleServiceAccess, ...]
    drive_access: GoogleDriveAccess
    grant_result: Literal["full", "partial", "none", "unknown"] = Field(
        description=(
            "Receipt evidence for requested Workspace scopes, not an action ceiling. "
            "Actual supported tools and Drive extent are projected independently."
        )
    )
    renewable: bool
    can_confirm: bool
    service_access_verified: Literal[False] = Field(
        description="Scope review does not verify live resource access."
    )


class GooglePublishedOutput(BaseModel):
    """Idempotent historical outcome; current binding is not current readiness."""

    toolkit_id: str
    connection_id: str
    current: bool


class GoogleCancelOutput(BaseModel):
    """Publication won the race or the candidate was locally abandoned."""

    cancelled: bool
    publication: GooglePublishedOutput | None


class GoogleConnectionOutput(BaseModel):
    """Saved local settings and actual grant evidence under current manager access."""

    toolkit_id: str
    revision: int
    connection_id: str | None
    status: Literal[
        "not_connected",
        "connected",
        "reconnect_required",
        "operator_setup_required",
        "client_changed",
    ]
    identity: GoogleIdentity | None
    services: tuple[GoogleService, ...]
    tool_groups: tuple[GoogleToolGroup, ...]
    oauth_request_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...] | None
    timeout: float
    accesses: tuple[GoogleServiceAccess, ...]
    drive_access: GoogleDriveAccess
    renewable: bool
    service_access_verified: Literal[False] = Field(
        description="Saved grant metadata is not a live access probe."
    )
