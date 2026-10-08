"""Completed database operations for the Agent service."""

import dataclasses
from typing import Annotated

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import AgentRuntimeCapability, WorkspaceUserRole
from azents.core.github_user_oauth import GitHubUserRevocation
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import (
    Agent,
    AgentAvatar,
    AgentCreate,
    AgentList,
    AgentUpdate,
)
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_admin.data import (
    AgentAdmin,
    AgentAdminCreate,
    AgentAdminList,
    DuplicateAdmin,
)
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.github_user_oauth.guards import capture_and_clear_agent_user_tokens
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import WorkspaceModelSettings
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser


@dataclasses.dataclass(frozen=True)
class AgentOperationRuntimeProfileInvalid:
    """Runtime Profile selection is not currently valid."""

    code: str


@dataclasses.dataclass(frozen=True)
class AgentOperationNotFound:
    """Agent disappeared during a completed operation."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentOperationWorkspaceMismatch:
    """Agent no longer belongs to the expected Workspace."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentOperationNotAdmin:
    """Actor no longer has current Agent mutation authority."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentOperationRuntimeProfileVersionRequired:
    """Runtime Profile mutation omitted its optimistic version."""


@dataclasses.dataclass(frozen=True)
class AgentOperationRuntimeProfileVersionConflict:
    """Runtime Profile selection version is stale."""

    current_version: int


@dataclasses.dataclass(frozen=True)
class AgentOperationUnlimitedRetention:
    """Agent decommission is blocked by unlimited archived retention."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentOperationLastAdmin:
    """The last Agent administrator cannot be removed."""

    agent_id: str
    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class AgentOperationAdminNotFound:
    """The requested Agent administrator does not exist."""

    agent_id: str
    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class AgentDecommissionRequest:
    """Committed Agent decommission state and durable job."""

    agent: Agent
    job: AgentDecommissionJob
    github_user_revocations: tuple[GitHubUserRevocation, ...] = dataclasses.field(
        repr=False
    )


@dataclasses.dataclass(frozen=True)
class AgentRuntimeProfileSelectionChange:
    """One explicit Runtime Profile selection update."""

    profile_id: str | None
    expected_version: int | None


AgentUpdateOperationError = (
    AgentOperationNotFound
    | AgentOperationWorkspaceMismatch
    | AgentOperationNotAdmin
    | AgentOperationRuntimeProfileInvalid
    | AgentOperationRuntimeProfileVersionRequired
    | AgentOperationRuntimeProfileVersionConflict
)


