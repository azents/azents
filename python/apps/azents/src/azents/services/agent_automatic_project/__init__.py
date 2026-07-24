"""Agent automatic Project policy management service."""

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import NotFound
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_automatic_project.data import AgentAutomaticProjectPolicy
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.agent.data import NotAdmin, NotBelongToWorkspace
from azents.services.runtime_directory_validation import (
    RuntimeDirectoryNotDirectory,
    RuntimeDirectoryNotFound,
    RuntimeDirectoryValidationUnavailable,
    validate_runtime_directory,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
)

from .data import (
    AgentAutomaticProjectPolicyNotFound,
    AutomaticSessionProjectsRevisionConflict,
    AutomaticSessionProjectsRuntimeUnavailable,
)


def _available_catalog_status_patch() -> AgentProjectCatalogStatusPatch:
    """Build a catalog projection patch for a validated directory."""
    return AgentProjectCatalogStatusPatch(
        status=AgentProjectCatalogStatus.AVAILABLE,
        status_detail=None,
        checked_at=datetime.now(UTC),
    )


@dataclasses.dataclass
class AgentAutomaticProjectService:
    """Manage one Agent's automatic root Session Project policy."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]
    policy_repository: Annotated[
        AgentAutomaticProjectRepository,
        Depends(AgentAutomaticProjectRepository),
    ]
    catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None

    async def get_policy(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
    ) -> Result[
        AgentAutomaticProjectPolicy,
        NotFound
        | NotBelongToWorkspace
        | NotAdmin
        | AgentAutomaticProjectPolicyNotFound,
    ]:
        """Return the current management policy without Runtime interaction."""
        authorization = await self._authorize(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
        )
        match authorization:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(authorization)
        async with self.session_manager() as session:
            policy = await self.policy_repository.get_policy(session, agent_id=agent_id)
        if policy is None:
            return Failure(AgentAutomaticProjectPolicyNotFound(agent_id=agent_id))
        return Success(policy)

    async def replace_policy(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        expected_revision: int,
        project_paths: list[str],
    ) -> Result[
        AgentAutomaticProjectPolicy,
        NotFound
        | NotBelongToWorkspace
        | NotAdmin
        | InvalidProjectPath
        | AutomaticSessionProjectsRevisionConflict
        | AutomaticSessionProjectsRuntimeUnavailable
        | AgentAutomaticProjectPolicyNotFound,
    ]:
        """Validate and atomically replace the complete ordered policy."""
        authorization = await self._authorize(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
        )
        match authorization:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(authorization)
        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        for path in project_paths:
            try:
                normalized_path = normalize_session_workspace_path(path)
            except ValueError as error:
                return Failure(InvalidProjectPath(path=path, reason=str(error)))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            normalized_paths.append(normalized_path)

        early_policy = await self._get_policy(agent_id)
        match early_policy:
            case Success(policy):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(early_policy)
        if policy.revision != expected_revision:
            return Failure(
                AutomaticSessionProjectsRevisionConflict(
                    expected_revision=expected_revision,
                )
            )

        if normalized_paths:
            validation = await self._validate_directories(
                agent_id=agent_id,
                project_paths=normalized_paths,
            )
            match validation:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(validation)

        async with self.session_manager() as session:
            locked_policy = await self.policy_repository.lock_policy(
                session,
                agent_id=agent_id,
            )
            if locked_policy is None:
                return Failure(AgentAutomaticProjectPolicyNotFound(agent_id=agent_id))
            if locked_policy.revision != expected_revision:
                return Failure(
                    AutomaticSessionProjectsRevisionConflict(
                        expected_revision=expected_revision,
                    )
                )
            replacement = await self.policy_repository.replace_policy(
                session,
                agent_id=agent_id,
                expected_revision=expected_revision,
                paths=normalized_paths,
                updated_by_workspace_user_id=workspace_user_id,
            )
            match replacement:
                case Success(replaced):
                    pass
                case Failure():
                    return Failure(
                        AutomaticSessionProjectsRevisionConflict(
                            expected_revision=expected_revision,
                        )
                    )
                case _:
                    assert_never(replacement)
            for path in normalized_paths:
                await self.catalog_repository.update_status(
                    session,
                    agent_id=agent_id,
                    path=path,
                    patch=_available_catalog_status_patch(),
                )
            await session.commit()
        return Success(replaced)

    async def _authorize(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
    ) -> Result[None, NotFound | NotBelongToWorkspace | NotAdmin]:
        """Require Agent ownership and an explicit AgentAdmin relationship."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(NotFound(agent_id=agent_id))
            if agent.workspace_id != workspace_id:
                return Failure(NotBelongToWorkspace(agent_id=agent_id))
            is_admin = await self.agent_admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            )
        if not is_admin:
            return Failure(NotAdmin(agent_id=agent_id))
        return Success(None)

    async def _get_policy(
        self,
        agent_id: str,
    ) -> Result[
        AgentAutomaticProjectPolicy,
        AgentAutomaticProjectPolicyNotFound,
    ]:
        """Read one policy snapshot before any Runtime operation."""
        async with self.session_manager() as session:
            policy = await self.policy_repository.get_policy(session, agent_id=agent_id)
        if policy is None:
            return Failure(AgentAutomaticProjectPolicyNotFound(agent_id=agent_id))
        return Success(policy)

    async def _validate_directories(
        self,
        *,
        agent_id: str,
        project_paths: list[str],
    ) -> Result[
        None,
        InvalidProjectPath | AutomaticSessionProjectsRuntimeUnavailable,
    ]:
        """Validate every replacement path with no database transaction held."""
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
        for path in project_paths:
            result = await validate_runtime_directory(
                self.runner_operations,
                runtime=runtime,
                path=path,
            )
            match result:
                case Success():
                    continue
                case Failure(error):
                    match error:
                        case RuntimeDirectoryValidationUnavailable(message=message):
                            return Failure(
                                AutomaticSessionProjectsRuntimeUnavailable(
                                    message=message
                                )
                            )
                        case RuntimeDirectoryNotFound():
                            return Failure(
                                InvalidProjectPath(
                                    path=path,
                                    reason=(
                                        "Project path must exist as a runtime "
                                        "directory."
                                    ),
                                )
                            )
                        case RuntimeDirectoryNotDirectory():
                            return Failure(
                                InvalidProjectPath(
                                    path=path,
                                    reason="Project path must be a runtime directory.",
                                )
                            )
                        case _:
                            assert_never(error)
                case _:
                    assert_never(result)
        return Success(None)
