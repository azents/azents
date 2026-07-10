"""Agent Project catalog service."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, RuntimeRunnerState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import (
    AgentProjectCatalogEntry,
    AgentProjectCatalogStatusPatch,
)
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
    normalize_session_workspace_project_paths,
)

_PROJECT_STATUS_SYNC_TIMEOUT_SECONDS = 120


def _project_status_sync_deadline() -> datetime:
    """Return Runtime operation deadline for Project status sync."""
    return datetime.now(UTC) + timedelta(seconds=_PROJECT_STATUS_SYNC_TIMEOUT_SECONDS)


@dataclasses.dataclass
class AgentProjectCatalogService:
    """Manage Agent Project catalog candidates and status projection."""

    catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
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
            normalized = normalize_session_workspace_path(path)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        async with self.session_manager() as session:
            entry = await self.catalog_repository.upsert_entry(
                session,
                agent_id=agent_id,
                path=normalized,
            )
            await session.commit()
            return Success(entry)

    async def upsert_project_candidates(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Upsert Project candidate paths."""
        try:
            normalized_paths = normalize_session_workspace_project_paths(paths)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        async with self.session_manager() as session:
            entries: list[AgentProjectCatalogEntry] = []
            for path in normalized_paths:
                entries.append(
                    await self.catalog_repository.upsert_entry(
                        session,
                        agent_id=agent_id,
                        path=path,
                    )
                )
            await session.commit()
            return Success(entries)

    async def list_catalog_entries(
        self,
        *,
        agent_id: str,
    ) -> list[AgentProjectCatalogEntry]:
        """Fetch catalog entries for an Agent."""
        async with self.session_manager() as session:
            return await self.catalog_repository.list_entries(
                session,
                agent_id=agent_id,
            )

    async def list_catalog_entries_by_paths(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Fetch catalog entries for normalized Project paths."""
        try:
            normalized_paths = normalize_session_workspace_project_paths(paths)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        async with self.session_manager() as session:
            return Success(
                await self.catalog_repository.list_entries_by_paths(
                    session,
                    agent_id=agent_id,
                    paths=normalized_paths,
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
            normalized = normalize_session_workspace_path(path)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path=path, reason=str(exc)))
        async with self.session_manager() as session:
            runtime = await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )
        patch = await self._status_patch(runtime, normalized)
        async with self.session_manager() as session:
            entry = await self.catalog_repository.update_status(
                session,
                agent_id=agent_id,
                path=normalized,
                patch=patch,
            )
            await session.commit()
            return Success(entry)

    async def refresh_project_statuses(
        self,
        *,
        agent_id: str,
        paths: list[str],
    ) -> Result[list[AgentProjectCatalogEntry], InvalidProjectPath]:
        """Refresh multiple Project candidate filesystem status projections."""
        try:
            normalized_paths = normalize_session_workspace_project_paths(paths)
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))
        async with self.session_manager() as session:
            runtime = await self.agent_runtime_repository.get_by_agent_id(
                session,
                agent_id,
            )
        patches = [await self._status_patch(runtime, path) for path in normalized_paths]
        async with self.session_manager() as session:
            entries: list[AgentProjectCatalogEntry] = []
            for path, patch in zip(normalized_paths, patches, strict=True):
                entries.append(
                    await self.catalog_repository.update_status(
                        session,
                        agent_id=agent_id,
                        path=path,
                        patch=patch,
                    )
                )
            await session.commit()
            return Success(entries)

    async def _status_patch(
        self,
        runtime: AgentRuntime | None,
        path: str,
    ) -> AgentProjectCatalogStatusPatch:
        """Build the current status patch for a path."""
        checked_at = datetime.now(UTC)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            return AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.UNAVAILABLE,
                status_detail="Runtime runner is not ready.",
                checked_at=checked_at,
            )
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
