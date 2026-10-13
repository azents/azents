"""Allowlisted Google management DTOs; internal credential models are never returned."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.google_oauth import GoogleIdentity
from azents.core.google_policy import GoogleService, GoogleTask


class GoogleConnectInput(BaseModel):
    """Explicit work selection before initial or ordinary reconnect authorization."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tasks: tuple[GoogleTask, ...] = Field(min_length=1)
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False)


class GoogleConnectOutput(BaseModel):
    """Browser navigation receipt, not a saved/executable connection."""

    attempt_id: str
    authorization_url: str
    expires_at: datetime.datetime


class GoogleTaskAccess(BaseModel):
    """Task-level permission evidence; no live resource-access promise."""

    task: GoogleTask
    service: GoogleService
    status: Literal["permitted", "partial", "not_granted", "unknown"]
    permitted_tools: tuple[str, ...]
    unavailable_tools: tuple[str, ...]


class GoogleReview(BaseModel):
    """Actual grant result with token-free exact ownership/capability projection."""

    attempt_id: str
    expires_at: datetime.datetime
    identity: GoogleIdentity
    client_id: str
    ownership: Literal["agent_only", "workspace_shared"]
    reconnect_toolkit_id: str | None
    requested_tasks: tuple[GoogleTask, ...]
    timeout: float
    tasks: tuple[GoogleTaskAccess, ...]
    grant_result: Literal["full", "partial", "none", "unknown"]
    renewable: bool
    can_confirm: bool
    service_access_verified: bool = Field(
        strict=True, description="Scope review does not verify live resource access."
    )
    security_notice: str


class GooglePublishedOutput(BaseModel):
    """Idempotent historical outcome; current binding is not current readiness."""

    toolkit_id: str
    connection_id: str
    current: bool


class GoogleCancelOutput(BaseModel):
    """Publication won the race or candidate was locally abandoned."""

    cancelled: bool
    publication: GooglePublishedOutput | None


class GoogleConnectionOutput(BaseModel):
    """Saved identity, authorization and selected work under manager authority."""

    toolkit_id: str
    status: Literal[
        "not_connected",
        "connected",
        "reconnect_required",
        "operator_setup_required",
        "client_changed",
    ]
    identity: GoogleIdentity | None
    selected_tasks: tuple[GoogleTask, ...]
    timeout: float
    tasks: tuple[GoogleTaskAccess, ...]
    renewable: bool
    service_access_verified: bool = Field(
        strict=True, description="Saved grant metadata is not a live access probe."
    )


GOOGLE_SECURITY_NOTICE = (
    "Google emails, files and events remain untrusted content. "
    "Azents screens known instruction-override and exfiltration patterns, "
    "but novel, semantic, obfuscated and multilingual attacks may be missed. "
    "False positives and inspection limits may block legitimate content. "
    "A blocked response does not undo an operation Google may have completed. "
    "Shared runs use the connected account, not each participant's private account."
)
