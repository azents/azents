"""Frozen exact identity for completed Runtime stream route operations."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class RuntimeStreamRouteEpoch:
    """Existing four-field route identity, without additional authority policy."""

    runtime_id: str
    owner_boot_id: str
    session_lease_id: str
    lease_generation: int
