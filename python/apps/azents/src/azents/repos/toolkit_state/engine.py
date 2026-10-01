"""Repository-owned completed operations for Engine Toolkit state."""

import dataclasses
from collections.abc import Callable, Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.engine_tool_state import (
    AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    AGENTS_TOOLKIT_NAMESPACE,
    CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    CLAUDE_RULES_TOOLKIT_NAMESPACE,
    TODO_TOOLKIT_NAMESPACE,
    TODO_TOOLKIT_STATE_NAME,
    TOOL_SEARCH_TOOLKIT_NAMESPACE,
    TOOL_SEARCH_WORKING_SET_STATE_NAME,
    AgentsAppendixDedupeState,
    ClaudeRulesAppendixDedupeState,
    TodoState,
    ToolWorkingSetState,
)
from azents.core.toolkit_state import ToolkitStateIdentity
from azents.rdb.session import SessionManager
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.store import ToolkitStateHandle, ToolkitStateStore


class SessionExecutionOwnerLike(Protocol):
    """Durable Session execution owner fields used for transaction fencing."""

    @property
    def session_id(self) -> str:
        """Return the durable Session identity."""
        ...

    @property
    def owner_generation(self) -> int:
        """Return the durable owner generation."""
        ...


@dataclasses.dataclass
class ToolWorkingSetStore:
    """Own completed deferred-tool working-set operations."""

    session_manager: SessionManager[AsyncSession]
    repository: ToolkitStateRepository | None = None

    def with_session_manager(
        self,
        session_manager: SessionManager[AsyncSession],
    ) -> "ToolWorkingSetStore":
        """Bind operations to a different database authority."""
        return ToolWorkingSetStore(
            session_manager=session_manager,
            repository=self.repository,
        )

    async def load(self, agent_id: str, session_id: str) -> ToolWorkingSetState:
        """Load the current Session working set in a completed transaction."""
        async with self.session_manager() as session:
            return await self.load_in_session(session, agent_id, session_id)

    async def load_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Load the working set for a database-only composing repository."""
        return await self._handle(session, agent_id, session_id).load(
            default_factory=ToolWorkingSetState
        )

    async def activate(
        self,
        agent_id: str,
        session_id: str,
        tool_names: Sequence[str],
    ) -> ToolWorkingSetState:
        """Move ranked search results to the recency front."""
        activated = _unique_tool_names(tool_names)
        return await self._update(
            agent_id,
            session_id,
            lambda current: ToolWorkingSetState(
                tool_names=[
                    *activated,
                    *(name for name in current.tool_names if name not in activated),
                ]
            ),
        )

    async def touch(
        self,
        agent_id: str,
        session_id: str,
        tool_name: str,
    ) -> ToolWorkingSetState:
        """Move an invoked deferred tool to the most-recent position."""
        return await self.activate(agent_id, session_id, [tool_name])

    async def clear(
        self,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Clear working-set recency in a completed transaction."""
        return await self._update(
            agent_id,
            session_id,
            lambda _current: ToolWorkingSetState(),
        )

    async def clear_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Clear recency for a database-only composing repository."""
        return await self._update_in_session(
            session,
            agent_id,
            session_id,
            lambda _current: ToolWorkingSetState(),
        )

    async def _update(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[ToolWorkingSetState], ToolWorkingSetState],
    ) -> ToolWorkingSetState:
        """Apply one completed optimistic state update."""
        async with self.session_manager() as session:
            return await self._update_in_session(
                session,
                agent_id,
                session_id,
                mutator,
            )

    async def _update_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
        mutator: Callable[[ToolWorkingSetState], ToolWorkingSetState],
    ) -> ToolWorkingSetState:
        """Apply one optimistic update for a composing repository."""
        updated: ToolWorkingSetState | None = None

        def capture(current: ToolWorkingSetState) -> ToolWorkingSetState:
            nonlocal updated
            updated = mutator(current)
            return updated

        await self._handle(session, agent_id, session_id).update(
            default_factory=ToolWorkingSetState,
            mutator=capture,
        )
        if updated is None:
            raise RuntimeError("Tool working-set update did not run")
        return updated

    def _handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ToolWorkingSetState]:
        """Create the typed handle for one Agent Session."""
        return ToolkitStateStore(
            session=session,
            repository=self.repository,
        ).handle(
            ToolkitStateIdentity(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=TOOL_SEARCH_TOOLKIT_NAMESPACE,
                state_name=TOOL_SEARCH_WORKING_SET_STATE_NAME,
            ),
            ToolWorkingSetState,
        )


@dataclasses.dataclass
class ToolkitAgentsAppendixDedupeStateStore:
    """Own completed AGENTS.md appendix dedupe operations."""

    session_manager: SessionManager[AsyncSession]

    def for_execution(
        self,
        owner: SessionExecutionOwnerLike,
    ) -> "ToolkitAgentsAppendixDedupeStateStore":
        """Bind dedupe operations to one durable Session owner."""
        return ToolkitAgentsAppendixDedupeStateStore(
            session_manager=OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
        )

    async def load_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
    ) -> AgentsAppendixDedupeState:
        """Fetch dedupe state in a completed transaction."""
        if not agent_id or not session_id:
            return AgentsAppendixDedupeState()
        async with self.session_manager() as session:
            return await self._handle(session, agent_id, session_id).load(
                default_factory=AgentsAppendixDedupeState
            )

    async def replace_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        appended_paths: Sequence[str],
    ) -> None:
        """Replace AGENTS.md dedupe paths in a completed transaction."""
        if not agent_id or not session_id:
            return
        replacement = AgentsAppendixDedupeState(appended_paths=list(appended_paths))
        async with self.session_manager() as session:
            await self._handle(session, agent_id, session_id).update(
                default_factory=AgentsAppendixDedupeState,
                mutator=lambda _current: replacement,
            )

    @staticmethod
    def _handle(
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[AgentsAppendixDedupeState]:
        """Create the typed AGENTS.md dedupe handle."""
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=AGENTS_TOOLKIT_NAMESPACE,
                state_name=AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
            ),
            AgentsAppendixDedupeState,
        )


@dataclasses.dataclass
class ToolkitClaudeRulesAppendixDedupeStateStore:
    """Own completed Claude rules appendix dedupe operations."""

    session_manager: SessionManager[AsyncSession]

    def for_execution(
        self,
        owner: SessionExecutionOwnerLike,
    ) -> "ToolkitClaudeRulesAppendixDedupeStateStore":
        """Bind dedupe operations to one durable Session owner."""
        return ToolkitClaudeRulesAppendixDedupeStateStore(
            session_manager=OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
        )

    async def load_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
    ) -> ClaudeRulesAppendixDedupeState:
        """Fetch dedupe state in a completed transaction."""
        if not agent_id or not session_id:
            return ClaudeRulesAppendixDedupeState()
        async with self.session_manager() as session:
            return await self._handle(session, agent_id, session_id).load(
                default_factory=ClaudeRulesAppendixDedupeState
            )

    async def add_appendix_dedupe_paths(
        self,
        agent_id: str,
        session_id: str,
        appended_paths: Sequence[str],
    ) -> None:
        """Merge Claude rules dedupe paths in a completed transaction."""
        if not agent_id or not session_id:
            return
        paths = set(appended_paths)
        async with self.session_manager() as session:
            await self._handle(session, agent_id, session_id).update(
                default_factory=ClaudeRulesAppendixDedupeState,
                mutator=lambda current: current.model_copy(
                    update={
                        "appended_paths": sorted(set(current.appended_paths) | paths)
                    }
                ),
            )

    async def clear_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Clear Claude rules dedupe paths in a completed transaction."""
        if not agent_id or not session_id:
            return
        cleared = ClaudeRulesAppendixDedupeState()
        async with self.session_manager() as session:
            await self._handle(session, agent_id, session_id).update(
                default_factory=ClaudeRulesAppendixDedupeState,
                mutator=lambda _current: cleared,
            )

    @staticmethod
    def _handle(
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ClaudeRulesAppendixDedupeState]:
        """Create the typed Claude rules dedupe handle."""
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=CLAUDE_RULES_TOOLKIT_NAMESPACE,
                state_name=CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
            ),
            ClaudeRulesAppendixDedupeState,
        )


