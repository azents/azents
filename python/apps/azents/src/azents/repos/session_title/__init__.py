"""Database operations for automatic Session title generation."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)

from .data import SessionTitleGenerationSnapshot


@dataclasses.dataclass
class SessionTitleRepository:
    """Own database-only automatic Session title operations."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def load_generation_snapshot(
        self,
        *,
        session_id: str,
        generation_event_id: str,
    ) -> SessionTitleGenerationSnapshot | None:
        """Load the eligible title owner, model selection, and credentials."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None:
                return None
            if not self._generation_is_current(
                agent_session,
                generation_event_id=generation_event_id,
            ):
                return None
            agent = await self.agent_repository.get_by_id(
                session, agent_session.agent_id
            )
            if agent is None:
                return None
            selection = agent.lightweight_model_selection
            integration = await self.integration_repository.get_by_id_with_secrets(
                session,
                selection.llm_provider_integration_id,
            )
            if integration is None or not integration.enabled:
                return None
            return SessionTitleGenerationSnapshot(
                agent_id=agent.id,
                selection=selection,
                integration=integration,
            )

    async def generation_is_current(
        self,
        *,
        session_id: str,
        generation_event_id: str,
    ) -> bool:
        """Return whether the initial automatic title still owns generation."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            return self._generation_is_current(
                agent_session,
                generation_event_id=generation_event_id,
            )

    async def replace_initial_auto_title(
        self,
        *,
        session_id: str,
        title: str,
        event_id: str,
    ) -> AgentSession | None:
        """Atomically replace the current initial automatic title."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.replace_initial_auto_title(
                session,
                session_id=session_id,
                title=title,
                event_id=event_id,
            )

    def _generation_is_current(
        self,
        agent_session: AgentSession | None,
        *,
        generation_event_id: str,
    ) -> bool:
        """Check the durable automatic-title ownership predicate."""
        return (
            agent_session is not None
            and agent_session.title_source == AgentSessionTitleSource.AUTO_INITIAL
            and agent_session.title_generation_event_id == generation_event_id
        )
