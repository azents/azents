"""Pure one-time cutover primitives; never an application old/new config decoder.

The stopped cutover owns validation and atomic persistence. These functions do not
read credentials, infer grants, or perform provider/Runtime/database I/O. Keep the
legacy mapping fixed when the direct request catalog evolves.
"""

import dataclasses
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import (
    GoogleWorkspaceConfig,
    GoogleWorkspaceFinalSettings,
)

LegacyGoogleTask = Literal[
    "calendar_read",
    "calendar_availability",
    "calendar_edit",
    "drive_read",
    "drive_files",
    "gmail_read",
    "gmail_drafts",
    "gmail_modify",
]


@dataclasses.dataclass(frozen=True)
class _LegacyRequest:
    service: GoogleService
    scopes: tuple[str, ...]


def _request(service: GoogleService, *scopes: str) -> _LegacyRequest:
    return _LegacyRequest(
        service, tuple("https://www.googleapis.com/auth/" + scope for scope in scopes)
    )


_LEGACY_REQUESTS = MappingProxyType(
    {
        "calendar_read": _request(
            GoogleService.CALENDAR,
            "calendar.events.readonly",
            "calendar.calendarlist.readonly",
        ),
        "calendar_availability": _request(
            GoogleService.CALENDAR,
            "calendar.events.freebusy",
            "calendar.calendarlist.readonly",
        ),
        "calendar_edit": _request(GoogleService.CALENDAR, "calendar.events"),
        "drive_read": _request(GoogleService.DRIVE, "drive.readonly"),
        "drive_files": _request(GoogleService.DRIVE, "drive.file"),
        "gmail_read": _request(GoogleService.GMAIL, "gmail.readonly"),
        "gmail_drafts": _request(GoogleService.GMAIL, "gmail.compose"),
        "gmail_modify": _request(GoogleService.GMAIL, "gmail.modify"),
    }
)


class GoogleCutoverError(ValueError):
    """Nonsecret diagnostic; no raw payload or validation input is retained."""


class _LegacyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tasks: tuple[LegacyGoogleTask, ...] = Field(min_length=1)
    # Historical config allowed omission with this exact value.
    timeout: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    security_risk_acknowledged: bool = Field(strict=True)


class _LegacyFinalSettings(_LegacyConfig):
    name: str | None = Field(max_length=255)
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool = Field(strict=True)
    always_expose_tools: bool = Field(strict=True)
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False)


_CONFIG = TypeAdapter(_LegacyConfig | GoogleWorkspaceConfig)
_FINAL = TypeAdapter(
    _LegacyFinalSettings
    | _LegacyConfig
    | GoogleWorkspaceFinalSettings
    | GoogleWorkspaceConfig
)


def _transform(config: _LegacyConfig) -> GoogleWorkspaceConfig:
    requests = tuple(_LEGACY_REQUESTS[task] for task in config.tasks)
    return GoogleWorkspaceConfig(
        services=tuple(request.service for request in requests),
        oauth_request_scopes=tuple(
            scope for request in requests for scope in request.scopes
        ),
        timeout=config.timeout,
    )


def transform_google_config(payload: object) -> GoogleWorkspaceConfig:
    """Preflight old input or final state without a runtime compatibility branch."""
    try:
        decoded = _CONFIG.validate_python(payload)
    except ValidationError:
        raise GoogleCutoverError(
            "Invalid Google Toolkit configuration for cutover."
        ) from None
    if isinstance(decoded, _LegacyConfig):
        return _transform(decoded)
    return decoded


def transform_google_final_settings(
    payload: object,
) -> GoogleWorkspaceFinalSettings | GoogleWorkspaceConfig:
    """Preserve historical metadata; convert selection only, never current grants."""
    try:
        decoded = _FINAL.validate_python(payload)
    except ValidationError:
        raise GoogleCutoverError(
            "Invalid published Google settings for cutover."
        ) from None
    if isinstance(decoded, _LegacyFinalSettings):
        config = _transform(decoded)
        return GoogleWorkspaceFinalSettings(
            services=config.services,
            oauth_request_scopes=config.oauth_request_scopes,
            timeout=config.timeout,
            name=decoded.name,
            slug=decoded.slug,
            description=decoded.description,
            prompt=decoded.prompt,
            enabled=decoded.enabled,
            always_expose_tools=decoded.always_expose_tools,
        )
    if isinstance(decoded, _LegacyConfig):
        return _transform(decoded)
    return decoded


class _PublishedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    toolkit_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)


@dataclasses.dataclass(frozen=True)
class GoogleCutoverOutcome:
    """Historical publication identity is not a live connection/readiness claim."""

    toolkit_id: str
    connection_id: str
    final_settings: GoogleWorkspaceFinalSettings | GoogleWorkspaceConfig


def transform_google_published_outcome(
    *,
    toolkit_id: str | None,
    connection_id: str | None,
    final_settings: object,
) -> GoogleCutoverOutcome:
    """Reject incomplete identities before any writer begins persisting changes."""
    try:
        identity = _PublishedIdentity.model_validate(
            {"toolkit_id": toolkit_id, "connection_id": connection_id}
        )
    except ValidationError:
        raise GoogleCutoverError(
            "Incomplete published Google outcome identity."
        ) from None
    return GoogleCutoverOutcome(
        toolkit_id=identity.toolkit_id,
        connection_id=identity.connection_id,
        final_settings=transform_google_final_settings(final_settings),
    )