@dataclasses.dataclass
class TodoStateStore:
    """Own completed Todo state operations."""

    session_manager: SessionManager[AsyncSession]

    def for_execution(
        self,
        owner: SessionExecutionOwnerLike,
    ) -> "TodoStateStore":
        """Bind Todo operations to one durable Session owner."""
        return TodoStateStore(
            session_manager=OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
        )

    async def load(self, agent_id: str, session_id: str) -> TodoState:
        """Fetch Todo state in a completed transaction."""
        async with self.session_manager() as session:
            return await self.load_in_session(session, agent_id, session_id)

    async def load_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> TodoState:
        """Fetch Todo state for a database-only composing repository."""
        if not agent_id or not session_id:
            return TodoState()
        return await self._handle(session, agent_id, session_id).load(
            default_factory=TodoState
        )

    async def replace(
        self,
        agent_id: str,
        session_id: str,
        state: TodoState,
    ) -> TodoState:
        """Replace Todo state with optimistic retry in a completed transaction."""
        if not agent_id or not session_id:
            return TodoState()
        async with self.session_manager() as session:
            await self._handle(session, agent_id, session_id).update(
                default_factory=TodoState,
                mutator=lambda _current: state,
            )
            return state

    @staticmethod
    def _handle(
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[TodoState]:
        """Create the typed Todo state handle."""
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=TODO_TOOLKIT_NAMESPACE,
                state_name=TODO_TOOLKIT_STATE_NAME,
            ),
            TodoState,
        )


def _unique_tool_names(tool_names: Sequence[str]) -> list[str]:
    """Return first-occurrence unique tool names after validation."""
    unique: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        if not name.strip():
            raise ValueError("Tool working-set names cannot be blank")
        if name not in seen:
            unique.append(name)
            seen.add(name)
    return unique
