"""Compacted-event retention policy validation and cleanup orchestration."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.repos.archived_session_retention.data import SystemFileLifecycleSettings
from azents.repos.compacted_event_retention import (
    CompactedEventCleanupSummary,
    CompactedEventRetentionOperations,
)


@dataclasses.dataclass
class CompactedEventRetentionService:
    """Expose independent compacted-event policy and periodic maintenance."""

    operations: Annotated[
        CompactedEventRetentionOperations, Depends(CompactedEventRetentionOperations)
    ]

    async def update_settings(
        self, *, expected_revision: int, retention_days: int | None, user_id: str
    ) -> SystemFileLifecycleSettings:
        """Validate and update compacted-event policy without synchronous deletion."""
        if retention_days is not None and (
            isinstance(retention_days, bool) or not 0 <= retention_days <= 2_147_483_647
        ):
            raise ValueError("Retention days must be a non-negative whole-day integer")
        return await self.operations.update_settings(
            expected_revision=expected_revision,
            retention_days=retention_days,
            user_id=user_id,
        )

    async def cleanup_once(self) -> CompactedEventCleanupSummary:
        """Complete one bounded cleanup transaction."""
        return await self.operations.cleanup_once(
            now=datetime.datetime.now(datetime.UTC), limit=1000
        )
