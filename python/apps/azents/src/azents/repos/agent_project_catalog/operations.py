"""Completed Agent Project catalog database operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import (
    AgentProjectCatalogEntry,
    AgentProjectCatalogStatusPatch,
)


@dataclasses.dataclass(frozen=True)
class ProjectCatalogStatusApplication:
    """One normalized path and detached Runtime-derived status projection."""

    path: str
    patch: AgentProjectCatalogStatusPatch


@dataclasses.dataclass
class AgentProjectCatalogOperationsRepository:
    """Own catalog identity groups and detached descriptive status mutations."""

    catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends(AgentProjectCatalogRepository)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def upsert_candidates(
        self, *, agent_id: str, paths: tuple[str, ...]
    ) -> list[AgentProjectCatalogEntry]:
        """Commit all normalized candidate paths as one catalog identity group."""
        async with self.session_manager() as session:
            return [
                await self.catalog_repository.upsert_entry(
                    session, agent_id=agent_id, path=path
                )
                for path in paths
            ]

    async def list_entries(self, *, agent_id: str) -> list[AgentProjectCatalogEntry]:
        """Return detached Agent-scoped entries from a completed read-only scope."""
        async with self.read_session_manager() as session:
            return await self.catalog_repository.list_entries(
                session, agent_id=agent_id
            )

    async def list_entries_by_paths(
        self, *, agent_id: str, paths: tuple[str, ...]
    ) -> list[AgentProjectCatalogEntry]:
        """Read exact normalized paths with the existing path-order projection."""
        async with self.read_session_manager() as session:
            return await self.catalog_repository.list_entries_by_paths(
                session, agent_id=agent_id, paths=list(paths)
            )

    async def apply_statuses(
        self,
        *,
        agent_id: str,
        applications: tuple[ProjectCatalogStatusApplication, ...],
    ) -> list[AgentProjectCatalogEntry]:
        """Commit detached status evidence as one complete mutation group."""
        async with self.session_manager() as session:
            return [
                await self.catalog_repository.update_status(
                    session,
                    agent_id=agent_id,
                    path=application.path,
                    patch=application.patch,
                )
                for application in applications
            ]
