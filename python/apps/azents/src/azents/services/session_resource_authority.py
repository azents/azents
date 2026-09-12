"""Canonical authority for internal Session resource operations."""

import dataclasses
from typing import Protocol, runtime_checkable


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
