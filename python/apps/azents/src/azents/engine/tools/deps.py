"""Toolkit DI dependencies."""

from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_config, get_credential_cipher
from azents.core.tools import ToolkitProvider
from azents.engine.tools.aws import AwsToolkitProvider
from azents.engine.tools.envvar import EnvVarToolkitProvider
from azents.engine.tools.gcp import GcpToolkitProvider
from azents.engine.tools.github import GitHubToolkitProvider
from azents.engine.tools.goal import GoalStateStore, GoalToolkitProvider
from azents.engine.tools.google_analytics import GoogleAnalyticsToolkitProvider
from azents.engine.tools.kubernetes import KubernetesToolkitProvider
from azents.engine.tools.mcp import McpToolkitProvider
from azents.engine.tools.notion import NotionToolkitProvider
from azents.engine.tools.sentry import SentryToolkitProvider
from azents.engine.tools.skill import SkillStateStore, SkillToolkitProvider
from azents.engine.tools.todo import TodoStateStore, TodoToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.artifact import ArtifactService
from azents.testing.runtime_hooks import TestenvRuntimeHookQAProvider


def get_toolkit_registry(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    config: Annotated[Config, Depends(get_config)],
    artifact_service: Annotated[ArtifactService, Depends(ArtifactService)],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ],
) -> dict[str, ToolkitProvider[Any]]:
    """Create the Toolkit registry.

    :param cipher: Credential encryption/decryption for the MCP toolkit repo
    :param session_manager: DB session manager for MCP toolkits
    :param config: Application settings for GitHub Platform App settings
    :param artifact_service: Service that stores MCP binary output
    :return: Mapping from toolkit_type to ToolkitProvider instances
    """
    github_config = config.github
    registry: dict[str, ToolkitProvider[Any]] = {
        "mcp": McpToolkitProvider(
            connection_repo=MCPOAuthConnectionRepository(cipher=cipher),
            session_manager=session_manager,
            artifact_service=artifact_service,
        ),
        "github": GitHubToolkitProvider(
            platform_app_id=(github_config.platform_app_id if github_config else None),
            platform_private_key=(
                github_config.platform_private_key if github_config else None
            ),
            session_manager=session_manager,
            agent_run_repository=agent_run_repository,
            agent_session_repository=agent_session_repository,
            toolkit_state_repository=toolkit_state_repository,
        ),
        "notion": NotionToolkitProvider(
            connection_repo=MCPOAuthConnectionRepository(cipher=cipher),
            session_manager=session_manager,
            artifact_service=artifact_service,
        ),
        "sentry": SentryToolkitProvider(
            connection_repo=MCPOAuthConnectionRepository(cipher=cipher),
            session_manager=session_manager,
            artifact_service=artifact_service,
        ),
        "gcp": GcpToolkitProvider(
            artifact_service=artifact_service,
            session_manager=session_manager,
        ),
        "aws": AwsToolkitProvider(
            artifact_service=artifact_service,
            session_manager=session_manager,
        ),
        "google_analytics": GoogleAnalyticsToolkitProvider(),
        "kubernetes": KubernetesToolkitProvider(),
        "envvar": EnvVarToolkitProvider(),
    }
    if config.testenv_runtime_hook_qa_enabled:
        registry[TestenvRuntimeHookQAProvider.slug] = TestenvRuntimeHookQAProvider()
    return registry


def get_todo_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ],
) -> TodoToolkitProvider:
    """TodoToolkitProvider dependency."""
    return TodoToolkitProvider(
        store=TodoStateStore(
            session_manager=session_manager,
            agent_run_repository=agent_run_repository,
            agent_session_repository=agent_session_repository,
            toolkit_state_repository=toolkit_state_repository,
        )
    )


def get_goal_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ],
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ],
) -> GoalToolkitProvider:
    """GoalToolkitProvider dependency."""
    return GoalToolkitProvider(
        store=GoalStateStore(
            session_manager=session_manager,
            agent_run_repository=agent_run_repository,
            agent_session_repository=agent_session_repository,
            event_transcript_repository=event_transcript_repository,
            toolkit_state_repository=toolkit_state_repository,
        )
    )


def get_skill_state_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ],
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ],
) -> SkillStateStore:
    """SkillStateStore dependency."""
    return SkillStateStore(
        session_manager=session_manager,
        agent_run_repository=agent_run_repository,
        agent_session_repository=agent_session_repository,
        toolkit_state_repository=toolkit_state_repository,
    )


def get_skill_toolkit_provider(
    skill_store: Annotated[SkillStateStore, Depends(get_skill_state_store)],
) -> SkillToolkitProvider:
    """SkillToolkitProvider dependency without runtime sync support."""
    return SkillToolkitProvider(store=skill_store)
