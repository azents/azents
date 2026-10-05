"""Completed authorization and atomic automatic Project policy operations."""

import dataclasses
import enum
from datetime import UTC, datetime
from typing import Annotated, assert_never

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent_automatic_project import AgentAutomaticProjectPolicy
from azents.core.enums import AgentProjectCatalogStatus
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch


class AutomaticProjectDenial(enum.StrEnum):
    """Closed database authority and expected revision denials."""

    AGENT_MISSING = "agent_missing"
    FOREIGN_WORKSPACE = "foreign_workspace"
    ADMIN_REQUIRED = "admin_required"
    POLICY_MISSING = "policy_missing"
    REVISION_CONFLICT = "revision_conflict"


type AutomaticProjectOperationResult = Result[
    AgentAutomaticProjectPolicy, AutomaticProjectDenial
]


@dataclasses.dataclass
class AgentAutomaticProjectOperationsRepository:
    """Own coherent policy reads and reauthorized policy/catalog atomic replacement."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    admin_repository: Annotated[AgentAdminRepository, Depends(AgentAdminRepository)]
    policy_repository: Annotated[
        AgentAutomaticProjectRepository, Depends(AgentAutomaticProjectRepository)
    ]
    catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends(AgentProjectCatalogRepository)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def read(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
    ) -> AutomaticProjectOperationResult:
        """Complete exact Agent/Workspace/admin admission and coherent policy read."""
        async with self.read_session_manager() as session:
            denial = await self._authorize(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
            )
            if denial is not None:
                return Failure(denial)
            policy = await self.policy_repository.get_policy(session, agent_id=agent_id)
            if policy is None:
                return Failure(AutomaticProjectDenial.POLICY_MISSING)
            return Success(policy)

    async def replace(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        expected_revision: int,
        paths: list[str],
    ) -> AutomaticProjectOperationResult:
        """Recheck authority and commit policy/catalog effects together after probes."""
        async with self.session_manager() as session:
            # Fence the same Agent and explicit admin row before policy mutation.
            agent = await self.agent_repository.lock_by_id(session, agent_id)
            if agent is None:
                return Failure(AutomaticProjectDenial.AGENT_MISSING)
            if agent.workspace_id != workspace_id:
                return Failure(AutomaticProjectDenial.FOREIGN_WORKSPACE)
            admin = await session.write_session.execute(
                sa.select(RDBAgentAdmin.id)
                .where(
                    RDBAgentAdmin.agent_id == agent_id,
                    RDBAgentAdmin.workspace_user_id == workspace_user_id,
                )
                .with_for_update()
            )
            if admin.scalar_one_or_none() is None:
                return Failure(AutomaticProjectDenial.ADMIN_REQUIRED)
            policy = await self.policy_repository.lock_policy(
                session, agent_id=agent_id
            )
            if policy is None:
                return Failure(AutomaticProjectDenial.POLICY_MISSING)
            if policy.revision != expected_revision:
                return Failure(AutomaticProjectDenial.REVISION_CONFLICT)
            replacement = await self.policy_repository.replace_policy(
                session,
                agent_id=agent_id,
                expected_revision=expected_revision,
                paths=paths,
                updated_by_workspace_user_id=workspace_user_id,
            )
            match replacement:
                case Failure():
                    return Failure(AutomaticProjectDenial.REVISION_CONFLICT)
                case Success(replaced):
                    pass
                case _:
                    assert_never(replacement)
            for path in paths:
                await self.catalog_repository.update_status(
                    session,
                    agent_id=agent_id,
                    path=path,
                    patch=AgentProjectCatalogStatusPatch(
                        status=AgentProjectCatalogStatus.AVAILABLE,
                        status_detail=None,
                        checked_at=datetime.now(UTC),
                    ),
                )
            return Success(replaced)

    async def _authorize(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
    ) -> AutomaticProjectDenial | None:
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return AutomaticProjectDenial.AGENT_MISSING
        if agent.workspace_id != workspace_id:
            return AutomaticProjectDenial.FOREIGN_WORKSPACE
        if not await self.admin_repository.is_admin(
            session, agent_id, workspace_user_id
        ):
            return AutomaticProjectDenial.ADMIN_REQUIRED
        return None
