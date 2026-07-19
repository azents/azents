"""System Admin API v1 schemas."""

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole
from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    RetentionApplicationScope,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)
from azents.services.archived_session_retention import (
    RetentionSettingsReadResult,
    RetentionSettingsUpdateResult,
)
from azents.services.system_user_role.data import SystemUserRoleAssignmentOutput


class ArchiveRetentionApplicationResponse(ArchivedSessionRetentionApplication):
    """Durable existing-archive recalculation progress response."""

    @classmethod
    def from_domain(
        cls,
        application: ArchivedSessionRetentionApplication,
    ) -> "ArchiveRetentionApplicationResponse":
        """Convert durable application state to an API response."""
        return cls.model_validate(application.model_dump())


class FileLifecycleSettingsResponse(SystemFileLifecycleSettings):
    """Instance-wide file lifecycle settings response."""

    active_application: ArchiveRetentionApplicationResponse | None

    @classmethod
    def from_domain(
        cls,
        result: RetentionSettingsReadResult,
    ) -> "FileLifecycleSettingsResponse":
        """Convert settings and active recalculation to an API response."""
        return cls(
            **result.settings.model_dump(),
            active_application=(
                ArchiveRetentionApplicationResponse.from_domain(
                    result.active_application
                )
                if result.active_application is not None
                else None
            ),
        )


class ArchiveRetentionPreviewRequest(BaseModel):
    """Proposed archive retention value for impact preview."""

    archived_session_retention_days: int | None = Field(
        ge=0,
        description="Whole-day archive retention; null means Unlimited",
    )


class ArchiveRetentionPreviewResponse(RetentionImpactPreview):
    """Existing archive impact preview response."""

    @classmethod
    def from_domain(
        cls,
        preview: RetentionImpactPreview,
    ) -> "ArchiveRetentionPreviewResponse":
        """Convert impact preview to an API response."""
        return cls.model_validate(preview.model_dump())


class FileLifecycleSettingsUpdateRequest(BaseModel):
    """Optimistic archive retention settings update."""

    expected_revision: int = Field(ge=1)
    archived_session_retention_days: int | None = Field(
        ge=0,
        description="Whole-day archive retention; null means Unlimited",
    )
    application_scope: RetentionApplicationScope


class FileLifecycleSettingsUpdateResponse(BaseModel):
    """Updated settings and optional durable recalculation application."""

    settings: FileLifecycleSettingsResponse
    application: ArchiveRetentionApplicationResponse | None

    @classmethod
    def from_domain(
        cls,
        result: RetentionSettingsUpdateResult,
    ) -> "FileLifecycleSettingsUpdateResponse":
        """Convert settings update output to an API response."""
        return cls(
            settings=FileLifecycleSettingsResponse.from_domain(
                RetentionSettingsReadResult(
                    settings=result.settings,
                    active_application=result.application,
                )
            ),
            application=(
                ArchiveRetentionApplicationResponse.from_domain(result.application)
                if result.application is not None
                else None
            ),
        )


class SystemAdminMeResponse(BaseModel):
    """Current system administrator response."""

    user_id: str = Field(description="Current User ID")
    roles: list[SystemUserRole] = Field(description="Current system roles")


class SystemUserRoleAssignmentResponse(SystemUserRoleAssignmentOutput):
    """System role assignment response."""

    @classmethod
    def convert_output(
        cls,
        output: SystemUserRoleAssignmentOutput,
    ) -> "SystemUserRoleAssignmentResponse":
        """Convert service output to an API response."""
        return cls.model_validate(output.model_dump())


class SystemUserRoleAssignmentListResponse(BaseModel):
    """System role assignment list response."""

    items: list[SystemUserRoleAssignmentResponse] = Field(
        description="System role assignments"
    )
    total: int = Field(description="Total assignment count")
