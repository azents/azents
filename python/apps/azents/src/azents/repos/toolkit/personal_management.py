"""Completed exact-account transactions for personal Toolkit management."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.github_user_oauth import (
    GitHubUserConnectionSummary,
    GitHubUserRevocation,
)
from azents.core.personal_toolkit import (
    PersonalToolkitAccessMutation,
    PersonalToolkitAgentIneligible,
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
    PersonalToolkitNotFound,
    PersonalToolkitProviderAuthorityDenied,
)
from azents.core.system_setting import SystemSettingSection
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.toolkit_identifiers import resolve_default_toolkit_slug
from azents.core.toolkit_ownership import PersonalToolkitAccess
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.account_access import evaluate_active_subject
from azents.repos.github_user_oauth.guards import (
    capture_and_clear_user_tokens,
    read_summary,
)
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import (
    MCPOAuthConnection,
    MCPOAuthConnectionSummary,
)
from azents.repos.session import SessionRepository
from azents.repos.toolkit.data import (
    PersonalToolkitConfig,
    ToolkitCreation,
    ToolkitUpdate,
)
from azents.repos.toolkit.personal import (
    PersonalToolkitRepository,
    eligible_personal_agent_ids,
)
from azents.repos.toolkit_operations import (
    ToolkitOperationsRepository,
    get_mcp_oauth_connection_repository,
)
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.repos.toolkit_operations.github_user_guard import (
    guard_locked_user_registration_update,
)
from azents.repos.toolkit_operations.owned_data import OAuthConnectionWrite
from azents.repos.user import UserRepository


@dataclasses.dataclass(frozen=True)
class PersonalToolkitManagementSnapshot:
    """Detached canonical connection and redacted Provider/access metadata."""

    toolkit: PersonalToolkitConfig = dataclasses.field(repr=False)
    access: PersonalToolkitAccess
    oauth_connection: MCPOAuthConnectionSummary | None
    github_user_connection: GitHubUserConnectionSummary | None


@dataclasses.dataclass(frozen=True)
class PersonalToolkitOAuthContext:
    """Authorized canonical personal connection and exact MCP grant snapshot."""

    toolkit: PersonalToolkitConfig = dataclasses.field(repr=False)
    connection: MCPOAuthConnection | None = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class PersonalToolkitEligibleAgent:
    """An ordinary-access Agent grouped by its canonical Workspace identity."""

    agent_id: str
    agent_name: str
    workspace_id: str
    workspace_name: str
    workspace_handle: str


@dataclasses.dataclass(frozen=True)
class PersonalToolkitPlatformTestAuthority:
    """Exact registration and selected installation authority for a Provider test."""

    authority: PlatformToolkitAuthority
    effective_generation: str


def get_personal_toolkit_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> PersonalToolkitRepository:
    """Bind common credential encryption without changing Provider storage."""
    return PersonalToolkitRepository(cipher)


@dataclasses.dataclass
class PersonalToolkitManagementRepository:
    """Own database scopes and recheck current User/Auth Session at every operation."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        PersonalToolkitRepository, Depends(get_personal_toolkit_repository)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    auth_session_repository: Annotated[SessionRepository, Depends(SessionRepository)]
    shared_operations: Annotated[
        ToolkitOperationsRepository, Depends(ToolkitOperationsRepository)
    ]
    oauth_repository: Annotated[
        MCPOAuthConnectionRepository, Depends(get_mcp_oauth_connection_repository)
    ]
    setting_payloads: Annotated[
        SystemSettingPayloadResolver, Depends(SystemSettingPayloadResolver)
    ]

    async def _authorize(
        self, session: ReadSession, subject: PersonalToolkitManager
    ) -> None:
        status = await evaluate_active_subject(
            session,
            user_id=subject.user_id,
            session_id=subject.session_id,
            user_repository=self.user_repository,
            session_repository=self.auth_session_repository,
        )
        if status is not ActiveAccountSubjectStatus.ACTIVE:
            raise PersonalToolkitAuthorityDenied(
                "Personal Toolkit account authorization required"
            )
        member = await session.read_session.scalar(
            sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.user_id == subject.user_id,
                RDBWorkspaceUser.workspace_id == subject.workspace_id,
            )
        )
        if member is None:
            raise PersonalToolkitAuthorityDenied(
                "Personal Toolkit Workspace access required"
            )

    async def authorize(self, subject: PersonalToolkitManager) -> None:
        """Finish current account admission before external Provider preparation."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)

    async def workspace_handle(self, subject: PersonalToolkitManager) -> str:
        """Return authorized canonical navigation identity, not credential authority."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            handle = await session.read_session.scalar(
                sa.select(RDBWorkspace.handle).where(
                    RDBWorkspace.id == subject.workspace_id
                )
            )
            if handle is None:
                raise PersonalToolkitAuthorityDenied(
                    "Personal Toolkit Workspace unavailable"
                )
            return handle

    async def authorize_test(
        self,
        subject: PersonalToolkitManager,
        *,
        source: PersonalToolkitConfig | None,
        platform: PersonalToolkitPlatformTestAuthority | None,
    ) -> None:
        """Admit the exact current account/source/installations before Provider use."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            if source is not None:
                current = await self.repository.get_personal(
                    session,
                    user_id=subject.user_id,
                    workspace_id=subject.workspace_id,
                    toolkit_id=source.id,
                )
                if current is None:
                    raise PersonalToolkitNotFound("Personal Toolkit not found")
                if current.revision != source.revision:
                    raise PersonalToolkitConfigurationConflict(
                        "Personal Toolkit changed; retry the connection test"
                    )
            if platform is not None:
                await self._platform_generation(session, platform.effective_generation)
                await self._provider_authority(session, subject, platform.authority)

    async def _platform_generation(
        self, session: WriteSession, expected_generation: str
    ) -> None:
        await self.shared_operations.system_setting_repository.acquire_section_lock(
            session, section=SystemSettingSection.PLATFORM_GITHUB_APP
        )
        current = await self.shared_operations.system_setting_repository.get_current(
            session, section=SystemSettingSection.PLATFORM_GITHUB_APP
        )
        resolved = self.setting_payloads.resolve_current(
            definition=self.setting_payloads.registry.get(
                SystemSettingSection.PLATFORM_GITHUB_APP
            ),
            current=current,
        )
        if resolved.effective_generation != expected_generation:
            raise PersonalToolkitConfigurationConflict(
                "Platform GitHub App changed; restart authorization"
            )

    async def sync_platform_installations(
        self,
        subject: PersonalToolkitManager,
        *,
        authority: PlatformToolkitAuthority,
        effective_generation: str,
        installations: Sequence[GitHubInstallationSnapshot],
    ) -> None:
        """Publish into the existing User inventory under current exact authority."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            await self._platform_generation(session, effective_generation)
            await self._provider_authority(session, subject, authority)
            await self.shared_operations.github_installation_repository.sync(
                session, subject.user_id, authority.app_id, installations
            )

    async def _provider_authority(
        self,
        session: ReadSession,
        subject: PersonalToolkitManager,
        authority: PlatformToolkitAuthority | None,
    ) -> None:
        if authority is None:
            return
        if authority.user_id != subject.user_id:
            raise PersonalToolkitProviderAuthorityDenied(
                "Provider authority belongs to another User"
            )
        error = await self.shared_operations.validate_platform_authority(
            session, authority
        )
        if error is not None:
            raise PersonalToolkitProviderAuthorityDenied(error.detail)

    async def _snapshot(
        self,
        session: ReadSession,
        subject: PersonalToolkitManager,
        toolkit: PersonalToolkitConfig,
    ) -> PersonalToolkitManagementSnapshot:
        access = await self.repository.read_access(
            session,
            user_id=subject.user_id,
            workspace_id=subject.workspace_id,
            toolkit_id=toolkit.id,
        )
        if access is None:
            raise PersonalToolkitNotFound("Personal Toolkit not found")
        return PersonalToolkitManagementSnapshot(
            toolkit=toolkit,
            access=access,
            oauth_connection=await self.oauth_repository.get_summary_by_toolkit_id(
                session, toolkit.id
            ),
            github_user_connection=await read_summary(session, toolkit.id),
        )

    async def create(
        self,
        subject: PersonalToolkitManager,
        create: ToolkitCreation,
        *,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> PersonalToolkitManagementSnapshot:
        """Commit common configuration after current account and Provider checks."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            await self._provider_authority(session, subject, platform_authority)
            toolkit = await self.repository.create_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                create=create,
            )
            return await self._snapshot(session, subject, toolkit)

    async def list(
        self, subject: PersonalToolkitManager
    ) -> Sequence[PersonalToolkitManagementSnapshot]:
        """Return only personal connections of this active authenticated account."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            toolkits = await self.repository.list_personal(
                session, user_id=subject.user_id, workspace_id=subject.workspace_id
            )
            return [
                await self._snapshot(session, subject, toolkit) for toolkit in toolkits
            ]

    async def agent_connections(
        self,
        subject: PersonalToolkitManager,
        agent_id: str,
    ) -> Sequence[PersonalToolkitManagementSnapshot]:
        """Read personal connection choices after ordinary exact-Agent admission."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            eligible = await session.read_session.scalar(
                eligible_personal_agent_ids(
                    subject.user_id, subject.workspace_id
                ).where(RDBAgent.id == agent_id)
            )
            if eligible is None:
                raise PersonalToolkitAgentIneligible(
                    "Agent is not currently accessible"
                )
            toolkits = await self.repository.list_personal(
                session, user_id=subject.user_id, workspace_id=subject.workspace_id
            )
            return [
                await self._snapshot(session, subject, toolkit) for toolkit in toolkits
            ]

    async def get(
        self, subject: PersonalToolkitManager, toolkit_id: str
    ) -> PersonalToolkitManagementSnapshot:
        """Reject foreign/shared IDs before exposing configuration or grant metadata."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            toolkit = await self.repository.get_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            if toolkit is None:
                raise PersonalToolkitNotFound("Personal Toolkit not found")
            return await self._snapshot(session, subject, toolkit)

    async def update(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
        update: ToolkitUpdate,
        *,
        expected_revision: int,
        slug_reset_canonical_name: str | None,
        platform_authority: PlatformToolkitAuthority | None,
    ) -> PersonalToolkitManagementSnapshot:
        """Publish a prepared edit only against its current canonical source."""
        async with self.session_manager() as session:
            row = await self.repository.lock_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            await self._authorize(session, subject)
            await self._provider_authority(session, subject, platform_authority)
            if row.revision != expected_revision:
                raise PersonalToolkitConfigurationConflict(
                    "Personal Toolkit changed; reload before saving"
                )
            current = await self.repository.get_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            if current is None:
                raise PersonalToolkitNotFound("Personal Toolkit not found")
            await guard_locked_user_registration_update(session, current, update)
            applied = ToolkitUpdate(**update)
            if slug_reset_canonical_name is not None:
                applied["slug"] = resolve_default_toolkit_slug(
                    applied.get("name", current.name), slug_reset_canonical_name
                )
            toolkit = await self.repository.update_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
                update=applied,
            )
            return await self._snapshot(session, subject, toolkit)

    async def delete(
        self, subject: PersonalToolkitManager, toolkit_id: str
    ) -> tuple[GitHubUserRevocation, ...]:
        """Capture revocation facts and delete before external cleanup."""
        async with self.session_manager() as session:
            row = await self.repository.lock_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            await self._authorize(session, subject)
            cipher = self.repository.cipher
            if cipher is None:
                raise RuntimeError(
                    "Personal Toolkit deletion requires credential encryption"
                )
            revocations = (
                await capture_and_clear_user_tokens(
                    session, row.id, None, cipher=cipher
                )
                if row.toolkit_type == "github"
                else ()
            )
            await self.repository.delete_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            return revocations

    async def read_oauth_context(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
    ) -> PersonalToolkitOAuthContext:
        """Capture a consistent source/grant pair before external management work."""
        async with self.session_manager() as session:
            await self.repository.lock_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            await self._authorize(session, subject)
            toolkit = await self.repository.get_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            if toolkit is None:
                raise PersonalToolkitNotFound("Personal Toolkit not found")
            return PersonalToolkitOAuthContext(
                toolkit=toolkit,
                connection=await self.oauth_repository.get_by_toolkit_id_for_update(
                    session, toolkit_id
                ),
            )

    async def store_oauth_connection(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
        *,
        expected_revision: int,
        connection: OAuthConnectionWrite,
    ) -> PersonalToolkitOAuthContext:
        """Publish only into the current owner/source after an external setup gap."""
        async with self.session_manager() as session:
            row = await self.repository.lock_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            await self._authorize(session, subject)
            if row.revision != expected_revision:
                raise PersonalToolkitConfigurationConflict(
                    "Personal Toolkit changed; restart authorization"
                )
            saved = await self.oauth_repository.upsert_connected(
                session, toolkit_id=toolkit_id, **dataclasses.asdict(connection)
            )
            row.revision += 1
            await session.write_session.flush()
            toolkit = await self.repository.get_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            if toolkit is None:
                raise PersonalToolkitNotFound("Personal Toolkit not found")
            return PersonalToolkitOAuthContext(toolkit=toolkit, connection=saved)

    async def delete_oauth_connection(
        self,
        subject: PersonalToolkitManager,
        toolkit_id: str,
    ) -> None:
        """Disconnect under the same parent fence used by pending personal callbacks."""
        async with self.session_manager() as session:
            row = await self.repository.lock_personal(
                session,
                user_id=subject.user_id,
                workspace_id=subject.workspace_id,
                toolkit_id=toolkit_id,
            )
            await self._authorize(session, subject)
            await self.oauth_repository.delete_by_toolkit_id(session, toolkit_id)
            row.revision += 1
            await session.write_session.flush()

    async def eligible_agents(
        self, subject: PersonalToolkitManager
    ) -> Sequence[PersonalToolkitEligibleAgent]:
        """Compute the full ordinary-access list independently of search pages."""
        async with self.session_manager() as session:
            await self._authorize(session, subject)
            rows = await session.read_session.execute(
                sa.select(
                    RDBAgent.id,
                    RDBAgent.name,
                    RDBWorkspace.id,
                    RDBWorkspace.name,
                    RDBWorkspace.handle,
                )
                .join(RDBWorkspace, RDBWorkspace.id == RDBAgent.workspace_id)
                .where(
                    RDBAgent.id.in_(
                        eligible_personal_agent_ids(
                            subject.user_id, subject.workspace_id
                        )
                    )
                )
                .order_by(
                    RDBWorkspace.name, RDBWorkspace.id, RDBAgent.name, RDBAgent.id
                )
            )
            return [PersonalToolkitEligibleAgent(*row) for row in rows]

    async def mutate_access(
        self,
        subject: PersonalToolkitManager,
        mutations: Sequence[PersonalToolkitAccessMutation],
        *,
        agent_id: str | None,
    ) -> Sequence[PersonalToolkitAccess]:
        """Commit both editor intents through current subject and parent authority."""
        by_id = {mutation.toolkit_id: mutation for mutation in mutations}
        if len(by_id) != len(mutations):
            raise ValueError("Duplicate Toolkit mutation")
        async with self.session_manager() as session:
            # Match dispatch lock order: parents first, then dependent authority.
            for toolkit_id in sorted(by_id):
                await self.repository.lock_personal(
                    session,
                    user_id=subject.user_id,
                    workspace_id=subject.workspace_id,
                    toolkit_id=toolkit_id,
                )
            await self._authorize(session, subject)
            if agent_id is not None:
                eligible = await session.read_session.scalar(
                    eligible_personal_agent_ids(
                        subject.user_id, subject.workspace_id
                    ).where(RDBAgent.id == agent_id)
                )
                if eligible is None:
                    raise PersonalToolkitAgentIneligible(
                        "Agent is not currently accessible"
                    )
                if any(
                    (mutation.allow_agent_ids | mutation.restrict_agent_ids)
                    - {agent_id}
                    for mutation in mutations
                ):
                    raise PersonalToolkitAgentIneligible(
                        "Agent editor may change only its exact Agent"
                    )
                if any(mutation.mode is not None for mutation in mutations):
                    raise ValueError("Agent editor cannot replace connection-wide mode")
            return [
                await self.repository.mutate_access(
                    session,
                    user_id=subject.user_id,
                    workspace_id=subject.workspace_id,
                    mutation=by_id[toolkit_id],
                )
                for toolkit_id in sorted(by_id)
            ]
