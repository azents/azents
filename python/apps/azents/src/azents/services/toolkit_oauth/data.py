"""Typed Toolkit OAuth orchestration inputs, projections and expected failures."""

import dataclasses
import enum


@dataclasses.dataclass(frozen=True)
class ToolkitConnectionTestInput:
    """Validated opaque provider form values, independent of API models."""

    toolkit_type: str
    config: dict[str, object]
    credentials: dict[str, object] | None
    toolkit_config_id: str | None


@dataclasses.dataclass(frozen=True)
class GitHubInstallationProjection:
    """Installation metadata accepted by the existing strict Public projection."""

    id: int
    account_login: str
    account_type: str
    account_avatar_url: str


class ToolkitOAuthFailureReason(enum.StrEnum):
    """Service admission, protocol and resource failures without HTTP policy."""

    INACTIVE_SUBJECT = "inactive_subject"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    MEMBERSHIP_REQUIRED = "membership_required"
    WRITE_PERMISSION_REQUIRED = "write_permission_required"
    TOOLKIT_NOT_FOUND = "toolkit_not_found"
    INVALID_REQUEST = "invalid_request"
    TOKEN_REJECTED = "token_rejected"
    RESOURCE_NOT_FOUND = "resource_not_found"
    PLATFORM_SETTINGS_CHANGED = "platform_settings_changed"


class ToolkitOAuthError(Exception):
    """Carry an expected domain failure for projection after database closure."""

    def __init__(
        self,
        reason: ToolkitOAuthFailureReason,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
