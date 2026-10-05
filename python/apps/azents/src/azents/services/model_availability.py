"""Completed Session model availability and Primary reservation service."""

import dataclasses
from typing import Annotated

from azcommon.result import Result
from fastapi import Depends

from azents.core.model_availability import (
    ModelCandidateIdentity,
    SessionModelAvailability,
)
from azents.core.model_availability_operations import (
    SessionModelAvailabilityError,
    SessionModelReservationError,
)
from azents.repos.session_model_availability import SessionModelAvailabilityRepository


@dataclasses.dataclass
class SessionModelAvailabilityService:
    """Expose model recovery operations without database session capabilities."""

    repository: Annotated[
        SessionModelAvailabilityRepository, Depends(SessionModelAvailabilityRepository)
    ]

    async def get(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[SessionModelAvailability, SessionModelAvailabilityError]:
        """Return the completed authorized DB-derived availability projection."""
        return await self.repository.get(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def reserve(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        semantic_label: str,
        primary: ModelCandidateIdentity,
    ) -> Result[SessionModelAvailability, SessionModelReservationError]:
        """Reserve the exact current Primary recovery opportunity once."""
        return await self.repository.reserve(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            semantic_label=semantic_label,
            primary=primary,
        )

    async def cancel(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        reservation_generation: int,
    ) -> Result[SessionModelAvailability, SessionModelReservationError]:
        """Cancel only the exact current Session reservation generation."""
        return await self.repository.cancel(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            reservation_generation=reservation_generation,
        )
