"""Repository-owned completed operations for Engine Toolkit state."""

import dataclasses
from collections.abc import Callable, Sequence

from azents.core.engine_tool_state import (
    AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    AGENTS_TOOLKIT_NAMESPACE,
    CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    CLAUDE_RULES_TOOLKIT_NAMESPACE,
    GITHUB_SELECTED_INSTALLATION_STATE_NAME,
    GITHUB_TOOLKIT_STATE_NAMESPACE,
    TODO_TOOLKIT_NAMESPACE,
    TODO_TOOLKIT_STATE_NAME,
    TOOL_SEARCH_TOOLKIT_NAMESPACE,
    TOOL_SEARCH_WORKING_SET_STATE_NAME,
    AgentsAppendixDedupeState,
    ClaudeRulesAppendixDedupeState,
    GitHubSelectedInstallationState,
    McpToolSnapshotState,
    TodoState,
    ToolWorkingSetState,
)
from azents.core.toolkit_state import ToolkitStateIdentity
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.store import ToolkitStateHandle, ToolkitStateStore


@dataclasses.dataclass
class ToolWorkingSetStore:
    """Own completed deferred-tool working-set operations."""

    session_manager: SessionManager[WriteSession]
    repository: ToolkitStateRepository | None = None

    def with_session_manager(
        self,
        session_manager: SessionManager[WriteSession],
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
        session: ReadSession,
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
        session: WriteSession,
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
        session: WriteSession,
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

    def _handle[S: ReadSession](
        self,
        session: S,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ToolWorkingSetState, S]:
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

    session_manager: SessionManager[WriteSession]

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
    def _handle[S: ReadSession](
        session: S,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[AgentsAppendixDedupeState, S]:
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

    session_manager: SessionManager[WriteSession]

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
    def _handle[S: ReadSession](
        session: S,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ClaudeRulesAppendixDedupeState, S]:
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

    session_manager: SessionManager[WriteSession]

    async def load(self, agent_id: str, session_id: str) -> TodoState:
        """Fetch Todo state in a completed transaction."""
        async with self.session_manager() as session:
            return await self.load_in_session(session, agent_id, session_id)

    async def load_in_session(
        self,
        session: ReadSession,
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
    def _handle[S: ReadSession](
        session: S,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[TodoState, S]:
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


@dataclasses.dataclass
class McpToolSnapshotStore:
    """Own completed MCP tool snapshot operations."""

    session_manager: SessionManager[WriteSession] | None
    read_session_manager: SessionManager[ReadSession] | None
    agent_id: str
    session_id: str
    toolkit_namespace: str
    state_name: str

    async def load(self) -> McpToolSnapshotState | None:
        """Load one snapshot in a completed transaction."""
        if not self._available():
            return None
        assert self.read_session_manager is not None  # noqa: S101
        async with self.read_session_manager() as session:
            return await self._handle(session).load(
                default_factory=McpToolSnapshotState
            )

    async def replace(self, snapshot: McpToolSnapshotState) -> None:
        """Replace one snapshot in a completed transaction."""
        if not self._available():
            return
        assert self.session_manager is not None  # noqa: S101
        async with self.session_manager() as session:
            await self._handle(session).save(snapshot)

    def with_identity(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> "McpToolSnapshotStore":
        """Return the same repository operation for another state identity."""
        return dataclasses.replace(
            self,
            agent_id=agent_id,
            session_id=session_id,
        )

    def _available(self) -> bool:
        """Return whether persistence and state identity are available."""
        return (
            self.session_manager is not None
            and self.read_session_manager is not None
            and bool(self.agent_id)
            and bool(self.session_id)
        )

    def _handle[S: ReadSession](
        self,
        session: S,
    ) -> ToolkitStateHandle[McpToolSnapshotState, S]:
        """Create the typed MCP snapshot handle."""
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=self.agent_id,
                session_id=self.session_id,
                toolkit_namespace=self.toolkit_namespace,
                state_name=self.state_name,
            ),
            McpToolSnapshotState,
        )


@dataclasses.dataclass
class GitHubSelectedInstallationStore:
    """Own completed GitHub selected-installation operations."""

    session_manager: SessionManager[WriteSession]
    read_session_manager: SessionManager[ReadSession]
    agent_id: str
    session_id: str

    async def load(self) -> str | None:
        """Load the selected installation in a completed transaction."""
        if not self.agent_id or not self.session_id:
            return None
        async with self.read_session_manager() as session:
            state = await self._handle(session).load(
                default_factory=lambda: GitHubSelectedInstallationState(
                    installation_id="__unset__"
                )
            )
        if state.installation_id == "__unset__":
            return None
        return state.installation_id

    async def save(self, installation_id: str) -> None:
        """Persist the selected installation in a completed transaction."""
        if not self.agent_id or not self.session_id:
            return
        async with self.session_manager() as session:
            await self._handle(session).save(
                GitHubSelectedInstallationState(installation_id=installation_id)
            )

    def _handle[S: ReadSession](
        self,
        session: S,
    ) -> ToolkitStateHandle[GitHubSelectedInstallationState, S]:
        """Create the typed selected-installation handle."""
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=self.agent_id,
                session_id=self.session_id,
                toolkit_namespace=GITHUB_TOOLKIT_STATE_NAMESPACE,
                state_name=GITHUB_SELECTED_INSTALLATION_STATE_NAME,
            ),
            GitHubSelectedInstallationState,
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
