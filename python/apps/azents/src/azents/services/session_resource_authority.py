"""Canonical authority for internal Session resource operations."""

import dataclasses
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclasses.dataclass(frozen=True)
class SessionExecutionOwner:
    """Durable Session execution ownership required by state-only collaborators."""

    session_id: str
    owner_generation: int


@dataclasses.dataclass(frozen=True)
class SessionResourceAuthority:
    """Validated canonical workload identity for internal resource access."""

    workspace_id: str
    agent_id: str
    session_id: str
    root_session_id: str
    run_id: str
    run_index: int
    owner_generation: int

    @property
    def execution_owner(self) -> SessionExecutionOwner:
        """Return the narrow durable owner token for Session state operations."""
        return SessionExecutionOwner(
            session_id=self.session_id,
            owner_generation=self.owner_generation,
        )


@runtime_checkable
class SessionExecutionOwnerBindable(Protocol):
    """Execution-local collaborator that binds narrow Session ownership."""

    def bind_execution_owner(
        self,
        owner: SessionExecutionOwner,
    ) -> None:
        """Bind exactly one immutable Session execution owner."""
        ...


@runtime_checkable
class SessionExecutionAuthorityBindable(Protocol):
    """Execution-local collaborator that binds durable Session authority."""

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Bind exactly one immutable execution authority."""
        ...


def accepts_execution_authority(
    current: SessionResourceAuthority | None,
    requested: SessionResourceAuthority,
    *,
    agent_id: str,
    session_id: str,
) -> bool:
    """Validate one local execution binding and report whether it is new."""
    if requested.agent_id != agent_id:
        raise ValueError("Execution authority Agent does not match Toolkit")
    if requested.session_id != session_id:
        raise ValueError("Execution authority Session does not match Toolkit")
    if current is None:
        return True
    if current.execution_owner != requested.execution_owner:
        raise ValueError("Toolkit is already bound to another execution owner")
    return current != requested


def accepts_execution_owner(
    current: SessionExecutionOwner | None,
    requested: SessionExecutionOwner,
    *,
    session_id: str,
) -> bool:
    """Validate one narrow execution binding and report whether it is new."""
    if requested.session_id != session_id:
        raise ValueError("Execution owner Session does not match Toolkit")
    if current is None:
        return True
    if current != requested:
        raise ValueError("Toolkit is already bound to another execution owner")
    return False


@dataclasses.dataclass(frozen=True)
class AuthorizedPublicSessionResource:
    """Authorized concrete Session identity and canonical permission root."""

    session: AgentSession
    root_session: AgentSession


@dataclasses.dataclass(frozen=True)
class PublicSessionResourceDenied:
    """The requester lacks access and the caller may disclose denial."""


@dataclasses.dataclass(frozen=True)
class PublicSessionResourceNotFound:
    """The Session is absent or authorization must remain not-found-safe."""


type PublicSessionResourceResult = (
    AuthorizedPublicSessionResource
    | PublicSessionResourceDenied
    | PublicSessionResourceNotFound
)


async def authorize_public_session_resource(
    session: AsyncSession,
    *,
    agent_session: AgentSession,
    user_id: str,
    require_active: bool,
    denied_as_not_found: bool,
    expected_workspace_id: str | None,
    expected_agent_id: str | None,
    agent_session_repository: AgentSessionRepository,
    workspace_user_repository: WorkspaceUserRepository,
) -> PublicSessionResourceResult:
    """Authorize one public resource bound to a concrete Agent Session."""
    if (
        (require_active and agent_session.status is not AgentSessionStatus.ACTIVE)
        or (
            expected_workspace_id is not None
            and agent_session.workspace_id != expected_workspace_id
        )
        or (
            expected_agent_id is not None
            and agent_session.agent_id != expected_agent_id
        )
    ):
        return PublicSessionResourceNotFound()

    root_session = agent_session
    if agent_session.session_kind is AgentSessionKind.SUBAGENT:
        root_agent = (
            await agent_session_repository.get_root_session_agent_by_session_id(
                session,
                agent_session.id,
            )
        )
        if root_agent is None:
            return PublicSessionResourceNotFound()
        loaded_root = await agent_session_repository.get_by_id(
            session,
            root_agent.agent_session_id,
        )
        if loaded_root is None or (
            require_active and loaded_root.status is not AgentSessionStatus.ACTIVE
        ):
            return PublicSessionResourceNotFound()
        root_session = loaded_root
    elif agent_session.session_kind is not AgentSessionKind.ROOT:
        return PublicSessionResourceNotFound()

    workspace_user = await workspace_user_repository.get_by_workspace_and_user(
        session,
        workspace_id=agent_session.workspace_id,
        user_id=user_id,
    )
    if workspace_user is None:
        if (
            denied_as_not_found
            or root_session.product_mode is AgentSessionProductMode.USER
        ):
            return PublicSessionResourceNotFound()
        return PublicSessionResourceDenied()

    if root_session.product_mode is AgentSessionProductMode.TEAM:
        return AuthorizedPublicSessionResource(
            session=agent_session,
            root_session=root_session,
        )
    if (
        root_session.product_mode is AgentSessionProductMode.USER
        and root_session.associated_user_id == user_id
    ):
        return AuthorizedPublicSessionResource(
            session=agent_session,
            root_session=root_session,
        )
    return PublicSessionResourceNotFound()


async def resolve_agent_session_resource(
    session: AsyncSession,
    *,
    agent_session: AgentSession,
    expected_workspace_id: str,
    expected_agent_id: str,
    agent_session_repository: AgentSessionRepository,
) -> AuthorizedPublicSessionResource | PublicSessionResourceNotFound:
    """Resolve an Agent-owned concrete Session without inventing User authority."""
    if (
        agent_session.status is not AgentSessionStatus.ACTIVE
        or agent_session.workspace_id != expected_workspace_id
        or agent_session.agent_id != expected_agent_id
    ):
        return PublicSessionResourceNotFound()
    if agent_session.session_kind is AgentSessionKind.ROOT:
        return AuthorizedPublicSessionResource(
            session=agent_session,
            root_session=agent_session,
        )
    if agent_session.session_kind is not AgentSessionKind.SUBAGENT:
        return PublicSessionResourceNotFound()
    root_agent = await agent_session_repository.get_root_session_agent_by_session_id(
        session,
        agent_session.id,
    )
    if root_agent is None:
        return PublicSessionResourceNotFound()
    root_session = await agent_session_repository.get_by_id(
        session,
        root_agent.agent_session_id,
    )
    if root_session is None or root_session.status is not AgentSessionStatus.ACTIVE:
        return PublicSessionResourceNotFound()
    return AuthorizedPublicSessionResource(
        session=agent_session,
        root_session=root_session,
    )
