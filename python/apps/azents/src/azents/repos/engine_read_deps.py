"""Composition-root factories for concrete completed Engine read dependencies."""

from typing import Annotated

from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.engine_read import (
    EngineInvokeReadRepository,
    EngineModelReadRepository,
    EngineToolkitReadRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.toolkit import ToolkitRepository


def get_engine_model_read_repository(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ],
) -> EngineModelReadRepository:
    """Compose one model read dependency without exporting its factory."""
    return EngineModelReadRepository(
        session_manager=session_manager, integration_repository=integration_repository
    )


def get_engine_invoke_read_repository(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ],
) -> EngineInvokeReadRepository:
    """Compose the existing atomic invocation read dependency."""
    return EngineInvokeReadRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        integration_repository=integration_repository,
    )


def get_engine_toolkit_read_repository(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> EngineToolkitReadRepository:
    """Compose a completed effective Toolkit read dependency."""
    return EngineToolkitReadRepository(
        session_manager=session_manager,
        toolkit_repository=ToolkitRepository(cipher=cipher),
    )
