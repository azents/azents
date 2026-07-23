"""System Settings Admin API v1 schemas."""

import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES,
    MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
)
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingFieldSource,
    SystemSettingHealthStatus,
    SystemSettingSecretActionType,
    SystemSettingValidationStatus,
)
from azents.repos.system_setting.data import StoredSystemSettingAuditEvent
from azents.services.github_platform_system_setting.data import (
    PlatformGitHubAppBindingState,
    PlatformGitHubAppCandidateState,
    PlatformGitHubAppDetail,
    PlatformGitHubAppEffectiveStatus,
    PlatformGitHubAppFieldState,
    PlatformGitHubAppHealthState,
    PlatformGitHubAppInventoryItem,
)


class SystemSettingSecretActionRequest(BaseModel):
    """Explicit secret replacement or clearing action."""

    action: SystemSettingSecretActionType
    value: str | None = None

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        """Require replacement plaintext and reject plaintext on clear."""
        if self.action is SystemSettingSecretActionType.REPLACE and self.value is None:
            raise ValueError("Secret replacement requires a value.")
        if (
            self.action is SystemSettingSecretActionType.CLEAR
            and self.value is not None
        ):
            raise ValueError("Secret clear cannot include a value.")
        return self


class ExternalChannelFilesPatchRequest(BaseModel):
    """Optimistic partial update for External Channel file limits."""

    expected_version: int = Field(ge=0)
    inbound_max_file_bytes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
    )
    outbound_max_file_bytes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
    )
    outbound_max_action_bytes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES,
    )


class ExternalChannelFilesDetailResponse(BaseModel):
    """Effective External Channel file policy without internal generation data."""

    section: str
    schema_version: int
    admin_version: int
    inbound_max_file_bytes: int
    outbound_max_file_bytes: int
    outbound_max_action_bytes: int

    @classmethod
    def from_domain(cls, resolved: ResolvedSystemSetting) -> Self:
        """Convert one effective typed file policy."""
        config = resolved.config
        if not isinstance(config, ExternalChannelFilesConfig):
            raise TypeError("Unexpected External Channel files config model.")
        return cls(
            section=resolved.section.value,
            schema_version=resolved.schema_version,
            admin_version=resolved.admin_version,
            inbound_max_file_bytes=config.inbound_max_file_bytes,
            outbound_max_file_bytes=config.outbound_max_file_bytes,
            outbound_max_action_bytes=config.outbound_max_action_bytes,
        )


class SystemSettingVersionConflictDetail(BaseModel):
    """Stable optimistic-mutation conflict detail."""

    code: Literal["stale_system_setting_version"]
    message: str
    current_version: int


class SystemSettingVersionConflictResponse(BaseModel):
    """FastAPI error envelope for an optimistic System Settings conflict."""

    detail: SystemSettingVersionConflictDetail


class PlatformGitHubAppPatchRequest(BaseModel):
    """Optimistic partial update for the Platform GitHub App Admin base."""

    expected_version: int = Field(ge=0)
    app_id: str | None = None
    client_id: str | None = None
    private_key: SystemSettingSecretActionRequest | None = None
    client_secret: SystemSettingSecretActionRequest | None = None


class PlatformGitHubAppConfirmRequest(BaseModel):
    """Confirmation for an unchanged validated candidate impact."""

    candidate_id: str
    expected_version: int = Field(ge=0)
    confirmation_action: str


class PlatformGitHubAppFieldResponse(BaseModel):
    """Redacted field response."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    secret: bool
    value: str | None
    configured: bool
    source: SystemSettingFieldSource
    environment_variable: str
    fallback_configured: bool
    fallback_last_changed_at: datetime.datetime | None

    @classmethod
    def from_domain(cls, field: PlatformGitHubAppFieldState) -> Self:
        """Convert a redacted field projection."""
        return cls.model_validate(field)


class PlatformGitHubAppCandidateResponse(BaseModel):
    """Redacted candidate lifecycle response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    base_version: int
    validation_status: SystemSettingValidationStatus
    validation_code: str | None
    validation_message: str | None
    action_hint: str | None
    impact: dict[str, Any] | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    expires_at: datetime.datetime

    @classmethod
    def from_domain(cls, candidate: PlatformGitHubAppCandidateState) -> Self:
        """Convert a redacted candidate projection."""
        return cls.model_validate(candidate)


