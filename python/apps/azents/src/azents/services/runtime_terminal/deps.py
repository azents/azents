"""FastAPI composition for the Public Runtime Terminal service."""

import secrets
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.deps import (
    get_runtime_coordination_store,
    get_runtime_terminal_control_dispatcher,
    get_runtime_terminal_coordination_store,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_dispatcher import (
    RuntimeTerminalControlDispatcherAdapter,
)
from azents.services.runtime_terminal.authority import (
    DatabaseRuntimeTerminalAuthorityResolver,
)
from azents.services.runtime_terminal.service import RuntimeTerminalService
from azents.services.runtime_terminal.ticket import HmacRuntimeTerminalTicketCodec
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)
from azents.services.terminal_policy.service import TerminalPolicyResolver


def get_runtime_terminal_authority_resolver(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    user_repository: Annotated[UserRepository, Depends(UserRepository)],
    authentication_session_repository: Annotated[
        SessionRepository,
        Depends(SessionRepository),
    ],
    workspace_repository: Annotated[
        WorkspaceRepository,
        Depends(WorkspaceRepository),
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ],
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ],
    runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
    ],
    profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ],
    runtime_coordination: Annotated[
        RuntimeCoordinationStore,
        Depends(get_runtime_coordination_store),
    ],
    working_folder_service: Annotated[
        SessionWorkingFolderBindingService,
        Depends(SessionWorkingFolderBindingService),
    ],
) -> DatabaseRuntimeTerminalAuthorityResolver:
    """Return the deployment-wired current Terminal authority resolver."""
    return DatabaseRuntimeTerminalAuthorityResolver(
        session_manager=session_manager,
        user_repository=user_repository,
        authentication_session_repository=authentication_session_repository,
        workspace_repository=workspace_repository,
        workspace_user_repository=workspace_user_repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        agent_session_repository=agent_session_repository,
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        runtime_coordination=runtime_coordination,
        working_folder_service=working_folder_service,
        policy_resolver=TerminalPolicyResolver(),
    )


def get_runtime_terminal_service(
    config: Annotated[Config, Depends(get_config)],
    authority_resolver: Annotated[
        DatabaseRuntimeTerminalAuthorityResolver,
        Depends(get_runtime_terminal_authority_resolver),
    ],
    terminal_coordination: Annotated[
        RuntimeTerminalCoordinationStore,
        Depends(get_runtime_terminal_coordination_store),
    ],
    dispatcher: Annotated[
        RuntimeTerminalControlDispatcherAdapter,
        Depends(get_runtime_terminal_control_dispatcher),
    ],
) -> RuntimeTerminalService:
    """Return the deployment-wired Public Runtime Terminal service."""
    return RuntimeTerminalService(
        authority_resolver=authority_resolver,
        coordination=terminal_coordination,
        dispatcher=dispatcher,
        ticket_codec=HmacRuntimeTerminalTicketCodec(
            config.credential_encryption.key.encode()
        ),
        clock=_utc_now,
        ticket_id_factory=_new_id,
        terminal_id_factory=_new_id,
        stream_nonce_factory=lambda: secrets.token_urlsafe(32),
    )


def get_runtime_terminal_web_origin(
    config: Annotated[Config, Depends(get_config)],
) -> str:
    """Return the exact configured Main Web origin for Terminal WebSockets."""
    parsed = urlsplit(config.web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Main Web URL is required for Runtime Terminal")
    return f"{parsed.scheme}://{parsed.netloc}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid7().hex
