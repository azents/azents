"""Agent automatic Project policy management service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent_automatic_project import AgentAutomaticProjectPolicy
from azents.core.agent_errors import NotFound
from azents.core.session_workspace_paths import (
    InvalidProjectPath,
    normalize_agent_workspace_root,
    normalize_session_workspace_path,
)
from azents.repos.agent_automatic_project_operations import (
    AgentAutomaticProjectOperationsRepository,
    AutomaticProjectDenial,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.agent.data import NotAdmin, NotBelongToWorkspace
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_directory_validation import (
    RuntimeDirectoryNotDirectory,
    RuntimeDirectoryNotFound,
    RuntimeDirectoryValidationUnavailable,
    validate_runtime_directory,
)
from azents.services.runtime_storage_error import RuntimeStorageError

from .data import (
    AgentAutomaticProjectPolicyNotFound,
    AutomaticSessionProjectsRevisionConflict,
    AutomaticSessionProjectsRuntimeUnavailable,
)


@dataclasses.dataclass
class AgentAutomaticProjectService:
    """Manage one Agent's automatic root Session Project policy."""

    repository: Annotated[
        AgentAutomaticProjectOperationsRepository,
        Depends(AgentAutomaticProjectOperationsRepository),
    ]
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
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
        result = await self.repository.read(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
        )
        match result:
            case Success(policy):
                return Success(policy)
            case Failure(error):
                return Failure(self._read_error(error, agent_id=agent_id))
            case _:
                assert_never(result)

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
        early_policy = await self.repository.read(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
        )
        match early_policy:
            case Success(policy):
                pass
            case Failure(error):
                return Failure(self._read_error(error, agent_id=agent_id))
            case _:
                assert_never(early_policy)
        if policy.revision != expected_revision:
            return Failure(
                AutomaticSessionProjectsRevisionConflict(
                    expected_revision=expected_revision,
                )
            )
        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        workspace_root: str | None = None
        runtime: RuntimeOperationTarget | None = None
        if project_paths:
            try:
                runtime = await self.runtime_target_resolver.resolve_operation_target(
                    agent_id
                )
            except RuntimeStorageError as error:
                return Failure(
                    AutomaticSessionProjectsRuntimeUnavailable(message=str(error))
                )
            try:
                workspace_root = normalize_agent_workspace_root(
                    runtime.workspace_path
                ).as_posix()
            except ValueError as error:
                return Failure(InvalidProjectPath(path="", reason=str(error)))
        for path in project_paths:
            assert workspace_root is not None
            try:
                normalized_path = normalize_session_workspace_path(
                    path,
                    workspace_root=workspace_root,
                )
            except ValueError as error:
                return Failure(InvalidProjectPath(path=path, reason=str(error)))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            normalized_paths.append(normalized_path)

        if normalized_paths:
            assert runtime is not None
            validation = await self._validate_directories(
                runtime=runtime,
                project_paths=normalized_paths,
            )
            match validation:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(validation)

        replacement = await self.repository.replace(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            expected_revision=expected_revision,
            paths=normalized_paths,
        )
        match replacement:
            case Success(replaced):
                return Success(replaced)
            case Failure(AutomaticProjectDenial.REVISION_CONFLICT):
                return Failure(
                    AutomaticSessionProjectsRevisionConflict(
                        expected_revision=expected_revision,
                    )
                )
            case Failure(error):
                return Failure(self._read_error(error, agent_id=agent_id))
            case _:
                assert_never(replacement)

    @staticmethod
    def _read_error(
        denial: AutomaticProjectDenial,
        *,
        agent_id: str,
    ) -> (
        NotFound | NotBelongToWorkspace | NotAdmin | AgentAutomaticProjectPolicyNotFound
    ):
        match denial:
            case AutomaticProjectDenial.AGENT_MISSING:
                return NotFound(agent_id=agent_id)
            case AutomaticProjectDenial.FOREIGN_WORKSPACE:
                return NotBelongToWorkspace(agent_id=agent_id)
            case AutomaticProjectDenial.ADMIN_REQUIRED:
                return NotAdmin(agent_id=agent_id)
            case AutomaticProjectDenial.POLICY_MISSING:
                return AgentAutomaticProjectPolicyNotFound(agent_id=agent_id)
            case AutomaticProjectDenial.REVISION_CONFLICT:
                raise RuntimeError("Policy read returned a mutation-only denial")
            case _:
                assert_never(denial)

    async def _validate_directories(
        self,
        *,
        runtime: RuntimeOperationTarget,
        project_paths: list[str],
    ) -> Result[
        None,
        InvalidProjectPath | AutomaticSessionProjectsRuntimeUnavailable,
    ]:
        """Validate every replacement path with no database transaction held."""
        for path in project_paths:
            try:
                normalized_path = normalize_session_workspace_path(
                    path,
                    workspace_root=runtime.workspace_path,
                )
            except ValueError as error:
                return Failure(InvalidProjectPath(path=path, reason=str(error)))
            result = await validate_runtime_directory(
                self.runner_operations,
                runtime=runtime,
                path=normalized_path,
            )
            if result.success:
                continue
            else:
                error = result.error
                match error:
                    case RuntimeDirectoryValidationUnavailable(message=message):
                        return Failure(
                            AutomaticSessionProjectsRuntimeUnavailable(message=message)
                        )
                    case RuntimeDirectoryNotFound():
                        return Failure(
                            InvalidProjectPath(
                                path=path,
                                reason=(
                                    "Project path must exist as a runtime directory."
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
        return Success(None)
