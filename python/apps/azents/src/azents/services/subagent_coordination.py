"""Model-facing bounded subagent coordination projection."""

import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
)
from azents.repos.subagent_coordination.repository import (
    SubagentCoordinationRepository,
)


@dataclasses.dataclass(frozen=True)
class ListedAgent:
    """One model-facing listed agent."""

    agent_name: str
    agent_status: str


@dataclasses.dataclass(frozen=True)
class SubagentListProjection:
    """Bounded model-facing agent list and privacy-safe counts."""

    agents: tuple[ListedAgent, ...]
    configured_capacity: int
    required_count: int
    selected_inactive_count: int
    omitted_inactive_count: int


@dataclasses.dataclass(frozen=True)
class SubagentCoordinationService:
    """Build bounded model-facing lists from durable coordination state."""

    repository: SubagentCoordinationRepository

    async def list_agents(
        self,
        session: AsyncSession,
        *,
        current_session_id: str,
        configured_capacity: int,
    ) -> SubagentListProjection | None:
        """Return one bounded coordination list for the current root tree."""
        snapshot = await self.repository.project_root_tree(
            session,
            current_session_id=current_session_id,
            configured_capacity=configured_capacity,
        )
        if snapshot is None:
            return None
        return SubagentListProjection(
            agents=tuple(
                ListedAgent(
                    agent_name=row.path,
                    agent_status=_project_agent_status(
                        row.session_run_state,
                        row.latest_run_status,
                    ),
                )
                for row in snapshot.rows
            ),
            configured_capacity=snapshot.configured_capacity,
            required_count=snapshot.required_count,
            selected_inactive_count=snapshot.selected_inactive_count,
            omitted_inactive_count=snapshot.omitted_inactive_count,
        )


def _project_agent_status(
    session_run_state: AgentSessionRunState,
    latest_run_status: AgentRunStatus | None,
) -> str:
    """Project one bounded model-facing coordination status."""
    if session_run_state == AgentSessionRunState.RUNNING:
        return "running"
    if latest_run_status is None:
        return "idle"
    if latest_run_status == AgentRunStatus.COMPLETED:
        return "completed"
    if latest_run_status == AgentRunStatus.FAILED:
        return "errored"
    if latest_run_status in {
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return "interrupted"
    return latest_run_status.value
