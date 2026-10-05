"""Neutral completed Session model availability operation outcomes."""

import dataclasses

from azents.core.model_availability import SessionModelAvailability


@dataclasses.dataclass(frozen=True)
class SessionModelAvailabilityNotFound:
    """The Session is absent or unavailable to the requester."""


@dataclasses.dataclass(frozen=True)
class SessionModelReservationConflict:
    """The optimistic reservation request no longer matches authority."""

    availability: SessionModelAvailability


type SessionModelAvailabilityError = SessionModelAvailabilityNotFound
type SessionModelReservationError = (
    SessionModelAvailabilityNotFound | SessionModelReservationConflict
)
