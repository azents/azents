"""Agent Project default repository data."""

import dataclasses
import datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentProjectDefault:
    """Agent-owned default Project path for new sessions."""

    id: str
    agent_id: str
    path: str
    position: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
