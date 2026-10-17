"""Current Team Session Toolkit delegation and exact credential failure writes."""

import dataclasses
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus
from azents.core.github_user_oauth import (
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.core.github_user_runtime import (
    GitHubUserExecutionContext,
    GitHubUserExecutionState,
)
from azents.core.personal_toolkit_runtime import PersonalToolkitExecutionDenied
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.payloads import connection_from
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.personal import PersonalToolkitRepository
from azents.repos.toolkit.personal_runtime import PersonalToolkitRuntimeRepository
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_operations import get_encrypted_toolkit_repository


def _current_delegation(
    context: GitHubUserExecutionContext,
) -> sa.Select[tuple[RDBToolkitConfig]]:
    """Use canonical Session, Agent and current shared attachment/owned relation."""
    attached = sa.exists().where(
        RDBAgentToolkit.agent_id == context.agent_id,
        RDBAgentToolkit.toolkit_id == context.toolkit_id,
    )
    return (
        sa.select(RDBToolkitConfig)
        .join(RDBAgent, RDBAgent.id == context.agent_id)
        .join(RDBAgentSession, RDBAgentSession.id == context.session_id)
        .where(
            RDBToolkitConfig.id == context.toolkit_id,
            RDBToolkitConfig.workspace_id == context.workspace_id,
            RDBToolkitConfig.toolkit_type == "github",
            RDBToolkitConfig.enabled.is_(True),
            RDBAgent.workspace_id == context.workspace_id,
            RDBAgent.enabled.is_(True),
            RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            RDBAgentSession.workspace_id == context.workspace_id,
            RDBAgentSession.agent_id == context.agent_id,
            RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            sa.or_(
                RDBToolkitConfig.owner_agent_id == context.agent_id,
                sa.and_(RDBToolkitConfig.owner_agent_id.is_(None), attached),
            ),
        )
        .execution_options(populate_existing=True)
    )


@dataclasses.dataclass(frozen=True)
class GitHubUserRuntimeOperationRepository:
    """Finish credential admission before MCP/Runtime effects without manager state."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    toolkit_repository: Annotated[
        ToolkitRepository, Depends(get_encrypted_toolkit_repository)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    async def _state(
        self, session: WriteSession, context: GitHubUserExecutionContext
    ) -> GitHubUserExecutionState | None:
        if context.personal_target is not None:
            target = context.personal_target
            if (
                target.execution_owner.session_id != context.session_id
                or target.workspace_id != context.workspace_id
                or target.agent_id != context.agent_id
                or target.toolkit_id != context.toolkit_id
            ):
                return None
            personal = PersonalToolkitRuntimeRepository(
                self.session_manager,
                PersonalToolkitRepository(self.cipher),
                ToolkitNamespaceRepository(),
                None,
            )
            try:
                toolkit = await personal.admit_in_session(session, target)
            except PersonalToolkitExecutionDenied:
                return None
            if toolkit.toolkit_type != "github":
                return None
        else:
            row = await session.read_session.scalar(_current_delegation(context))
            if row is None:
                return None
            toolkit = await self.toolkit_repository.get_by_id(
                session, context.toolkit_id
            )
            if toolkit is None:
                return None
        connection = await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection)
            .where(RDBGitHubUserConnection.toolkit_id == context.toolkit_id)
            .execution_options(populate_existing=True)
        )
        if connection is None:
            return None
        return GitHubUserExecutionState(
            toolkit=toolkit, connection=connection_from(connection, self.cipher)
        )

    async def load(
        self, context: GitHubUserExecutionContext
    ) -> GitHubUserExecutionState:
        """Read only currently delegated active credentials, never review candidates."""
        async with self.session_manager() as session:
            current = await self._state(session, context)
            if current is None:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.AUTHORITY,
                    "Current GitHub user Toolkit authorization is unavailable.",
                )
            return current

    async def mark_authentication_failed(
        self, context: GitHubUserExecutionContext, *, connection_id: str
    ) -> None:
        """A late 401 can affect only its admitted connection in the same context."""
        async with self.session_manager() as session:
            state = await self._state(session, context)
            if state is None or state.connection.id != connection_id:
                return
            await session.write_session.execute(
                sa.update(RDBGitHubUserConnection)
                .where(
                    RDBGitHubUserConnection.toolkit_id == context.toolkit_id,
                    RDBGitHubUserConnection.id == connection_id,
                )
                .values(
                    status=GitHubUserConnectionStatus.RECONNECT_REQUIRED,
                    failure_reason="authentication_failed",
                )
            )
