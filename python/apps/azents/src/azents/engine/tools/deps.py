"""Toolkit DI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_appctx, get_config, get_credential_cipher
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
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.artifact import ArtifactService
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.vfs import ReleaseVfsCatalog, VfsProjectionService
from azents.testing.runtime_hooks import TestenvRuntimeHookQAProvider
from azents.utils.appctx import AppContext


def get_toolkit_registry(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    config: Annotated[Config, Depends(get_config)],
    artifact_service: Annotated[ArtifactService, Depends(ArtifactService)],
    github_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
) -> dict[str, ToolkitProvider[Any]]:
    """Create the Toolkit registry.

    :param cipher: Credential encryption/decryption for the MCP toolkit repo
    :param session_manager: DB session manager for MCP toolkits
    :param config: Process-wide application settings
    :param artifact_service: Service that stores MCP binary output
    :param github_runtime: Operation-boundary Platform GitHub App resolver
    :return: Mapping from toolkit_type to ToolkitProvider instances
    """
    registry: dict[str, ToolkitProvider[Any]] = {
        "mcp": McpToolkitProvider(
            connection_repo=MCPOAuthConnectionRepository(cipher=cipher),
            session_manager=session_manager,
            artifact_service=artifact_service,
        ),
        "github": GitHubToolkitProvider(
            platform_runtime=github_runtime,
            session_manager=session_manager,
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


async def get_release_vfs_catalog(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> ReleaseVfsCatalog:
    """Return the process-scoped release VFS catalog."""

    async def create() -> AsyncIterator[ReleaseVfsCatalog]:
        yield ReleaseVfsCatalog()

    return await appctx.get_variable(f"{__name__}.release_vfs_catalog", create)


def get_vfs_projection_service(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ],
    catalog: Annotated[ReleaseVfsCatalog, Depends(get_release_vfs_catalog)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> VfsProjectionService:
    """Create the run VFS projection service."""
    return VfsProjectionService(
        session_manager=session_manager,
        toolkit_registry=toolkit_registry,
        catalog=catalog,
        agent_run_repository=AgentRunRepository(),
        agent_toolkit_repository=AgentToolkitRepository(),
        toolkit_repository=ToolkitRepository(cipher=cipher),
    )


def get_todo_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> TodoToolkitProvider:
    """TodoToolkitProvider dependency."""
    return TodoToolkitProvider(store=TodoStateStore(session_manager=session_manager))


def get_goal_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> GoalToolkitProvider:
    """GoalToolkitProvider dependency."""
    return GoalToolkitProvider(store=GoalStateStore(session_manager=session_manager))


def get_skill_state_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> SkillStateStore:
    """SkillStateStore dependency."""
    return SkillStateStore(session_manager=session_manager)


def get_skill_toolkit_provider(
    skill_store: Annotated[SkillStateStore, Depends(get_skill_state_store)],
) -> SkillToolkitProvider:
    """SkillToolkitProvider dependency without runtime sync support."""
    return SkillToolkitProvider(store=skill_store)
