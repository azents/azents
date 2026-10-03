"""Revisioned automatic Session Project policy domain contract."""

import dataclasses
import datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentAutomaticProjectPolicy:
    """Revisioned ordered Agent Project policy for automatic root Sessions."""

    agent_id: str
    revision: int
    project_paths: tuple[str, ...]
    updated_by_workspace_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
