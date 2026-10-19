"""Expected Agent domain failures shared by repository, service, and API layers."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Agent not found."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class InvalidRoutineCadence:
    """The effective minimum action delay exceeds the checking interval."""
