"""Completed database-only reads for Worker Executor orchestration."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.action_execution_data import ActionExecutionProjection
from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.worker_executor_read_data import (
    WorkerModelConfigurationSnapshot,
    WorkerModelInputTranscript,
    WorkerSessionTreeChangeRouting,
)


@dataclass(frozen=True)
class WorkerExecutorReadRepository:
    """Finish durable snapshots before provider, Runtime or publication effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]

    async def get_agent(self, agent_id: str) -> Agent | None:
        """Read an unlocked Agent without strengthening missing-Agent policy."""
        async with self.session_manager() as session:
            result = await self.agent_repository.get_by_id(session, agent_id)
        return result

    async def get_session(self, session_id: str) -> AgentSession | None:
        """Read an unlocked Session for the caller's existing missing-row outcome."""
        async with self.session_manager() as session:
            result = await self.agent_session_repository.get_by_id(session, session_id)
        return result

    async def list_tree_session_ids(
        self, *, root_session_agent_id: str
    ) -> tuple[str, ...]:
        """Read a tree and detach its deduplicated ordered routing identities."""
        async with self.session_manager() as session:
            agents = await self.agent_session_repository.list_session_agent_tree(
                session,
                root_session_agent_id=root_session_agent_id,
            )
            result = tuple(sorted({agent.agent_session_id for agent in agents}))
        return result

    async def get_session_agent(self, session_id: str) -> SessionAgent | None:
        """Read the current SessionAgent, preserving missing-row suppression."""
        async with self.session_manager() as session:
            result = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
        return result

    async def tree_change_routes(
        self, session_agent_ids: list[str]
    ) -> tuple[WorkerSessionTreeChangeRouting, ...]:
        """Read changed nodes and each distinct audience within one transaction."""
        unique_ids = list(dict.fromkeys(session_agent_ids))
        if not unique_ids:
            return ()
        async with self.session_manager() as session:
            changed_agents = []
            for session_agent_id in unique_ids:
                agent = await self.agent_session_repository.get_session_agent_by_id(
                    session,
                    session_agent_id,
                )
                if agent is not None:
                    changed_agents.append(agent)
            audiences: dict[str, tuple[str, ...]] = {}
            for agent in changed_agents:
                if agent.root_session_agent_id in audiences:
                    continue
                tree = await self.agent_session_repository.list_session_agent_tree(
                    session,
                    root_session_agent_id=agent.root_session_agent_id,
                )
                audiences[agent.root_session_agent_id] = tuple(
                    sorted({node.agent_session_id for node in tree})
                )
            result = tuple(
                WorkerSessionTreeChangeRouting(
                    root_session_agent_id=agent.root_session_agent_id,
                    changed_session_agent_id=agent.id,
                    target_session_ids=audiences[agent.root_session_agent_id],
                )
                for agent in changed_agents
            )
        return result

    async def model_configuration_snapshot(
        self, *, agent_id: str, session_id: str
    ) -> WorkerModelConfigurationSnapshot:
        """Capture exact drift inputs without adding locks, versions or fences."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            current = await self.agent_session_repository.get_by_id(session, session_id)
            result = WorkerModelConfigurationSnapshot(agent=agent, session=current)
        return result

    async def action_execution_projections(
        self, session_id: str
    ) -> list[ActionExecutionProjection]:
        """Complete ordered pending/running action projection reads."""
        async with self.session_manager() as session:
            result = (
                await self.action_execution_repository.list_projections_by_session_id(
                    session,
                    session_id=session_id,
                )
            )
        return result

    async def model_input_transcript(
        self, session_id: str
    ) -> WorkerModelInputTranscript:
        """Keep the Session head and transcript within the same read transaction."""
        async with self.session_manager() as session:
            current = await self.agent_session_repository.get_by_id(session, session_id)
            head_event_id = (
                current.model_input_head_event_id if current is not None else None
            )
            events = await self.event_transcript_repository.list_for_model_input(
                session,
                session_id,
                head_event_id=head_event_id,
            )
            result = WorkerModelInputTranscript(
                head_event_id=head_event_id, events=tuple(events)
            )
        return result
