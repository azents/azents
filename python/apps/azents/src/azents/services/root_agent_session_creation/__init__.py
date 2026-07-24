"""Shared root AgentSession creation service."""

import dataclasses
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionKind
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_automatic_project.data import AgentAutomaticProjectPolicy
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.services.session_workspace_project import (
    normalize_session_workspace_project_paths,
)

from .data import (
    AgentDefaultRootWorkspaceIntent,
    ExplicitRootWorkspaceIntent,
    RootAgentSessionCreationResult,
    RootWorkspaceIntent,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class _ResolvedRootWorkspace:
    """Resolved Project paths and optional policy provenance."""

    project_paths: tuple[str, ...]
    policy_revision: int | None


@dataclasses.dataclass
class RootAgentSessionCreationService:
    """Create root Session context Project snapshots without committing."""

    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    automatic_project_repository: Annotated[
        AgentAutomaticProjectRepository,
        Depends(AgentAutomaticProjectRepository),
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]

    async def create_root_session(
        self,
        session: AsyncSession,
        *,
        create: AgentSessionCreate,
        workspace_intent: RootWorkspaceIntent,
    ) -> RootAgentSessionCreationResult:
        """Create one non-racing root Session and its Project snapshot."""
        if create.session_kind is not AgentSessionKind.ROOT:
            raise ValueError("Root AgentSession creation requires a root Session")
        if create.primary_kind is not None:
            raise ValueError("Team-primary creation requires ensure_team_primary")
        resolved_workspace = await self._resolve_workspace_intent(
            session,
            agent_id=create.agent_id,
            workspace_intent=workspace_intent,
        )
        agent_session = await self.agent_session_repository.create(session, create)
        await self._create_projects(
            session,
            session_id=agent_session.id,
            project_paths=resolved_workspace.project_paths,
        )
        return RootAgentSessionCreationResult(
            agent_session=agent_session,
            created=True,
            initial_project_paths=resolved_workspace.project_paths,
            policy_revision=resolved_workspace.policy_revision,
        )

    async def ensure_team_primary(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> RootAgentSessionCreationResult:
        """Ensure team primary and snapshot policy only for its insert winner."""
        ensured = await self.agent_session_repository.ensure_team_primary_for_agent(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        if not ensured.created:
            projects = await self.session_workspace_project_repository.list_projects(
                session,
                session_id=ensured.session.id,
            )
            return RootAgentSessionCreationResult(
                agent_session=ensured.session,
                created=False,
                initial_project_paths=tuple(project.path for project in projects),
                policy_revision=None,
            )

        policy = await self._require_automatic_project_policy(
            session,
            agent_id=agent_id,
        )
        await self._create_projects(
            session,
            session_id=ensured.session.id,
            project_paths=policy.project_paths,
        )
        return RootAgentSessionCreationResult(
            agent_session=ensured.session,
            created=True,
            initial_project_paths=policy.project_paths,
            policy_revision=policy.revision,
        )

    async def _resolve_workspace_intent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        workspace_intent: RootWorkspaceIntent,
    ) -> _ResolvedRootWorkspace:
        """Resolve explicit or Agent-default Project paths before row creation."""
        match workspace_intent:
            case ExplicitRootWorkspaceIntent(existing_project_paths=paths):
                return _ResolvedRootWorkspace(
                    project_paths=tuple(
                        normalize_session_workspace_project_paths(paths)
                    ),
                    policy_revision=None,
                )
            case AgentDefaultRootWorkspaceIntent():
                policy = await self._require_automatic_project_policy(
                    session,
                    agent_id=agent_id,
                )
                return _ResolvedRootWorkspace(
                    project_paths=policy.project_paths,
                    policy_revision=policy.revision,
                )
            case _:
                assert_never(workspace_intent)

    async def _require_automatic_project_policy(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentAutomaticProjectPolicy:
        """Return the required per-Agent automatic Project policy row."""
        policy = await self.automatic_project_repository.get_policy(
            session,
            agent_id=agent_id,
        )
        if policy is None:
            raise RuntimeError("Agent automatic Project policy is missing")
        return policy

    async def _create_projects(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        project_paths: tuple[str, ...],
    ) -> None:
        """Persist root context Project rows in caller-owned transaction."""
        for path in project_paths:
            await self.session_workspace_project_repository.create_project(
                session,
                SessionWorkspaceProjectCreate(session_id=session_id, path=path),
            )
