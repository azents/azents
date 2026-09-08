"""Repository-owned Toolkit database operations."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import ToolkitScopeType
from azents.core.system_setting import (
    SystemSettingFieldSource,
    SystemSettingSection,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnectionSummary
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import (
    AgentToolkitRepository,
    ToolkitRepository,
    ToolkitScopeRepository,
)
from azents.repos.toolkit.data import (
    AgentToolkit,
    AgentToolkitCreate,
    DuplicateAgentToolkit,
    DuplicateScope,
    DuplicateSlug,
    NotFound,
    ScopeNotFound,
    ToolkitConfig,
    ToolkitCreate,
    ToolkitScope,
    ToolkitScopeCreate,
    ToolkitUpdate,
)
from azents.repos.workspace_user import WorkspaceUserRepository

from .data import (
    AgentToolkitMismatch,
    AgentWorkspaceMismatch,
    EffectiveSlugConflict,
    PlatformAuthorityRejected,
    PlatformToolkitAuthority,
    ScopeToolkitMismatch,
    ToolkitUnavailable,
    ToolkitWithOAuth,
    ToolkitWorkspaceMismatch,
)

_PLATFORM_NOT_CONFIGURED = "GitHub Platform App is not configured."
_PLATFORM_RECONNECT_REQUIRED = "GitHub Platform App reconnect is required."
_INSTALLATION_NOT_ACCESSIBLE = "GitHub installation is not accessible to this user."

ToolkitReadError = NotFound | ToolkitWorkspaceMismatch
ToolkitMutationError = (
    ToolkitReadError | DuplicateSlug | PlatformAuthorityRejected | EffectiveSlugConflict
)
ToolkitScopeMutationError = ToolkitReadError | DuplicateScope
ToolkitScopeDeleteError = ToolkitReadError | ScopeNotFound | ScopeToolkitMismatch
AgentToolkitListError = AgentWorkspaceMismatch
AgentToolkitAttachError = (
    NotFound
    | ToolkitWorkspaceMismatch
    | ToolkitUnavailable
    | DuplicateAgentToolkit
    | AgentWorkspaceMismatch
    | EffectiveSlugConflict
)
AgentToolkitDetachError = ScopeNotFound | AgentToolkitMismatch | AgentWorkspaceMismatch


def get_encrypted_toolkit_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ToolkitRepository:
    """Construct a Toolkit repository with credential encryption."""
    return ToolkitRepository(cipher=cipher)


def get_mcp_oauth_connection_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> MCPOAuthConnectionRepository:
    """Construct an MCP OAuth repository with credential encryption."""
    return MCPOAuthConnectionRepository(cipher=cipher)


@dataclasses.dataclass
class ToolkitOperationsRepository:
    """Compose complete Toolkit transactions from narrow repositories."""

    toolkit_repository: Annotated[
        ToolkitRepository,
        Depends(get_encrypted_toolkit_repository),
    ]
    scope_repository: Annotated[
        ToolkitScopeRepository,
        Depends(ToolkitScopeRepository),
    ]
    agent_toolkit_repository: Annotated[
        AgentToolkitRepository,
        Depends(AgentToolkitRepository),
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    github_installation_repository: Annotated[
        GithubUserInstallationRepository,
        Depends(GithubUserInstallationRepository),
    ]
    oauth_connection_repository: Annotated[
        MCPOAuthConnectionRepository,
        Depends(get_mcp_oauth_connection_repository),
    ]
    system_setting_repository: Annotated[
        SystemSettingRepository,
        Depends(SystemSettingRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def create(
        self,
        create: ToolkitCreate,
        *,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> Result[ToolkitWithOAuth, DuplicateSlug | PlatformAuthorityRejected]:
        """Atomically create a Toolkit, Workspace scope, and response snapshot."""
        async with self.session_manager() as session:
            if platform_authority is not None:
                authority_error = await self.validate_platform_authority(
                    session,
                    platform_authority,
                )
                if authority_error is not None:
                    return Failure(authority_error)
            create_result = await self.toolkit_repository.create(session, create)
            if isinstance(create_result, Failure):
                return Failure(create_result.error)
            scope_result = await self.scope_repository.create(
                session,
                ToolkitScopeCreate(
                    toolkit_id=create_result.value.id,
                    scope_type=ToolkitScopeType.WORKSPACE,
                    scope_id=create.workspace_id,
                ),
            )
            if isinstance(scope_result, Failure):
                raise RuntimeError("Initial Toolkit Workspace scope already exists.")
            summary = await self.oauth_connection_repository.get_summary_by_toolkit_id(
                session,
                create_result.value.id,
            )
            return Success(
                ToolkitWithOAuth(
                    toolkit=create_result.value,
                    oauth_connection=summary,
                )
            )

    async def list_by_workspace(self, workspace_id: str) -> list[ToolkitWithOAuth]:
        """List Workspace Toolkits and OAuth summaries in one transaction."""
        async with self.session_manager() as session:
            toolkits = await self.toolkit_repository.list_by_workspace(
                session,
                workspace_id,
            )
            summaries = (
                await self.oauth_connection_repository.list_summaries_by_toolkit_ids(
                    session,
                    [toolkit.id for toolkit in toolkits],
                )
            )
            return [
                ToolkitWithOAuth(
                    toolkit=toolkit,
                    oauth_connection=summaries.get(toolkit.id),
                )
                for toolkit in toolkits
            ]

    async def get_by_id(
        self,
        toolkit_id: str,
        *,
        workspace_id: str,
    ) -> Result[ToolkitWithOAuth, ToolkitReadError]:
        """Load one Workspace Toolkit and OAuth summary in one transaction."""
        async with self.session_manager() as session:
            toolkit_result = await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )
            if isinstance(toolkit_result, Failure):
                return Failure(toolkit_result.error)
            summary = await self.oauth_connection_repository.get_summary_by_toolkit_id(
                session,
                toolkit_id,
            )
            return Success(
                ToolkitWithOAuth(
                    toolkit=toolkit_result.value,
                    oauth_connection=summary,
                )
            )

    async def load_update_context(
        self,
        toolkit_id: str,
        *,
        workspace_id: str,
    ) -> Result[ToolkitConfig, ToolkitReadError]:
        """Load the detached Toolkit snapshot used for external preparation."""
        async with self.session_manager() as session:
            return await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )

    async def update(
        self,
        toolkit_id: str,
        update: ToolkitUpdate,
        *,
        workspace_id: str,
        expected_toolkit_type: str,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> Result[ToolkitConfig, ToolkitMutationError]:
        """Revalidate current authority and update one Toolkit."""
        async with self.session_manager() as session:
            if platform_authority is not None:
                authority_error = await self.validate_platform_authority(
                    session,
                    platform_authority,
                )
                if authority_error is not None:
                    return Failure(authority_error)
            toolkit = await self.toolkit_repository.get_shared_by_id_for_update(
                session, toolkit_id
            )
            if toolkit is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            if toolkit.workspace_id != workspace_id:
                return Failure(ToolkitWorkspaceMismatch(toolkit_id=toolkit_id))
            if toolkit.toolkit_type != expected_toolkit_type:
                return Failure(NotFound(toolkit_id=toolkit_id))
            candidate_slug = update.get("slug", toolkit.slug)
            candidate_enabled = update.get("enabled", toolkit.enabled)
            if candidate_slug != toolkit.slug or candidate_enabled != toolkit.enabled:
                agent_ids = (
                    await self.agent_toolkit_repository.list_agent_ids_by_toolkit(
                        session, toolkit_id
                    )
                )
                for agent_id in agent_ids:
                    await self.agent_repository.lock_by_id(session, agent_id)
                for agent_id in agent_ids:
                    if await self.toolkit_repository.has_effective_slug_conflict(
                        session,
                        agent_id=agent_id,
                        workspace_id=workspace_id,
                        toolkit_id=toolkit_id,
                        slug=candidate_slug,
                        enabled=candidate_enabled,
                    ):
                        return Failure(EffectiveSlugConflict(slug=candidate_slug))
            update_result = await self.toolkit_repository.update_by_id(
                session,
                toolkit_id,
                update,
            )
            if isinstance(update_result, Failure):
                return Failure(update_result.error)
            return Success(update_result.value)

    async def delete(
        self,
        toolkit_id: str,
        *,
        workspace_id: str,
    ) -> Result[None, ToolkitReadError]:
        """Revalidate Workspace ownership and delete one Toolkit."""
        async with self.session_manager() as session:
            toolkit_result = await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )
            if isinstance(toolkit_result, Failure):
                return Failure(toolkit_result.error)
            await self.toolkit_repository.delete_by_id(session, toolkit_id)
            return Success(None)

    async def create_scope(
        self,
        *,
        toolkit_id: str,
        workspace_id: str,
    ) -> Result[ToolkitScope, ToolkitScopeMutationError]:
        """Revalidate Toolkit ownership and create its Workspace scope."""
        async with self.session_manager() as session:
            toolkit_result = await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )
            if isinstance(toolkit_result, Failure):
                return Failure(toolkit_result.error)
            create_result = await self.scope_repository.create(
                session,
                ToolkitScopeCreate(
                    toolkit_id=toolkit_id,
                    scope_type=ToolkitScopeType.WORKSPACE,
                    scope_id=workspace_id,
                ),
            )
            if isinstance(create_result, Failure):
                return Failure(create_result.error)
            return Success(create_result.value)

    async def list_scopes(
        self,
        toolkit_id: str,
        *,
        workspace_id: str,
    ) -> Result[list[ToolkitScope], ToolkitReadError]:
        """List scopes only after validating current Toolkit ownership."""
        async with self.session_manager() as session:
            toolkit_result = await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )
            if isinstance(toolkit_result, Failure):
                return Failure(toolkit_result.error)
            return Success(
                await self.scope_repository.list_by_toolkit(session, toolkit_id)
            )

    async def delete_scope(
        self,
        scope_id: str,
        *,
        toolkit_id: str,
        workspace_id: str,
    ) -> Result[None, ToolkitScopeDeleteError]:
        """Revalidate Toolkit and Scope identity before deleting the Scope."""
        async with self.session_manager() as session:
            toolkit_result = await self._get_workspace_toolkit(
                session,
                toolkit_id=toolkit_id,
                workspace_id=workspace_id,
            )
            if isinstance(toolkit_result, Failure):
                return Failure(toolkit_result.error)
            scope = await self.scope_repository.get_by_id(session, scope_id)
            if scope is None:
                return Failure(ScopeNotFound(scope_id=scope_id))
            if scope.toolkit_id != toolkit_id:
                return Failure(ScopeToolkitMismatch(scope_id=scope_id))
            await self.scope_repository.delete_by_id(session, scope_id)
            return Success(None)

    async def list_available(
        self,
        workspace_id: str,
        user_id: str,
    ) -> list[ToolkitWithOAuth]:
        """List currently available Toolkits and OAuth summaries."""
        async with self.session_manager() as session:
            toolkits = await self.toolkit_repository.list_available_for_workspace_user(
                session,
                workspace_id,
                user_id,
            )
            summaries = (
                await self.oauth_connection_repository.list_summaries_by_toolkit_ids(
                    session,
                    [toolkit.id for toolkit in toolkits],
                )
            )
            return [
                ToolkitWithOAuth(
                    toolkit=toolkit,
                    oauth_connection=summaries.get(toolkit.id),
                )
                for toolkit in toolkits
            ]

    async def list_agent_toolkits(
        self,
        agent_id: str,
        *,
        workspace_id: str,
    ) -> Result[list[AgentToolkit], AgentToolkitListError]:
        """List Agent Toolkit attachments after current Workspace validation."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(AgentWorkspaceMismatch(agent_id=agent_id))
            return Success(
                await self.agent_toolkit_repository.list_by_agent(session, agent_id)
            )

    async def attach_to_agent(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        user_id: str,
    ) -> Result[AgentToolkit, AgentToolkitAttachError]:
        """Atomically revalidate availability and attach one Toolkit."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repository.get_shared_by_id_for_update(
                session, toolkit_id
            )
            if toolkit is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            if toolkit.workspace_id != workspace_id:
                return Failure(ToolkitWorkspaceMismatch(toolkit_id=toolkit_id))
            agent = await self.agent_repository.lock_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(AgentWorkspaceMismatch(agent_id=agent_id))
            available = await self.toolkit_repository.list_available_for_workspace_user(
                session,
                workspace_id,
                user_id,
            )
            if toolkit_id not in {item.id for item in available}:
                return Failure(ToolkitUnavailable(toolkit_id=toolkit_id))
            if await self.toolkit_repository.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
                slug=toolkit.slug,
                enabled=toolkit.enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=toolkit.slug))
            create_result = await self.agent_toolkit_repository.create(
                session,
                AgentToolkitCreate(
                    agent_id=agent_id,
                    toolkit_id=toolkit_id,
                    toolkit_type=toolkit.toolkit_type,
                ),
            )
            if isinstance(create_result, Failure):
                return Failure(create_result.error)
            return Success(create_result.value)

    async def detach_from_agent(
        self,
        agent_toolkit_id: str,
        *,
        agent_id: str,
        workspace_id: str,
    ) -> Result[None, AgentToolkitDetachError]:
        """Revalidate Agent and attachment identity before detaching."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(AgentWorkspaceMismatch(agent_id=agent_id))
            agent_toolkit = await self.agent_toolkit_repository.get_by_id(
                session,
                agent_toolkit_id,
            )
            if agent_toolkit is None:
                return Failure(ScopeNotFound(scope_id=agent_toolkit_id))
            if agent_toolkit.agent_id != agent_id:
                return Failure(AgentToolkitMismatch(agent_toolkit_id=agent_toolkit_id))
            await self.agent_toolkit_repository.delete_by_id(
                session,
                agent_toolkit_id,
            )
            return Success(None)

    async def get_oauth_summary(
        self,
        toolkit_id: str,
    ) -> MCPOAuthConnectionSummary | None:
        """Load one OAuth summary through a completed repository operation."""
        async with self.session_manager() as session:
            return await self.oauth_connection_repository.get_summary_by_toolkit_id(
                session,
                toolkit_id,
            )

    async def _get_workspace_toolkit(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        workspace_id: str,
    ) -> Result[ToolkitConfig, ToolkitReadError]:
        toolkit = await self.toolkit_repository.get_shared_by_id(session, toolkit_id)
        if toolkit is None:
            return Failure(NotFound(toolkit_id=toolkit_id))
        if toolkit.workspace_id != workspace_id:
            return Failure(ToolkitWorkspaceMismatch(toolkit_id=toolkit_id))
        return Success(toolkit)

    async def validate_platform_authority(
        self,
        session: AsyncSession,
        authority: PlatformToolkitAuthority,
    ) -> PlatformAuthorityRejected | None:
        if authority.app_id_source is SystemSettingFieldSource.ADMIN:
            current = await self.system_setting_repository.get_current(
                session,
                section=SystemSettingSection.PLATFORM_GITHUB_APP,
            )
            if current is None:
                return PlatformAuthorityRejected(_PLATFORM_NOT_CONFIGURED)
            current_app_id = current.config.get("app_id")
            if current_app_id != authority.app_id:
                return PlatformAuthorityRejected(_PLATFORM_RECONNECT_REQUIRED)
        elif authority.app_id_source is not SystemSettingFieldSource.ENVIRONMENT:
            return PlatformAuthorityRejected(_PLATFORM_NOT_CONFIGURED)

        accessible_ids = (
            await self.github_installation_repository.list_accessible_installation_ids(
                session,
                user_id=authority.user_id,
                platform_app_id=authority.app_id,
                installation_ids=authority.installation_ids,
            )
        )
        if accessible_ids != authority.installation_ids:
            return PlatformAuthorityRejected(_INSTALLATION_NOT_ACCESSIBLE)
        return None
