"""Archive retention sequencing through completed repository operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.archived_session_retention_data import (
    RetentionRecalculationSummary,
    RetentionSettingsReadResult,
    RetentionSettingsUpdateResult,
)
from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    RetentionApplicationScope,
    RetentionImpactPreview,
    SystemFileLifecycleSettings,
)
from azents.repos.archived_session_retention_operations import (
    ArchivedSessionRetentionOperations,
)


@dataclasses.dataclass
class ArchivedSessionRetentionService:
    """Coordinate completed settings and recalculation operations."""

    operations: Annotated[
        ArchivedSessionRetentionOperations, Depends(ArchivedSessionRetentionOperations)
    ]

    async def get_settings(self) -> SystemFileLifecycleSettings:
        """Complete the get settings operation."""
        return await self.operations.get_settings()

    async def get_settings_state(self) -> RetentionSettingsReadResult:
        """Complete the get settings state operation."""
        return await self.operations.get_settings_state()

    async def preview(self, retention_days: int | None) -> RetentionImpactPreview:
        """Complete the preview operation."""
        return await self.operations.preview(retention_days=retention_days)

    async def get_application(
        self, *, application_id: str
    ) -> ArchivedSessionRetentionApplication | None:
        """Complete the get application operation."""
        return await self.operations.get_application(application_id=application_id)

    async def update_settings(
        self,
        *,
        expected_revision: int,
        retention_days: int | None,
        application_scope: RetentionApplicationScope,
        user_id: str,
    ) -> RetentionSettingsUpdateResult:
        """Complete the update settings operation."""
        return await self.operations.update_settings(
            expected_revision=expected_revision,
            retention_days=retention_days,
            application_scope=application_scope,
            user_id=user_id,
        )

    async def recalculate_once(
        self, *, lease_owner: str
    ) -> RetentionRecalculationSummary:
        """Complete the recalculate once operation."""
        return await self.operations.recalculate_once(lease_owner=lease_owner)
