"""Completed database operations used while materializing Engine requests."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.engine_read import (
    EngineInvokeReadRepository,
    EngineModelReadRepository,
    EngineToolkitReadRepository,
)
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.deps import get_toolkit_repository
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository


@dataclasses.dataclass(frozen=True)
class EngineResolveRepositories:
    """Expose only completed operations, never a transaction or session factory."""

    invoke_read: EngineInvokeReadRepository
    model_read: EngineModelReadRepository
    toolkit_read: EngineToolkitReadRepository
    chatgpt_oauth: ChatGPTOAuthRuntimeRepository
    xai_oauth: XaiOAuthRuntimeRepository
    kimi_oauth: KimiOAuthRuntimeRepository


def get_engine_resolve_repositories(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ],
    toolkit_repository: Annotated[ToolkitRepository, Depends(get_toolkit_repository)],
) -> EngineResolveRepositories:
    """Wire request operation repositories at the database composition boundary."""
    return EngineResolveRepositories(
        invoke_read=EngineInvokeReadRepository(
            session_manager=session_manager,
            agent_repository=agent_repository,
            integration_repository=integration_repository,
        ),
        model_read=EngineModelReadRepository(
            session_manager=session_manager,
            integration_repository=integration_repository,
        ),
        toolkit_read=EngineToolkitReadRepository(
            session_manager=session_manager,
            toolkit_repository=toolkit_repository,
        ),
        chatgpt_oauth=ChatGPTOAuthRuntimeRepository(
            session_manager=session_manager,
            integration_repository=integration_repository,
        ),
        xai_oauth=XaiOAuthRuntimeRepository(
            session_manager=session_manager,
            integration_repository=integration_repository,
        ),
        kimi_oauth=KimiOAuthRuntimeRepository(
            session_manager=session_manager,
            integration_repository=integration_repository,
        ),
    )
