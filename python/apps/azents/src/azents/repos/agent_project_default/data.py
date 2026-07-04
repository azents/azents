"""Agent Project default repository data."""

import dataclasses
import datetime

from azents.core.enums import AgentProjectDefaultItemType


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentProjectDefaultCreate:
    """Agent-owned default workspace item create input."""

    path: str
    item_type: AgentProjectDefaultItemType


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentProjectDefault:
    """Agent-owned default workspace item for new sessions."""

    id: str
    agent_id: str
    path: str
    item_type: AgentProjectDefaultItemType
    position: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
