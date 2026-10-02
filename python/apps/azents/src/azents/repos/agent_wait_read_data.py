"""Detached descendant facts for the application wait predicate."""

from dataclasses import dataclass

from azents.engine.events.types import AgentRunState
from azents.repos.agent_session.data import AgentSession


@dataclass(frozen=True)
class AgentWaitDescendantState:
    """One descendant in the original path order with its durable state."""

    session_id: str
    path: str
    session: AgentSession | None
    run: AgentRunState | None


@dataclass(frozen=True)
class AgentWaitDescendantSnapshot:
    """Completed descendant read, including the explicit empty/missing result."""

    descendants: tuple[AgentWaitDescendantState, ...]
