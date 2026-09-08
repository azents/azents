"""Completed database-only Agent Toolkit authority and OAuth operations."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import (
    DuplicateSlug,
    NotFound,
    ToolkitConfig,
    ToolkitCreate,
    ToolkitUpdate,
)
from azents.repos.toolkit_operations import (
    ToolkitOperationsRepository,
    get_encrypted_toolkit_repository,
    get_mcp_oauth_connection_repository,
)
from azents.repos.toolkit_operations.data import (
    AgentWorkspaceMismatch,
    EffectiveSlugConflict,
    PlatformAuthorityRejected,
    PlatformToolkitAuthority,
)
from azents.repos.toolkit_operations.owned_data import (
    AgentManagementDenied,
    AgentManagementSnapshot,
    AgentOAuthContext,
    OAuthConnectionWrite,
)


@dataclasses.dataclass
class AgentToolkitOperationsRepository:
    """Own completed authority and OAuth transactions for Agent-owned Toolkits."""

    toolkit_repo: Annotated[
        ToolkitRepository, Depends(get_encrypted_toolkit_repository)
    ]
    mcp_oauth_connection_repo: Annotated[
        MCPOAuthConnectionRepository, Depends(get_mcp_oauth_connection_repository)
    ]
    agent_repo: Annotated[AgentRepository, Depends()]
    agent_admin_repo: Annotated[AgentAdminRepository, Depends()]
    github_user_installation_repo: Annotated[
        GithubUserInstallationRepository, Depends()
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    shared_operations: Annotated[ToolkitOperationsRepository, Depends()]

    async def load_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentManagementSnapshot, AgentWorkspaceMismatch | AgentManagementDenied
    ]:
        """Finish all management reads before provider or OAuth presentation."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            if isinstance(access, Failure):
                return Failure(access.error)
            attachments = (
                await self.shared_operations.agent_toolkit_repository.list_by_agent(
                    session,
                    agent_id,
                )
            )
            shared: list[ToolkitConfig] = []
            for attachment in attachments:
                toolkit = await self.toolkit_repo.get_shared_by_id(
                    session,
                    attachment.toolkit_id,
                )
                if toolkit is not None:
                    shared.append(toolkit)
            owned = await self.toolkit_repo.list_by_owner_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
            )
            available = await self.toolkit_repo.list_available_for_workspace_user(
                session,
                workspace_id,
                user_id,
            )
            return Success(
                AgentManagementSnapshot(
                    attachments=attachments,
                    shared=shared,
                    owned=owned,
                    available=available,
                )
            )

    async def get_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        ToolkitConfig, AgentWorkspaceMismatch | AgentManagementDenied | NotFound
    ]:
        """Return a detached Toolkit only for the exact currently authorized owner."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            if isinstance(access, Failure):
                return Failure(access.error)
            toolkit = await self.toolkit_repo.get_agent_owned_by_id(
                session,
                toolkit_id,
                agent_id=agent_id,
            )
            if toolkit is None or toolkit.workspace_id != workspace_id:
                return Failure(NotFound(toolkit_id=toolkit_id))
            return Success(toolkit)

    async def create_agent_owned(
        self,
        agent_id: str,
        create: ToolkitCreate,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> Result[
        ToolkitConfig,
        AgentWorkspaceMismatch
        | AgentManagementDenied
        | DuplicateSlug
        | EffectiveSlugConflict
        | PlatformAuthorityRejected,
    ]:
        """Revalidate owner and namespace; create without a Scope or attachment."""
        if create.owner_agent_id != agent_id or create.workspace_id != workspace_id:
            return Failure(AgentWorkspaceMismatch(agent_id=agent_id))
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            if isinstance(access, Failure):
                return Failure(access.error)
            if platform_authority is not None:
                error = await self.shared_operations.validate_platform_authority(
                    session,
                    platform_authority,
                )
                if error is not None:
                    return Failure(error)
            if await self.toolkit_repo.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id="",
                slug=create.slug,
                enabled=create.enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=create.slug))
            result = await self.toolkit_repo.create(session, create)
            if isinstance(result, Failure):
                return Failure(result.error)
            return Success(result.value)

    async def update_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        update: ToolkitUpdate,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> Result[
        ToolkitConfig,
        AgentWorkspaceMismatch
        | AgentManagementDenied
        | NotFound
        | DuplicateSlug
        | EffectiveSlugConflict
        | PlatformAuthorityRejected,
    ]:
        """Preserve Toolkit-before-Agent locking and final effective slug validation."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(session, toolkit_id)
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            if isinstance(access, Failure):
                return Failure(access.error)
            if platform_authority is not None:
                error = await self.shared_operations.validate_platform_authority(
                    session,
                    platform_authority,
                )
                if error is not None:
                    return Failure(error)
            slug = update.get("slug", toolkit.slug)
            enabled = update.get("enabled", toolkit.enabled)
            if await self.toolkit_repo.has_effective_slug_conflict(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
                slug=slug,
                enabled=enabled,
            ):
                return Failure(EffectiveSlugConflict(slug=slug))
            result = await self.toolkit_repo.update_by_id(session, toolkit_id, update)
            if isinstance(result, Failure):
                return Failure(result.error)
            return Success(result.value)

    async def authorize_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[None, AgentWorkspaceMismatch | AgentManagementDenied]:
        """Verify current Agent Toolkit management authority."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
        match access:
            case Success():
                return Success(None)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

    async def sync_agent_github_installations(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
        platform_app_id: str,
        installations: list[dict[str, object]],
    ) -> Result[None, AgentWorkspaceMismatch | AgentManagementDenied]:
        """Synchronize GitHub installations after current Agent authorization."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.github_user_installation_repo.sync(
                session,
                user_id,
                platform_app_id,
                installations,
            )
        return Success(None)

    async def get_agent_oauth_context(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentOAuthContext,
        AgentWorkspaceMismatch | AgentManagementDenied | NotFound,
    ]:
        """Load one authorized Agent-owned Toolkit and OAuth connection."""
        async with self.session_manager() as session:
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=False,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            toolkit = await self.toolkit_repo.get_agent_owned_by_id(
                session,
                toolkit_id,
                agent_id=agent_id,
            )
            if toolkit is None or toolkit.workspace_id != workspace_id:
                return Failure(NotFound(toolkit_id=toolkit_id))
            connection = await self.mcp_oauth_connection_repo.get_by_toolkit_id(
                session,
                toolkit_id,
            )
        return Success(
            AgentOAuthContext(
                toolkit=toolkit,
                connection=connection,
            )
        )

    async def store_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        connection: OAuthConnectionWrite,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        connected: bool,
    ) -> Result[
        None,
        AgentWorkspaceMismatch | AgentManagementDenied | NotFound,
    ]:
        """Persist OAuth state only while Agent ownership and authority remain valid."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.mcp_oauth_connection_repo.upsert_connected(
                session,
                toolkit_id=toolkit_id,
                issuer=connection.issuer,
                resource=connection.resource,
                server_url=connection.server_url,
                authorization_endpoint=connection.authorization_endpoint,
                token_endpoint=connection.token_endpoint,
                registration_endpoint=connection.registration_endpoint,
                client_id=connection.client_id,
                client_secret=connection.client_secret,
                token_endpoint_auth_method=connection.token_endpoint_auth_method,
                scope=connection.scope,
                access_token=connection.access_token,
                refresh_token=connection.refresh_token,
                expires_at=connection.expires_at,
            )
            if not connected:
                await self.mcp_oauth_connection_repo.mark_reconnect_required(
                    session,
                    toolkit_id=toolkit_id,
                )
        return Success(None)

    async def delete_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        AgentWorkspaceMismatch | AgentManagementDenied | NotFound,
    ]:
        """Delete OAuth state only for the currently authorized Agent-owned Toolkit."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.mcp_oauth_connection_repo.delete_by_toolkit_id(
                session,
                toolkit_id,
            )
        return Success(None)

    async def delete_agent_owned(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        AgentWorkspaceMismatch | AgentManagementDenied | NotFound,
    ]:
        """Delete one ToolkitConfig owned by the exact managed Agent."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repo.get_by_id_for_update(
                session,
                toolkit_id,
            )
            if (
                toolkit is None
                or toolkit.owner_agent_id != agent_id
                or toolkit.workspace_id != workspace_id
            ):
                return Failure(NotFound(toolkit_id=toolkit_id))
            access = await self._get_managed_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
                for_update=True,
            )
            match access:
                case Failure(error):
                    return Failure(error)
                case Success():
                    pass
                case _:
                    assert_never(access)
            await self.toolkit_repo.delete_by_id(session, toolkit_id)
        return Success(None)

    async def _get_managed_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        for_update: bool,
    ) -> Result[Agent, AgentWorkspaceMismatch | AgentManagementDenied]:
        """Load an active Agent and verify Owner or explicit AgentAdmin authority."""
        agent = (
            await self.agent_repo.lock_by_id(session, agent_id)
            if for_update
            else await self.agent_repo.get_by_id(session, agent_id)
        )
        if (
            agent is None
            or agent.workspace_id != workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return Failure(AgentWorkspaceMismatch(agent_id=agent_id))
        if role is WorkspaceUserRole.OWNER:
            return Success(agent)
        if not await self.agent_admin_repo.is_admin(
            session,
            agent_id,
            workspace_user_id,
        ):
            return Failure(AgentManagementDenied(agent_id=agent_id))
        return Success(agent)
