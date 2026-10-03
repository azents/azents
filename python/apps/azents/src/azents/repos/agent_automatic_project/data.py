"""Agent automatic Project policy repository data."""

import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentAutomaticProjectPolicyRevisionConflict:
    """Optimistic replacement failed because the expected revision was stale."""

    agent_id: str
    expected_revision: int
