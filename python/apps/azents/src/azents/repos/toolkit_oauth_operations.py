"""Completed shared Toolkit OAuth reads and atomic persistence operations."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.permissions import Permissions, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.account_access import evaluate_active_subject
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.session import SessionRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig
from azents.repos.toolkit_oauth_data import (
    GithubInstallationRecord,
    SharedOAuthContext,
    ToolkitOAuthDenialReason,
    ToolkitOAuthDenied,
    ToolkitOAuthRequester,
)
from azents.repos.toolkit_operations import (
    get_encrypted_toolkit_repository,
    get_mcp_oauth_connection_repository,
)
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class ToolkitOAuthOperationRepository:
    """Own original atomic groups and final current admission after external work."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    toolkit_repository: Annotated[
        ToolkitRepository, Depends(get_encrypted_toolkit_repository)
    ]
    connection_repository: Annotated[
        MCPOAuthConnectionRepository, Depends(get_mcp_oauth_connection_repository)
    ]
    installation_repository: Annotated[
        GithubUserInstallationRepository, Depends(GithubUserInstallationRepository)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    session_repository: Annotated[SessionRepository, Depends(SessionRepository)]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def sync_installations(
        self,
        *,
        requester: ToolkitOAuthRequester,
        platform_app_id: str,
        installations: tuple[GithubInstallationRecord, ...],
    ) -> Result[None, ToolkitOAuthDenied]:
        """Revalidate admission and complete the ordered full upsert/prune group."""
        rows = [
            GitHubInstallationSnapshot(
                installation_id=record.installation_id,
                app_id=None,
                account_login=record.account_login,
                account_type=record.account_type,
                account_avatar_url=record.account_avatar_url,
            )
            for record in installations
        ]
        async with self.session_manager() as session:
            denial = await self._evaluate_write_authority(session, requester)
            if denial is not None:
                return Failure(denial)
            await self.installation_repository.sync(
                session, requester.user_id, platform_app_id, rows
            )
            return Success(None)

    async def read_shared_context(self, *, toolkit_id: str) -> SharedOAuthContext:
        """Read Toolkit then connection even when the Toolkit lookup is absent."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repository.get_shared_by_id(
                session, toolkit_id
            )
            connection = await self.connection_repository.get_by_toolkit_id(
                session, toolkit_id
            )
            return SharedOAuthContext(toolkit=toolkit, connection=connection)

    async def store_shared_connection(
        self,
        *,
        requester: ToolkitOAuthRequester,
        toolkit_id: str,
        connection: OAuthConnectionWrite,
    ) -> Result[None, ToolkitOAuthDenied]:
        """Repeat current admission and shared identity before the full upsert."""
        async with self.session_manager() as session:
            denial = await self._evaluate_write_authority(session, requester)
            if denial is not None:
                return Failure(denial)
            toolkit = await self.toolkit_repository.get_shared_by_id(
                session, toolkit_id
            )
            if toolkit is None or toolkit.workspace_id != requester.workspace_id:
                return Failure(
                    ToolkitOAuthDenied(
                        reason=ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND,
                        subject_status=None,
                    )
                )
            await self.connection_repository.upsert_connected(
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
            return Success(None)

    async def delete_shared_connection(
        self, *, workspace_id: str, toolkit_id: str
    ) -> Result[None, ToolkitOAuthDenied]:
        """Keep exact shared Toolkit eligibility and idempotent delete together."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repository.get_shared_by_id(
                session, toolkit_id
            )
            if toolkit is None or toolkit.workspace_id != workspace_id:
                return Failure(
                    ToolkitOAuthDenied(
                        reason=ToolkitOAuthDenialReason.TOOLKIT_NOT_FOUND,
                        subject_status=None,
                    )
                )
            await self.connection_repository.delete_by_toolkit_id(session, toolkit_id)
            return Success(None)

    async def read_shared_toolkit(
        self, *, workspace_id: str, toolkit_id: str
    ) -> ToolkitConfig | None:
        """Return the detached exact shared Workspace Toolkit or normal absence."""
        async with self.session_manager() as session:
            toolkit = await self.toolkit_repository.get_shared_by_id(
                session, toolkit_id
            )
            if toolkit is None or toolkit.workspace_id != workspace_id:
                return None
            return toolkit

    async def read_optional_shared_toolkit(
        self, *, workspace_id: str, toolkit_id: str | None
    ) -> ToolkitConfig | None:
        """Resolve an optional saved snapshot without opening a scope for None."""
        if toolkit_id is None:
            return None
        return await self.read_shared_toolkit(
            workspace_id=workspace_id, toolkit_id=toolkit_id
        )

    async def _evaluate_write_authority(
        self, session: ReadSession, requester: ToolkitOAuthRequester
    ) -> ToolkitOAuthDenied | None:
        """Repeat existing admission, without locking or commit-time serialization."""
        subject_status = await evaluate_active_subject(
            session,
            user_id=requester.user_id,
            session_id=requester.session_id,
            user_repository=self.user_repository,
            session_repository=self.session_repository,
        )
        if subject_status is not ActiveAccountSubjectStatus.ACTIVE:
            return ToolkitOAuthDenied(
                reason=ToolkitOAuthDenialReason.INACTIVE_SUBJECT,
                subject_status=subject_status,
            )
        workspace = await self.workspace_repository.get_by_id(
            session, requester.workspace_id
        )
        if workspace is None:
            return ToolkitOAuthDenied(
                reason=ToolkitOAuthDenialReason.WORKSPACE_NOT_FOUND,
                subject_status=None,
            )
        member = await self.workspace_user_repository.get_by_workspace_and_user(
            session, requester.workspace_id, requester.user_id
        )
        if member is None:
            return ToolkitOAuthDenied(
                reason=ToolkitOAuthDenialReason.MEMBERSHIP_REQUIRED,
                subject_status=None,
            )
        if not has_permission(
            get_permissions_for_role(member.role), Permissions.TOOLKITS_WRITE
        ):
            return ToolkitOAuthDenied(
                reason=ToolkitOAuthDenialReason.WRITE_PERMISSION_REQUIRED,
                subject_status=None,
            )
        return None