@dataclasses.dataclass
class AgentOperationsRepository:
    """Own complete Agent service database transactions."""

    session_manager: Annotated[
        SessionManager[WriteSession],
        Depends(get_session_manager),
    ]
    credential_cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]
    workspace_model_settings_repository: Annotated[
        WorkspaceModelSettingsRepository,
        Depends(WorkspaceModelSettingsRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    agent_decommission_repository: Annotated[
        AgentDecommissionRepository,
        Depends(AgentDecommissionRepository),
    ]
    archived_session_retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    runtime_profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    runtime_profile_availability_repository: Annotated[
        RuntimeProfileAvailabilityRepository,
        Depends(RuntimeProfileAvailabilityRepository),
    ]

    async def get_workspace_model_settings(
        self,
        workspace_id: str,
    ) -> WorkspaceModelSettings:
        """Return completed Workspace model settings."""
        async with self.session_manager() as session:
            return await self.workspace_model_settings_repository.get_or_create(
                session,
                workspace_id,
            )

    async def create(
        self,
        create: AgentCreate,
        *,
        creator_workspace_user_id: str,
    ) -> Result[Agent, AgentOperationRuntimeProfileInvalid]:
        """Create Agent, first admin, and reconcile intent atomically."""
        async with self.session_manager() as session:
            if create.runtime_profile_id is not None:
                availability_repository = self.runtime_profile_availability_repository
                error_code = await (
                    availability_repository.get_agent_profile_unavailability_code(
                        session,
                        workspace_id=create.workspace_id,
                        profile_id=create.runtime_profile_id,
                    )
                )
                if error_code is not None:
                    return Failure(AgentOperationRuntimeProfileInvalid(code=error_code))
            agent = await self.agent_repository.create(session, create)
            await self.admin_repository.create(
                session,
                AgentAdminCreate(
                    agent_id=agent.id,
                    workspace_user_id=creator_workspace_user_id,
                ),
            )
            if agent.runtime_capability is AgentRuntimeCapability.MANAGED:
                await self.runtime_profile_repository.enqueue_reconcile_task(
                    session,
                    source_type=RuntimeReconcileSourceKind.AGENT_SELECTION,
                    source_id=agent.id,
                    source_version=str(agent.runtime_profile_selection_version),
                    available_at=tznow(),
                )
            return Success(agent)

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        workspace_user_id: str,
        owner: bool,
    ) -> AgentList:
        """Return completed Workspace Agent visibility results."""
        async with self.session_manager() as session:
            if owner:
                return await self.agent_repository.list_by_workspace(
                    session,
                    workspace_id,
                )
            return await self.agent_repository.list_visible_by_workspace(
                session,
                workspace_id,
                workspace_user_id,
            )

    async def list_admin_agent_ids(
        self,
        *,
        workspace_user_id: str,
        agent_ids: list[str],
    ) -> set[str]:
        """Return completed management membership for visible Agents."""
        async with self.session_manager() as session:
            return await self.admin_repository.list_admin_agent_ids(
                session,
                workspace_user_id=workspace_user_id,
                agent_ids=agent_ids,
            )

    async def get_by_id(self, agent_id: str) -> Agent | None:
        """Return one completed Agent snapshot."""
        async with self.session_manager() as session:
            return await self.agent_repository.get_by_id(session, agent_id)

    async def is_admin(
        self,
        agent_id: str,
        workspace_user_id: str,
    ) -> bool:
        """Return completed Agent admin membership."""
        async with self.session_manager() as session:
            return await self.admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            )

    async def update_by_id(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        update: AgentUpdate,
        runtime_profile_change: AgentRuntimeProfileSelectionChange | None,
        model_configuration_changed: bool,
        valid_model_target_labels: list[str],
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
    ) -> Result[Agent, AgentUpdateOperationError]:
        """Apply one complete Agent mutation under existing authority fences."""
        async with self.session_manager() as session:
            authority = await self._authorize_mutation(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
            )
            if authority.failure:
                return Failure(authority.error)
            locked = authority.value
            if runtime_profile_change is not None:
                capability_error = _runtime_capability_update_error(
                    locked.runtime_capability
                )
                if capability_error is not None:
                    return Failure(
                        AgentOperationRuntimeProfileInvalid(code=capability_error)
                    )
                expected_version = runtime_profile_change.expected_version
                if expected_version is None:
                    return Failure(AgentOperationRuntimeProfileVersionRequired())
                runtime_profile_id = runtime_profile_change.profile_id
                if runtime_profile_id is None:
                    profile_repository = self.runtime_profile_repository
                    cleared = await (
                        profile_repository.clear_agent_runtime_profile_selection(
                            session,
                            agent_id=agent_id,
                            expected_selection_version=expected_version,
                        )
                    )
                    if not cleared:
                        current = await self.agent_repository.get_by_id(
                            session,
                            agent_id,
                        )
                        if current is None:
                            return Failure(AgentOperationNotFound(agent_id=agent_id))
                        return Failure(
                            AgentOperationRuntimeProfileVersionConflict(
                                current_version=(
                                    current.runtime_profile_selection_version
                                )
                            )
                        )
                else:
                    availability_repository = (
                        self.runtime_profile_availability_repository
                    )
                    error_code = await (
                        availability_repository.get_agent_profile_unavailability_code(
                            session,
                            workspace_id=workspace_id,
                            profile_id=runtime_profile_id,
                        )
                    )
                    if error_code is not None:
                        return Failure(
                            AgentOperationRuntimeProfileInvalid(code=error_code)
                        )
                    selected = (
                        await self.agent_repository.replace_runtime_profile_selection(
                            session,
                            agent_id=agent_id,
                            expected_version=expected_version,
                            runtime_profile_id=runtime_profile_id,
                        )
                    )
                    if selected is None:
                        current = await self.agent_repository.get_by_id(
                            session,
                            agent_id,
                        )
                        if current is None:
                            return Failure(AgentOperationNotFound(agent_id=agent_id))
                        return Failure(
                            AgentOperationRuntimeProfileVersionConflict(
                                current_version=(
                                    current.runtime_profile_selection_version
                                )
                            )
                        )
                    await self.runtime_profile_repository.enqueue_reconcile_task(
                        session,
                        source_type=RuntimeReconcileSourceKind.AGENT_SELECTION,
                        source_id=selected.id,
                        source_version=str(selected.runtime_profile_selection_version),
                        available_at=tznow(),
                    )

            result = await self.agent_repository.update_by_id(
                session,
                agent_id,
                update,
            )
            if result.failure:
                return Failure(AgentOperationNotFound(agent_id=agent_id))
            if model_configuration_changed:
                await (
                    self.agent_session_repository.replace_stale_applied_inference_profiles
                )(
                    session,
                    agent_id=agent_id,
                    valid_model_target_labels=valid_model_target_labels,
                    model_target_label=model_target_label,
                    reasoning_effort=reasoning_effort,
                    enabled_execution_options=[],
                )
            return Success(result.value)

    async def request_decommission(
        self,
        *,
        agent_id: str,
        workspace_user_id: str,
    ) -> Result[
        AgentDecommissionRequest,
        AgentOperationNotFound | AgentOperationUnlimitedRetention,
    ]:
        """Request Agent decommission in one completed transaction."""
        async with self.session_manager() as session:
            settings = await self.archived_session_retention_repository.get_settings(
                session
            )
            if settings.archived_session_retention_days is None:
                return Failure(AgentOperationUnlimitedRetention(agent_id=agent_id))
            revocations = await capture_and_clear_agent_user_tokens(
                session, agent_id=agent_id, cipher=self.credential_cipher
            )
            decommissioned = await self.agent_repository.mark_decommissioning(
                session,
                agent_id,
            )
            if decommissioned is None:
                return Failure(AgentOperationNotFound(agent_id=agent_id))
            job = await self.agent_decommission_repository.create_or_get(
                session,
                agent_id=decommissioned.id,
                workspace_id=decommissioned.workspace_id,
                requested_by_workspace_user_id=workspace_user_id,
            )
            return Success(
                AgentDecommissionRequest(
                    agent=decommissioned,
                    job=job,
                    github_user_revocations=revocations,
                )
            )

    async def list_admins(self, agent_id: str) -> AgentAdminList:
        """Return completed Agent admin list."""
        async with self.session_manager() as session:
            return await self.admin_repository.list_by_agent(session, agent_id)

    async def get_workspace_user(
        self,
        workspace_user_id: str,
    ) -> WorkspaceUser | None:
        """Return one completed WorkspaceUser snapshot."""
        async with self.session_manager() as session:
            return await self.workspace_user_repository.get(
                session,
                workspace_user_id,
            )

    async def create_admin(
        self,
        *,
        agent_id: str,
        workspace_user_id: str,
    ) -> Result[AgentAdmin, DuplicateAdmin]:
        """Create one Agent admin in a completed transaction."""
        async with self.session_manager() as session:
            return await self.admin_repository.create(
                session,
                AgentAdminCreate(
                    agent_id=agent_id,
                    workspace_user_id=workspace_user_id,
                ),
            )

    async def remove_admin(
        self,
        *,
        agent_id: str,
        workspace_user_id: str,
    ) -> Result[None, AgentOperationLastAdmin | AgentOperationAdminNotFound]:
        """Protect the last admin and remove the target atomically."""
        async with self.session_manager() as session:
            count = await self.admin_repository.count_by_agent(session, agent_id)
            if count <= 1:
                return Failure(
                    AgentOperationLastAdmin(
                        agent_id=agent_id,
                        workspace_user_id=workspace_user_id,
                    )
                )
            deleted = await self.admin_repository.delete(
                session,
                agent_id,
                workspace_user_id,
            )
            if not deleted:
                return Failure(
                    AgentOperationAdminNotFound(
                        agent_id=agent_id,
                        workspace_user_id=workspace_user_id,
                    )
                )
            return Success(None)

    async def update_avatar(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        avatar: AgentAvatar | None,
    ) -> Result[
        Agent,
        AgentOperationNotFound
        | AgentOperationWorkspaceMismatch
        | AgentOperationNotAdmin,
    ]:
        """Replace one Agent avatar in a completed transaction."""
        async with self.session_manager() as session:
            authority = await self._authorize_mutation(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
            )
            if authority.failure:
                return Failure(authority.error)
            result = await self.agent_repository.update_avatar(
                session,
                agent_id,
                avatar,
            )
            if result.failure:
                return Failure(AgentOperationNotFound(agent_id=agent_id))
            return Success(result.value)

    async def _authorize_mutation(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
    ) -> Result[
        Agent,
        AgentOperationNotFound
        | AgentOperationWorkspaceMismatch
        | AgentOperationNotAdmin,
    ]:
        """Read exact Workspace and Agent mutation permissions without parent locks."""
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(AgentOperationNotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(AgentOperationWorkspaceMismatch(agent_id=agent_id))
        workspace_user = await self.workspace_user_repository.get(
            session,
            workspace_user_id,
        )
        if workspace_user is None or workspace_user.workspace_id != workspace_id:
            return Failure(AgentOperationNotAdmin(agent_id=agent_id))
        if workspace_user.role is WorkspaceUserRole.OWNER:
            return Success(agent)
        admin = await self.admin_repository.is_admin(
            session,
            agent_id,
            workspace_user_id,
        )
        if not admin:
            return Failure(AgentOperationNotAdmin(agent_id=agent_id))
        return Success(agent)


def _runtime_capability_update_error(
    capability: AgentRuntimeCapability,
) -> str | None:
    """Return the dedicated-action error for Runtime-only Agent settings."""
    if capability is AgentRuntimeCapability.NONE:
        return "runtime_action_required"
    if capability is AgentRuntimeCapability.REMOVING:
        return "runtime_removal_in_progress"
    return None
