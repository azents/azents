"""Canonical authority for internal Session resource operations."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class SessionResourceAuthority:
    """Validated canonical workload identity for internal resource access."""

    workspace_id: str
    agent_id: str
    session_id: str
    root_session_id: str
    run_id: str
    run_index: int
    owner_generation: int
