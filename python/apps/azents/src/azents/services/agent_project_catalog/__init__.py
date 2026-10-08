"""Agent Project catalog service."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import AgentProjectCatalogStatus
from azents.core.session_workspace_paths import (
    InvalidProjectPath,
    normalize_agent_workspace_root,
    normalize_session_workspace_path,
    normalize_session_workspace_project_paths,
)
from azents.repos.agent_project_catalog.data import (
    AgentProjectCatalogEntry,
    AgentProjectCatalogStatusPatch,
)
from azents.repos.agent_project_catalog.operations import (
    AgentProjectCatalogOperationsRepository,
    ProjectCatalogStatusApplication,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_storage_error import RuntimeStorageError

_PROJECT_STATUS_SYNC_TIMEOUT_SECONDS = 120


def _project_status_sync_deadline() -> datetime:
    """Return Runtime operation deadline for Project status sync."""
    return datetime.now(UTC) + timedelta(seconds=_PROJECT_STATUS_SYNC_TIMEOUT_SECONDS)


@dataclasses.dataclass
class AgentProjectCatalogService:
    """Manage Agent Project catalog candidates and status projection."""

    repository: Annotated[
        AgentProjectCatalogOperationsRepository,
        Depends(AgentProjectCatalogOperationsRepository),
    ]
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
    ]
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None

    async def upsert_project_candidate(
        self,
        *,
        agent_id: str,
        path: str,
    ) -> Result[AgentProjectCatalogEntry, InvalidProjectPath]:
        """Upsert one Project candidate path."""
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
        except RuntimeStorageError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        try:
            normalized = normalize_session_workspace_path(
                path, workspace_root=runtime.workspace_path
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        entries = await self.repository.upsert_candidates(
            agent_id=agent_id, paths=(normalized,)
        )
        return Success(entries[0])

    async def upsert_project_candidates(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Upsert Project candidate paths."""
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
        except RuntimeStorageError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        try:
            normalized_paths = normalize_session_workspace_project_paths(
                paths, workspace_root=runtime.workspace_path
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        entries = await self.repository.upsert_candidates(
            agent_id=agent_id, paths=tuple(normalized_paths)
        )
        return Success(entries)

    async def list_catalog_entries(
        self,
        *,
        agent_id: str,
    ) -> list[AgentProjectCatalogEntry]:
        """Fetch catalog entries for an Agent."""
        return await self.repository.list_entries(agent_id=agent_id)

    async def list_catalog_entries_by_paths(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Fetch catalog entries for normalized Project paths."""
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                wait_timeout_seconds=0.0,
                start_if_stopped=False,
            )
        except RuntimeStorageError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        try:
            normalized_paths = normalize_session_workspace_project_paths(
                paths, workspace_root=runtime.workspace_path
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        return Success(
            await self.repository.list_entries_by_paths(
                agent_id=agent_id, paths=tuple(normalized_paths)
            )
        )

    async def refresh_project_status(
        self,
        *,
        agent_id: str,
        path: str,
    ) -> Result[AgentProjectCatalogEntry, InvalidProjectPath]:
        """Refresh one Project candidate filesystem status projection."""
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
        except RuntimeStorageError as error:
            return Failure(InvalidProjectPath(path=path, reason=str(error)))
        try:
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized = normalize_session_workspace_path(
                path, workspace_root=workspace_root
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        patch = await self._status_patch(runtime, normalized)
        entries = await self.repository.apply_statuses(
            agent_id=agent_id,
            applications=(
                ProjectCatalogStatusApplication(path=normalized, patch=patch),
            ),
        )
        return Success(entries[0])

    async def refresh_project_statuses(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Refresh multiple Project candidate filesystem status projections."""
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
        except RuntimeStorageError as error:
            return Failure(InvalidProjectPath(path="", reason=str(error)))
        try:
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_paths = normalize_session_workspace_project_paths(
                paths, workspace_root=workspace_root
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        applications = tuple(
            [
                ProjectCatalogStatusApplication(
                    path=path, patch=await self._status_patch(runtime, path)
                )
                for path in normalized_paths
            ]
        )
        entries = await self.repository.apply_statuses(
            agent_id=agent_id, applications=applications
        )
        return Success(entries)

    async def _status_patch(
        self,
        runtime: RuntimeOperationTarget,
        path: str,
    ) -> AgentProjectCatalogStatusPatch:
        """Build the current status patch for a path."""
        checked_at = datetime.now(UTC)
        if self.runner_operations is None:
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.UNAVAILABLE,
                status_detail="Runtime runner operations are unavailable.",
                checked_at=checked_at,
            )
        try:
            stat = await self.runner_operations.stat_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=None,
                path=path,
                deadline_at=_project_status_sync_deadline(),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.UNAVAILABLE,
                status_detail="Runtime runner is not ready.",
                checked_at=checked_at,
            )
        except RuntimeRunnerOperationFailedError as error:
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.ERROR,
                status_detail=str(error),
                checked_at=checked_at,
            )
        return _status_patch_from_stat(stat, checked_at=checked_at)


def _status_patch_from_stat(
    stat: RuntimeFileStatResult,
    *,
    checked_at: datetime,
) -> AgentProjectCatalogStatusPatch:
    """Map a runner stat result to Project catalog status."""
    target_kind = stat.resolved_kind if stat.kind == "symlink" else stat.kind
    match target_kind:
        case "directory":
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.AVAILABLE,
                status_detail=None,
                checked_at=checked_at,
            )
        case "missing":
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.MISSING,
                status_detail="Path does not exist.",
                checked_at=checked_at,
            )
        case "file" | "symlink" | "other" | None:
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.ERROR,
                status_detail=f"Project path is not a directory: {stat.kind}.",
                checked_at=checked_at,
            )
        case _:
            assert_never(target_kind)
