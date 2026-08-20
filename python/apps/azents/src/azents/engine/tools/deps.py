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
from azents.engine.tools.external_channel import ExternalChannelToolkitProvider
from azents.engine.tools.gcp import GcpToolkitProvider
from azents.engine.tools.github import GitHubToolkitProvider
from azents.engine.tools.goal import GoalStateStore, GoalToolkitProvider
from azents.engine.tools.google_analytics import GoogleAnalyticsToolkitProvider
from azents.engine.tools.kubernetes import KubernetesToolkitProvider
from azents.engine.tools.mcp import McpToolkitProvider
from azents.engine.tools.notion import NotionToolkitProvider
from azents.engine.tools.scheduled import ScheduledToolkitProvider
from azents.engine.tools.sentry import SentryToolkitProvider
from azents.engine.tools.skill import SkillStateStore, SkillToolkitProvider
from azents.engine.tools.todo import TodoStateStore, TodoToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.services.artifact import ArtifactService
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
)
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)
from azents.services.scheduled_task.service import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskService,
)
from azents.services.scheduled_task.terminal import ScheduledTaskTerminalService
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


def get_scheduled_toolkit_provider(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ],
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ],
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)],
    channel_service: Annotated[
        ScheduledTaskChannelService,
        Depends(get_scheduled_task_channel_service),
    ],
    file_transfer_service: Annotated[
        ExternalChannelFileTransferService,
        Depends(),
    ],
) -> ScheduledToolkitProvider:
    """Scheduled Toolkit dependency without ToolkitConfig or credentials."""
    service = ScheduledTaskService(
        repository=task_repository,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        authority_validator=RDBScheduledTaskAuthorityValidator(),
    )
    return ScheduledToolkitProvider(
        session_manager=session_manager,
        service=service,
        terminal_service=ScheduledTaskTerminalService(
            session_manager=session_manager,
            run_repository=run_repository,
            event_repository=EventTranscriptRepository(),
            task_repository=task_repository,
            cycle_repository=cycle_repository,
        ),
        channel_service=channel_service,
        file_transfer_service=file_transfer_service,
        cycle_repository=cycle_repository,
        run_repository=run_repository,
    )


def get_vfs_projection_service(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    toolkit_registry: Annotated[
        dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)
    ],
    catalog: Annotated[ReleaseVfsCatalog, Depends(get_release_vfs_catalog)],
    scheduled_toolkit_provider: Annotated[
        ScheduledToolkitProvider, Depends(get_scheduled_toolkit_provider)
    ],
) -> VfsProjectionService[AsyncSession]:
    """Create the run VFS projection service."""
    return VfsProjectionService(
        session_manager=session_manager,
        toolkit_registry=toolkit_registry,
        catalog=catalog,
        agent_run_repository=AgentRunRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_toolkit_repository=AgentToolkitRepository(),
        toolkit_repository=ToolkitRepository(),
        required_provider_sources={
            scheduled_toolkit_provider.slug: scheduled_toolkit_provider
        },
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


def get_external_channel_toolkit_provider(
    service: Annotated[ExternalChannelActionService, Depends()],
    scheduled_channel_service: Annotated[
        ScheduledTaskChannelService,
        Depends(get_scheduled_task_channel_service),
    ],
    file_transfer_service: Annotated[
        ExternalChannelFileTransferService,
        Depends(),
    ],
) -> ExternalChannelToolkitProvider:
    """External Channel root Toolkit dependency."""
    return ExternalChannelToolkitProvider(
        service=service,
        scheduled_channel_service=scheduled_channel_service,
        file_transfer_service=file_transfer_service,
    )


def get_skill_state_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> SkillStateStore:
    """SkillStateStore dependency."""
    return SkillStateStore(session_manager=session_manager)


def get_skill_toolkit_provider(
    skill_store: Annotated[SkillStateStore, Depends(get_skill_state_store)],
    vfs_projection_service: Annotated[
        VfsProjectionService[AsyncSession],
        Depends(get_vfs_projection_service),
    ],
) -> SkillToolkitProvider:
    """SkillToolkitProvider dependency without runtime sync support."""
    return SkillToolkitProvider(
        store=skill_store,
        projection_service=None,
        vfs_projection_service=vfs_projection_service,
    )
