"""Resolve exact Agent Runtime Profiles through completed database operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.repos.runtime_profile_resolution_operations import (
    RuntimeProfileResolutionOperationRepository,
    RuntimeProfileResolutionRejected,
)
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionResult,
    RuntimeProfileResolutionUnavailable,
)


@dataclasses.dataclass
class RuntimeProfileResolutionService:
    """Project one completed atomic Runtime desired configuration resolution."""

    operations: Annotated[
        RuntimeProfileResolutionOperationRepository,
        Depends(RuntimeProfileResolutionOperationRepository),
    ]

    async def ensure_for_agent(self, agent_id: str) -> RuntimeProfileResolutionResult:
        """Return committed desired/applied state or the existing bounded failure."""
        try:
            record = await self.operations.ensure_for_agent(agent_id)
        except RuntimeProfileResolutionRejected as error:
            raise RuntimeProfileResolutionUnavailable(
                code=error.code,
                provider_id=error.provider_id,
                message=error.message,
            ) from error
        return RuntimeProfileResolutionResult(
            runtime=record.runtime,
            desired=record.desired,
            applied=record.applied,
            runtime_created=record.runtime_created,
        )