class PlatformGitHubAppHealthResponse(BaseModel):
    """Current-effective explicit health response."""

    model_config = ConfigDict(from_attributes=True)

    status: SystemSettingHealthStatus
    code: str | None
    message: str | None
    action_hint: str | None
    metadata: dict[str, Any] | None
    checked_at: datetime.datetime

    @classmethod
    def from_domain(cls, health: PlatformGitHubAppHealthState) -> Self:
        """Convert the current-effective health projection."""
        return cls.model_validate(health)


class PlatformGitHubAppBindingResponse(BaseModel):
    """Redacted resources that require reconnect for the effective App."""

    model_config = ConfigDict(from_attributes=True)

    affected_user_count: int
    affected_installation_count: int
    affected_toolkit_count: int
    affected_agent_count: int

    @classmethod
    def from_domain(cls, impact: PlatformGitHubAppBindingState) -> Self:
        """Convert current identity-binding impact counts."""
        return cls.model_validate(impact)


class PlatformGitHubAppDetailResponse(BaseModel):
    """Redacted Platform GitHub App detail response."""

    section: str
    schema_version: int
    admin_version: int
    effective_status: PlatformGitHubAppEffectiveStatus
    fields: list[PlatformGitHubAppFieldResponse]
    candidate: PlatformGitHubAppCandidateResponse | None
    health: PlatformGitHubAppHealthResponse | None
    binding_impact: PlatformGitHubAppBindingResponse | None
    activation_validation_status: SystemSettingValidationStatus | None
    app_slug: str | None

    @classmethod
    def from_domain(cls, detail: PlatformGitHubAppDetail) -> Self:
        """Convert the complete redacted detail projection."""
        return cls(
            section=detail.section,
            schema_version=detail.schema_version,
            admin_version=detail.admin_version,
            effective_status=detail.effective_status,
            fields=[
                PlatformGitHubAppFieldResponse.from_domain(field)
                for field in detail.fields
            ],
            candidate=(
                PlatformGitHubAppCandidateResponse.from_domain(detail.candidate)
                if detail.candidate is not None
                else None
            ),
            health=(
                PlatformGitHubAppHealthResponse.from_domain(detail.health)
                if detail.health is not None
                else None
            ),
            binding_impact=(
                PlatformGitHubAppBindingResponse.from_domain(detail.binding_impact)
                if detail.binding_impact is not None
                else None
            ),
            activation_validation_status=detail.activation_validation_status,
            app_slug=detail.app_slug,
        )


class SystemSettingInventoryItemResponse(BaseModel):
    """Generic System Settings inventory item."""

    model_config = ConfigDict(from_attributes=True)

    section: str
    display_name: str
    effective_status: PlatformGitHubAppEffectiveStatus
    admin_version: int
    environment_managed_field_count: int
    candidate_status: SystemSettingValidationStatus | None

    @classmethod
    def from_domain(cls, item: PlatformGitHubAppInventoryItem) -> Self:
        """Convert one inventory item."""
        return cls.model_validate(item)


class SystemSettingInventoryResponse(BaseModel):
    """System Settings inventory response."""

    items: list[SystemSettingInventoryItemResponse]


class SystemSettingAuditEventResponse(BaseModel):
    """Metadata-only System Settings audit event."""

    id: str
    section: str
    event_type: SystemSettingAuditEventType
    source: SystemSettingAuditSource
    previous_version: int | None
    new_version: int | None
    actor_user_id: str | None
    changed_fields: list[str]
    secret_actions: dict[str, str]
    validation_status: SystemSettingValidationStatus | None
    candidate_id: str | None
    impact_confirmed: bool
    confirmation_action: str | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime

    @classmethod
    def from_domain(cls, event: StoredSystemSettingAuditEvent) -> Self:
        """Convert a metadata-only audit event."""
        return cls(
            id=event.id,
            section=event.section.value,
            event_type=event.event_type,
            source=event.source,
            previous_version=event.previous_version,
            new_version=event.new_version,
            actor_user_id=event.actor_user_id,
            changed_fields=event.changed_fields,
            secret_actions=event.secret_actions,
            validation_status=event.validation_status,
            candidate_id=event.candidate_id,
            impact_confirmed=event.impact_confirmed,
            confirmation_action=event.confirmation_action,
            metadata=event.metadata,
            created_at=event.created_at,
        )


class SystemSettingAuditEventListResponse(BaseModel):
    """Paginated metadata-only System Settings audit events."""

    items: list[SystemSettingAuditEventResponse]
    total: int
