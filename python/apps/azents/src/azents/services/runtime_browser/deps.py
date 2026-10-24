"""FastAPI composition for the public Session Browser command surface."""

import time
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from azents_runtime_control.grpc_browser_source_client import GrpcBrowserSourceClient
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.browser_configuration import BrowserConfigurationRepository
from azents.repos.runtime_browser_authority_read import (
    RuntimeBrowserAuthorityReadRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session import SessionRepository
from azents.repos.session_working_folder_binding import (
    SessionWorkingFolderBindingRepository,
)
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.deps import (
    get_api_runtime_browser_source_client,
    get_runtime_coordination_store,
    get_runtime_runner_operation_client,
)
from azents.services.runtime_browser.authority import (
    DatabaseRuntimeBrowserAuthorityResolver,
    DatabaseRuntimeBrowserStreamScopeValidator,
)
from azents.services.runtime_browser.service import RuntimeBrowserService
from azents.services.runtime_browser.socket import RuntimeBrowserSocketService
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)


def get_runtime_browser_authority_resolver(
    authority_repository: Annotated[
        RuntimeBrowserAuthorityReadRepository,
        Depends(RuntimeBrowserAuthorityReadRepository),
    ],
    runtime_coordination: Annotated[
        RuntimeCoordinationStore, Depends(get_runtime_coordination_store)
    ],
    working_folder_service: Annotated[
        SessionWorkingFolderBindingService, Depends(SessionWorkingFolderBindingService)
    ],
    browser_configuration: Annotated[
        BrowserConfigurationRepository, Depends(BrowserConfigurationRepository)
    ],
) -> DatabaseRuntimeBrowserAuthorityResolver:
    return DatabaseRuntimeBrowserAuthorityResolver(
        authority_repository=authority_repository,
        runtime_coordination=runtime_coordination,
        working_folder_service=working_folder_service,
        browser_configuration=browser_configuration,
    )


def get_runtime_browser_service(
    authority_resolver: Annotated[
        DatabaseRuntimeBrowserAuthorityResolver,
        Depends(get_runtime_browser_authority_resolver),
    ],
    runner_operations: Annotated[
        RuntimeRunnerOperationClient, Depends(get_runtime_runner_operation_client)
    ],
) -> RuntimeBrowserService:
    return RuntimeBrowserService(
        authority_resolver=authority_resolver,
        runner_operations=runner_operations,
        clock=_utc_now,
    )


def get_runtime_browser_stream_scope_validator(
    authority_repository: Annotated[
        RuntimeBrowserAuthorityReadRepository,
        Depends(RuntimeBrowserAuthorityReadRepository),
    ],
    authority_resolver: Annotated[
        DatabaseRuntimeBrowserAuthorityResolver,
        Depends(get_runtime_browser_authority_resolver),
    ],
    runner_operations: Annotated[
        RuntimeRunnerOperationClient, Depends(get_runtime_runner_operation_client)
    ],
) -> DatabaseRuntimeBrowserStreamScopeValidator:
    return DatabaseRuntimeBrowserStreamScopeValidator(
        authority_repository=authority_repository,
        authority_resolver=authority_resolver,
        runner_operations=runner_operations,
        clock=_utc_now,
    )


def build_runtime_browser_stream_scope_validator(
    *,
    session_manager: SessionManager[WriteSession],
    read_session_manager: SessionManager[ReadSession],
    runtime_coordination: RuntimeCoordinationStore,
    runner_operations: RuntimeRunnerOperationClient,
) -> DatabaseRuntimeBrowserStreamScopeValidator:
    """Compose the same current authority for the Control process without DI."""
    agents = AgentRepository()
    sessions = AgentSessionRepository()
    repository = RuntimeBrowserAuthorityReadRepository(
        session_manager=read_session_manager,
        user_repository=UserRepository(),
        authentication_session_repository=SessionRepository(),
        workspace_repository=WorkspaceRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        agent_repository=agents,
        agent_admin_repository=AgentAdminRepository(),
        agent_session_repository=sessions,
        runtime_repository=AgentRuntimeRepository(),
        profile_repository=RuntimeProfileRepository(),
    )
    folders = SessionWorkingFolderBindingService(
        repository=SessionWorkingFolderBindingRepository(
            agent_repository=agents,
            agent_session_repository=sessions,
            session_manager=session_manager,
            read_session_manager=read_session_manager,
        )
    )
    return DatabaseRuntimeBrowserStreamScopeValidator(
        authority_repository=repository,
        authority_resolver=DatabaseRuntimeBrowserAuthorityResolver(
            repository,
            runtime_coordination,
            folders,
            BrowserConfigurationRepository(
                read_session_manager, session_manager, RuntimeProfileRepository()
            ),
        ),
        runner_operations=runner_operations,
        clock=_utc_now,
    )


def get_runtime_browser_socket_service(
    scope_validator: Annotated[
        DatabaseRuntimeBrowserStreamScopeValidator,
        Depends(get_runtime_browser_stream_scope_validator),
    ],
    source_client: Annotated[
        GrpcBrowserSourceClient | None, Depends(get_api_runtime_browser_source_client)
    ],
) -> RuntimeBrowserSocketService:
    return RuntimeBrowserSocketService(
        scope_validator=scope_validator,
        source_client=source_client,
        clock=_utc_now,
        monotonic_clock=time.monotonic,
    )


def get_runtime_browser_web_origin(
    config: Annotated[Config, Depends(get_config)],
) -> str:
    if config.web_url is None:
        raise ValueError("Main Web origin is required for Browser WebSockets")
    parsed = urlsplit(config.web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Main Web origin is required for Browser WebSockets")
    return f"{parsed.scheme}://{parsed.netloc}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
