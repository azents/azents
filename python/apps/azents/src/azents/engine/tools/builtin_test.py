"""BuiltinToolkit/RuntimeToolkit update_context() and handler tests."""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.enums import (
    EventKind,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.tools import ShellToolkitConfig, ToolkitState, TurnContext
from azents.engine.events.engine_events import (
    RuntimeProcessOutputDeltaEvent,
    RuntimeReadyEvent,
)
from azents.engine.events.types import ClientToolResultPayload, Event
from azents.engine.hooks.types import SessionCompactHookContext
from azents.engine.run.emit import PublishedEvent, durable, handle_engine_event
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tools import builtin as builtin_module
from azents.engine.tools.builtin import BuiltinToolkit, RuntimeToolkit
from azents.engine.tools.builtin_agents import (
    AGENTS_LIVE_READ_INTERVAL_TURNS,
    ProjectAgentsInstructionState,
    RootAgentsInstructionState,
)
from azents.engine.tools.edit import make_edit_tool
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.runtime_io import (
    RuntimeBashResult,
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileReadResult,
    RuntimeFileStatResult,
    RuntimeFileWriteResult,
    RuntimeGrepFileMatch,
    RuntimeGrepLineMatch,
    RuntimeGrepResult,
    RuntimeProcessOutputDelta,
    RuntimeProcessResult,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationUnavailable,
)
from azents.engine.tools.testing import FakeSharedStorage
from azents.engine.tools.write import make_write_tool
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemorySummary
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    *,
    user_id: str | None = "user-1",
    workspace_id: str = "ws-1",
    model: str = "test-model",
    run_id: str = "run-1",
) -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id=user_id,
        workspace_id=workspace_id,
        model=model,
        run_id=run_id,
        publish_event=AsyncMock(),
    )


def _make_mock_session_manager() -> SessionManager[AsyncMock]:
    """Create session_manager for tests."""

    @asynccontextmanager
    async def _session_manager() -> AsyncGenerator[AsyncMock, None]:
        yield AsyncMock()

    return _session_manager


def _make_mock_memory_repo(
    agent_summaries: list[MemorySummary] | None = None,
    user_summaries: list[MemorySummary] | None = None,
) -> MemoryRepository:
    """Create MemoryRepository mock for tests."""
    repo = AsyncMock(spec=MemoryRepository)

    async def _list_summaries(
        session: object,  # noqa: ARG001
        *,
        agent_id: str,  # noqa: ARG001
        user_id: str | None,
        type: str | None = None,  # noqa: ARG001
    ) -> list[MemorySummary]:
        if user_id is None:
            return agent_summaries or []
        return user_summaries or []

    repo.list_summaries = _list_summaries
    return repo


def _make_runtime_repo(
    *,
    runtime_id: str = "runtime-1",
    desired_state: RuntimeDesiredState = RuntimeDesiredState.RUNNING,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.CONNECTED
    ),
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
) -> AgentRuntimeRepository:
    """Create AgentRuntimeRepository mock for tests."""
    repo = AsyncMock(spec=AgentRuntimeRepository)
    repo.get_by_agent_id.return_value = SimpleNamespace(
        id=runtime_id,
        desired_state=desired_state,
        provider_connection_state=provider_connection_state,
        provider_observed_state=provider_observed_state,
        runner_state=runner_state,
        runner_generation=1,
    )
    return repo


class _FakeAgentsInstructionStateStore:
    """AGENTS.md instruction state store for tests."""

    def __init__(self) -> None:
        self.root_states: dict[tuple[str, str], RootAgentsInstructionState] = {}
        self.project_states: dict[tuple[str, str], ProjectAgentsInstructionState] = {}

    async def load_root(
        self, agent_id: str, session_id: str
    ) -> RootAgentsInstructionState:
        """Return stored root state."""
        return self.root_states.get(
            (agent_id, session_id), RootAgentsInstructionState()
        )

    async def save_root(
        self, agent_id: str, session_id: str, state: RootAgentsInstructionState
    ) -> None:
        """Store root state."""
        self.root_states[(agent_id, session_id)] = state

    async def update_root(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[RootAgentsInstructionState], RootAgentsInstructionState],
    ) -> None:
        """Apply root state update."""
        state = await self.load_root(agent_id, session_id)
        await self.save_root(agent_id, session_id, mutator(state))

    async def load_project(
        self, agent_id: str, session_id: str
    ) -> ProjectAgentsInstructionState:
        """Return stored project state."""
        return self.project_states.get(
            (agent_id, session_id), ProjectAgentsInstructionState()
        )

    async def save_project(
        self,
        agent_id: str,
        session_id: str,
        state: ProjectAgentsInstructionState,
    ) -> None:
        """Store project state."""
        self.project_states[(agent_id, session_id)] = state

    async def update_project(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[
            [ProjectAgentsInstructionState], ProjectAgentsInstructionState
        ],
    ) -> None:
        """Apply project state update."""
        state = await self.load_project(agent_id, session_id)
        await self.save_project(agent_id, session_id, mutator(state))


class _FakeRunnerOperations:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.bash_calls: list[dict[str, object]] = []
        self.process_start_calls: list[dict[str, object]] = []
        self.process_write_calls: list[dict[str, object]] = []
        self.stat_calls: list[str] = []
        self.stat_started_event: asyncio.Event | None = None
        self.stat_continue_event: asyncio.Event | None = None
        self.bash_unavailable_message: str | None = None
        self.process_unavailable_message: str | None = None
        self.next_process_start_result = RuntimeProcessResult(
            process_id="proc-1",
            status="exited_unread",
            exit_code=0,
            stdout="hello\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_omitted_bytes=0,
            stderr_omitted_bytes=0,
            missing_reason=None,
            final_cursor="0-1",
        )
        self.next_process_write_result = RuntimeProcessResult(
            process_id="proc-1",
            status="running",
            exit_code=None,
            stdout="tick\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_omitted_bytes=0,
            stderr_omitted_bytes=0,
            missing_reason=None,
            final_cursor="0-2",
        )

    def add_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    async def run_bash(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        command: str,
        timeout_seconds: int,
        env: dict[str, str] | None,
        deadline_at: datetime,
        cancel_check: object | None = None,
    ) -> RuntimeBashResult:
        del runtime_id, runner_generation, timeout_seconds, deadline_at, cancel_check
        self.bash_calls.append({"command": command, "env": env})
        if self.bash_unavailable_message is not None:
            raise RuntimeRunnerOperationUnavailable(self.bash_unavailable_message)
        env_values = env or {}
        if "MY_TEST_KEY" in env_values:
            return RuntimeBashResult(
                stdout=f"{env_values['MY_TEST_KEY']}\n",
                stderr="",
                exit_code=0,
                final_cursor="0-1",
            )
        if command == "pwd":
            return RuntimeBashResult(
                stdout="/workspace/agent\n",
                stderr="",
                exit_code=0,
                final_cursor="0-1",
            )
        if "hello" in command:
            return RuntimeBashResult(
                stdout="hello\n",
                stderr="",
                exit_code=0,
                final_cursor="0-1",
            )
        return RuntimeBashResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            final_cursor="0-1",
        )

    async def start_process(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        command: str,
        workdir: str | None,
        yield_time_ms: int,
        max_output_bytes: int,
        env: dict[str, str] | None,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: object | None = None,
    ) -> RuntimeProcessResult:
        del runtime_id, runner_generation, deadline_at
        self.process_start_calls.append(
            {
                "command": command,
                "workdir": workdir,
                "yield_time_ms": yield_time_ms,
                "max_output_bytes": max_output_bytes,
                "env": env,
                "owner_session_id": owner_session_id,
                "process_output_callback": process_output_callback,
            }
        )
        if self.process_unavailable_message is not None:
            raise RuntimeRunnerOperationUnavailable(self.process_unavailable_message)
        return self.next_process_start_result

    async def write_process_stdin(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        process_id: str,
        stdin: str,
        yield_time_ms: int,
        max_output_bytes: int,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: object | None = None,
    ) -> RuntimeProcessResult:
        del runtime_id, runner_generation, deadline_at
        self.process_write_calls.append(
            {
                "process_id": process_id,
                "stdin": stdin,
                "yield_time_ms": yield_time_ms,
                "max_output_bytes": max_output_bytes,
                "owner_session_id": owner_session_id,
                "process_output_callback": process_output_callback,
            }
        )
        if self.process_unavailable_message is not None:
            raise RuntimeRunnerOperationUnavailable(self.process_unavailable_message)
        return self.next_process_write_result

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        del runtime_id, runner_generation, deadline_at
        data = self.files[path]
        chunk = (
            data[offset:] if max_bytes is None else data[offset : offset + max_bytes]
        )
        return RuntimeFileReadResult(data=chunk, final_cursor="0-1")

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        del runtime_id, runner_generation, deadline_at
        if self.stat_started_event is not None:
            self.stat_started_event.set()
        if self.stat_continue_event is not None:
            await self.stat_continue_event.wait()
        self.stat_calls.append(path)
        data = self.files.get(path)
        if data is not None:
            return RuntimeFileStatResult(
                path=path,
                kind="file",
                size_bytes=len(data),
                symlink=False,
                real_path=None,
                resolved_kind=None,
                final_cursor="0-1",
            )
        prefix = path.rstrip("/") + "/"
        if any(
            path.startswith(f"{file_path}/")
            for file_path in self.files
            if "/" not in path[len(file_path) + 1 :]
        ):
            raise RuntimeRunnerOperationFailedError(
                f"STAT_FAILED: [Errno 20] Not a directory: {path}"
            )
        if any(file_path.startswith(prefix) for file_path in self.files):
            return RuntimeFileStatResult(
                path=path,
                kind="directory",
                size_bytes=None,
                symlink=False,
                real_path=None,
                resolved_kind=None,
                final_cursor="0-1",
            )
        raise RuntimeRunnerOperationFailedError(f"NOT_FOUND: No such file: {path}")

    async def write_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        data: bytes,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        del runtime_id, runner_generation, deadline_at
        self.files[path] = data
        return RuntimeFileWriteResult(bytes_written=len(data), final_cursor="0-1")

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        del runtime_id, runner_generation, recursive, exclude_patterns, deadline_at
        prefix = path.rstrip("/") + "/"
        children: dict[str, RuntimeFileListEntry] = {}
        for file_path, data in self.files.items():
            if not file_path.startswith(prefix):
                continue
            remainder = file_path[len(prefix) :]
            child_name = remainder.split("/", 1)[0]
            child_path = f"{prefix}{child_name}"
            children[child_path] = RuntimeFileListEntry(
                path=child_path,
                type="directory" if "/" in remainder else "file",
                size_bytes=None if "/" in remainder else len(data),
            )
        return RuntimeFileListResult(
            entries=tuple(children.values()),
            final_cursor="0-1",
        )

    async def grep_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeGrepResult:
        del (
            runtime_id,
            runner_generation,
            recursive,
            exclude_patterns,
            max_matching_files,
            max_lines_per_file,
            max_searched_files,
            max_scanned_bytes,
            deadline_at,
        )
        matches: list[RuntimeGrepFileMatch] = []
        for file_path, data in self.files.items():
            if not file_path.startswith(path.rstrip("/") + "/"):
                continue
            text = data.decode("utf-8")
            lines = [
                RuntimeGrepLineMatch(line_number=index, text=line)
                for index, line in enumerate(text.splitlines(), start=1)
                if pattern in line
            ]
            if lines:
                matches.append(
                    RuntimeGrepFileMatch(
                        path=file_path,
                        lines=tuple(lines),
                        truncated=False,
                    )
                )
        return RuntimeGrepResult(
            files=tuple(matches),
            searched_file_count=len(self.files),
            matched_file_count=len(matches),
            truncated=False,
            stopped_reason=None,
            final_cursor="0-1",
        )


def _make_toolkit(
    config: ShellToolkitConfig | None = None,
    *,
    agent_id: str = "agent-1",
    session_id: str = "session-1",
    desired_state: RuntimeDesiredState = RuntimeDesiredState.RUNNING,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.CONNECTED
    ),
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
    storage_files: dict[str, bytes] | None = None,
    projects: list[SessionWorkspaceProject] | None = None,
    agents_store: _FakeAgentsInstructionStateStore | None = None,
) -> RuntimeToolkit:
    """Create RuntimeToolkit for tests."""
    runner_operations = _FakeRunnerOperations(storage_files)
    session_manager = _make_mock_session_manager()
    agent_runtime_repo: AgentRuntimeRepository | None = AsyncMock(
        spec=AgentRuntimeRepository
    )
    agent_runtime_repo.get_by_agent_id.return_value = SimpleNamespace(
        id="runtime-1",
        desired_state=desired_state,
        provider_connection_state=provider_connection_state,
        provider_observed_state=provider_observed_state,
        runner_state=runner_state,
        runner_generation=1,
    )
    project_repo: SessionWorkspaceProjectRepository | None = None
    if projects is not None:
        project_repo = AsyncMock(spec=SessionWorkspaceProjectRepository)
        project_repo.list_projects.return_value = projects
    if agents_store is None:
        agents_store = _FakeAgentsInstructionStateStore()

    toolkit = RuntimeToolkit(
        config=config or ShellToolkitConfig(),
        exchange_file_service=AsyncMock(spec=ExchangeFileService),
        artifact_service=AsyncMock(spec=ArtifactService),
        model_file_service=AsyncMock(),
        agent_id=agent_id,
        runner_operations=cast(Any, runner_operations),
        session_manager=session_manager,
        agent_runtime_repo=agent_runtime_repo,
        project_repo=project_repo,
        agents_store=cast(Any, agents_store),
    )
    toolkit.set_session_id(session_id)
    cast(Any, toolkit)._test_runner_operations = runner_operations
    cast(Any, toolkit)._test_agent_runtime_repo = agent_runtime_repo
    return toolkit


async def _drain_agents_refresh(toolkit: RuntimeToolkit) -> None:
    """Wait until AGENTS.md background refresh task completes for tests."""
    task = cast(Any, toolkit)._agents_refresh_task
    if task is not None:
        await task


def _make_project(*, path: str) -> SessionWorkspaceProject:
    """Create SessionWorkspaceProject for tests."""
    now = datetime.now(UTC)
    return SessionWorkspaceProject(
        id=f"project-{path.rsplit('/', maxsplit=1)[-1]}",
        session_id="session-1",
        path=path,
        created_at=now,
        updated_at=now,
    )


def _make_builtin_toolkit(
    config: ShellToolkitConfig | None = None,
    *,
    agent_id: str = "agent-1",
    session_id: str = "session-1",
    session_manager: SessionManager[AsyncMock] | None = None,
    memory_repo: MemoryRepository | None = None,
    agent_runtime_repo: AgentRuntimeRepository | None = None,
    agents_store: _FakeAgentsInstructionStateStore | None = None,
) -> BuiltinToolkit:
    """Create BuiltinToolkit for tests."""
    toolkit = BuiltinToolkit(
        config=config or ShellToolkitConfig(),
        agent_id=agent_id,
        session_manager=session_manager,
        memory_repo=memory_repo,
        agent_runtime_repo=agent_runtime_repo,
        agents_store=agents_store,
    )
    toolkit.set_session_id(session_id)
    return toolkit


# ---------------------------------------------------------------------------
# update_context() default behavior tests
# ---------------------------------------------------------------------------


class TestRuntimeToolkitUpdateContext:
    """RuntimeToolkit.update_context() unit tests."""

    @pytest.mark.asyncio
    async def test_returns_toolkit_state(self) -> None:
        """Check that update_context returns ToolkitState."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert isinstance(state, ToolkitState)

    @pytest.mark.asyncio
    async def test_tools_not_empty(self) -> None:
        """Check that tool list is not empty with default settings."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert len(state.tools) > 0

    @pytest.mark.asyncio
    async def test_includes_core_tools(self) -> None:
        """Check that core tools are included."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        names = {t.spec.name for t in state.tools}
        assert "exec_command" in names
        assert "write_stdin" in names
        assert "bash" not in names
        assert "read" in names
        assert "write" in names
        assert "edit" in names
        assert "glob" in names
        assert "grep" in names
        assert "import_file" in names
        assert "present_file" in names

    @pytest.mark.asyncio
    async def test_prompt_includes_runtime_files(self) -> None:
        """Check that prompt includes Runtime Files section."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "Runtime Files" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_agent_workspace_path(self) -> None:
        """Prompt includes /workspace/agent path."""
        toolkit = _make_toolkit(agent_id="agent-1")
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "/workspace/agent/" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_exchange_tools_when_user_id(self) -> None:
        """When user_id exists, exchange tool guidance is included."""
        toolkit = _make_toolkit()
        ctx = _make_context(user_id="user-1")
        state = await toolkit.update_context(ctx)
        assert "import_file" in state.prompt
        assert "present_file" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_excludes_legacy_data_paths(self) -> None:
        """runtime prompt does not guide legacy /data path."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "/data/" not in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_registered_projects(self) -> None:
        """Registered Project list and root guidance are included in prompt."""
        toolkit = _make_toolkit(
            projects=[
                _make_project(path="/workspace/agent/azents"),
                _make_project(path="/workspace/agent/admin"),
            ]
        )
        ctx = _make_context()

        state = await toolkit.update_context(ctx)

        assert "Registered Projects" in state.prompt
        assert "`/workspace/agent/azents`" in state.prompt
        assert "`/workspace/agent/admin`" in state.prompt
        assert "`/workspace/agent` itself is not a Project" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_omits_project_section_when_empty(self) -> None:
        """Do not display registered Project section when Project is absent."""
        toolkit = _make_toolkit(projects=[])
        ctx = _make_context()

        state = await toolkit.update_context(ctx)

        assert "Registered Projects" not in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_loaded_after_project_file_access(self) -> None:
        """Project AGENTS is included after loaded Project file access."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md": b"PROJECT_AGENT_RULE",
                "/workspace/agent/app/src/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/src/file.py"}',
            )
        )
        state = await toolkit.update_context(_make_context())
        assert "Project Instructions" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "Project Instructions" in state.prompt
        assert "/workspace/agent/app/AGENTS.md" in state.prompt
        assert "PROJECT_AGENT_RULE" in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_cache_miss_refresh_does_not_block_prompt(
        self,
    ) -> None:
        """Cache miss live read runs in background and does not block update_context."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md": b"PROJECT_AGENT_RULE",
                "/workspace/agent/app/src/file.py": b"print('hi')",
            },
        )
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        stat_started = asyncio.Event()
        stat_continue = asyncio.Event()
        runner_operations.stat_started_event = stat_started
        runner_operations.stat_continue_event = stat_continue
        await toolkit.update_context(_make_context())
        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/src/file.py"}',
            )
        )

        state = await toolkit.update_context(_make_context())
        await asyncio.wait_for(stat_started.wait(), timeout=1)

        assert "Project Instructions" not in state.prompt
        assert cast(Any, toolkit)._agents_refresh_task is not None

        stat_continue.set()
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "PROJECT_AGENT_RULE" in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_ignores_directory_named_agents_md(self) -> None:
        """Do not read AGENTS.md candidate when it is not a file."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md/nested.txt": b"NOT_A_RULE",
                "/workspace/agent/app/src/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/src/file.py"}',
            )
        )
        state = await toolkit.update_context(_make_context())
        assert "NOT_A_RULE" not in state.prompt
        assert "Project Instructions" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "NOT_A_RULE" not in state.prompt
        assert "Project Instructions" not in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_prunes_missing_candidates_from_active_state(
        self,
    ) -> None:
        """Do not leave nonexistent AGENTS candidate in active/cache state."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/src/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/src/file.py"}',
            )
        )
        await _drain_agents_refresh(toolkit)

        store = cast(_FakeAgentsInstructionStateStore, cast(Any, toolkit)._agents_store)
        state = await store.load_project("agent-1", "session-1")
        assert state.active_project_paths == set()
        assert state.project_contents == {}

    @pytest.mark.asyncio
    async def test_project_agents_ignores_not_directory_stat_failures(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Silently ignore not-directory stat failure for AGENTS candidate."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
                "/workspace/agent/app/frontend/src/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="grep",
                args_json=(
                    '{"path": "/workspace/agent/app/frontend/src/file.py", '
                    '"pattern": "hi"}'
                ),
            )
        )
        state = await toolkit.update_context(_make_context())
        assert "Project Instructions" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )

        assert "PROJECT_RULE" in state.prompt
        assert "file.py/AGENTS.md" not in state.prompt
        assert "/workspace/agent/app/frontend/src/file.py/AGENTS.md" in (
            runner_operations.stat_calls
        )
        assert "Failed to read project AGENTS.md" not in caplog.text

    @pytest.mark.asyncio
    async def test_project_agents_ignored_outside_loaded_project(self) -> None:
        """AGENTS in unregistered folder is not included in prompt."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/unregistered/AGENTS.md": b"SHOULD_NOT_APPEAR",
                "/workspace/agent/unregistered/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/unregistered/file.py"}',
            )
        )
        state = await toolkit.update_context(_make_context())

        assert "SHOULD_NOT_APPEAR" not in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_refresh_existing_active_file(self) -> None:
        """Active AGENTS file reflects changed content on next turn refresh."""
        files = {"/workspace/agent/app/AGENTS.md": b"OLD_RULE"}
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files=files,
        )
        await toolkit.update_context(_make_context())
        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            )
        )
        state = await toolkit.update_context(_make_context())
        assert "OLD_RULE" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())
        assert "OLD_RULE" in state.prompt

        cast(Any, toolkit)._test_runner_operations.files[
            "/workspace/agent/app/AGENTS.md"
        ] = b"NEW_RULE"
        cast(
            Any, toolkit
        )._agents_turns_since_live_read = AGENTS_LIVE_READ_INTERVAL_TURNS
        state = await toolkit.update_context(_make_context())
        assert "OLD_RULE" in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "NEW_RULE" in state.prompt
        assert "OLD_RULE" not in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_compaction_clears_project_instruction_state(
        self,
    ) -> None:
        """compaction hook clears all Project AGENTS active/cache state."""
        files = {"/workspace/agent/app/AGENTS.md": b"OLD_RULE"}
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files=files,
        )
        await toolkit.update_context(_make_context())
        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            )
        )
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())
        assert "OLD_RULE" in state.prompt

        hook = toolkit.hooks().get("on_session_compact")
        assert hook is not None
        await hook(
            SessionCompactHookContext(
                workspace_id="ws-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
            )
        )
        state = await toolkit.update_context(_make_context())

        assert "OLD_RULE" not in state.prompt
        store = cast(_FakeAgentsInstructionStateStore, cast(Any, toolkit)._agents_store)
        saved_state = await store.load_project("agent-1", "session-1")
        assert saved_state.active_project_paths == set()
        assert saved_state.project_contents == {}

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            )
        )
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())
        assert "OLD_RULE" in state.prompt

    @pytest.mark.asyncio
    async def test_directory_tool_activates_nested_agents(self) -> None:
        """directory tool enables ancestor AGENTS up to target directory."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
                "/workspace/agent/app/frontend/AGENTS.md": b"FRONTEND_RULE",
                "/workspace/agent/app/frontend/src/AGENTS.md": b"SRC_RULE",
            },
        )
        await toolkit.update_context(_make_context())

        await toolkit.on_before_tool_call(
            MagicMock(
                tool_name="grep",
                args_json=(
                    '{"path": "/workspace/agent/app/frontend/src", "pattern": "TODO"}'
                ),
            )
        )
        state = await toolkit.update_context(_make_context())
        assert "Project Instructions" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "PROJECT_RULE" in state.prompt
        assert "FRONTEND_RULE" in state.prompt
        assert "SRC_RULE" in state.prompt

    @pytest.mark.asyncio
    async def test_project_agents_prompt_omits_over_budget_files(self) -> None:
        """Items exceeding Project AGENTS prompt budget are omitted from prompt."""
        storage_files = {
            f"/workspace/agent/app/dir-{index}/AGENTS.md": f"RULE_{index}".encode()
            for index in range(25)
        }
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files=storage_files,
        )
        await toolkit.update_context(_make_context())

        for index in range(25):
            await toolkit.on_before_tool_call(
                MagicMock(
                    tool_name="read",
                    args_json=json.dumps(
                        {"path": f"/workspace/agent/app/dir-{index}/file.py"}
                    ),
                )
            )
        state = await toolkit.update_context(_make_context())
        assert "Project Instructions" not in state.prompt
        await _drain_agents_refresh(toolkit)
        state = await toolkit.update_context(_make_context())

        assert "RULE_0" in state.prompt
        assert "additional AGENTS.md instruction file(s) were omitted" in state.prompt


# ---------------------------------------------------------------------------
# Skill prompt tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Memory prompt tests
# ---------------------------------------------------------------------------


class TestBuiltinToolkitMemoryPrompt:
    """Test whether memory information is included in prompt from update_context()."""

    @pytest.mark.asyncio
    async def test_memory_enabled_includes_memory_rules(self) -> None:
        """When memory_enabled=True, memory rules are included in prompt."""
        config = ShellToolkitConfig(memory_enabled=True)
        toolkit = _make_builtin_toolkit(
            config=config,
            session_manager=_make_mock_session_manager(),
            memory_repo=_make_mock_memory_repo(),
        )
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "Memories" in state.prompt
        assert "Memory Rules" in state.prompt

    @pytest.mark.asyncio
    async def test_memory_disabled_excludes_memory(self) -> None:
        """When memory_enabled=False, there is no memory-related prompt."""
        config = ShellToolkitConfig(memory_enabled=False)
        toolkit = _make_builtin_toolkit(config=config)
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "Memories" not in state.prompt

    @pytest.mark.asyncio
    async def test_memory_index_included(self) -> None:
        """When agent memory exists, index content is included in prompt."""
        config = ShellToolkitConfig(memory_enabled=True)
        toolkit = _make_builtin_toolkit(
            config=config,
            session_manager=_make_mock_session_manager(),
            memory_repo=_make_mock_memory_repo(
                agent_summaries=[
                    MemorySummary(
                        name="my-project",
                        type="project",
                        description="my project description",
                    ),
                ],
            ),
        )
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "my-project" in state.prompt
        assert "my project description" in state.prompt

    @pytest.mark.asyncio
    async def test_builtin_toolkit_excludes_runtime_tools(self) -> None:
        """BuiltinToolkit does not expose shell/file tools."""
        toolkit = BuiltinToolkit(
            config=ShellToolkitConfig(memory_enabled=True),
            agent_id="agent-1",
            session_manager=_make_mock_session_manager(),
            memory_repo=_make_mock_memory_repo(),
        )
        ctx = _make_context()

        state = await toolkit.update_context(ctx)

        tool_names = {tool.spec.name for tool in state.tools}
        assert "save_memory" in tool_names
        assert "search_memories" in tool_names
        assert "bash" not in tool_names
        assert "exec_command" not in tool_names
        assert "Runtime Files" not in state.prompt

    @pytest.mark.asyncio
    async def test_root_agents_loaded_from_persistent_state(self) -> None:
        """persistent root AGENTS.md state is included in prompt."""
        agents_store = _FakeAgentsInstructionStateStore()
        await agents_store.save_root(
            "agent-root-state-test",
            "session-1",
            RootAgentsInstructionState(root_content="SNAPSHOT_ROOT_RULE"),
        )
        toolkit = _make_builtin_toolkit(
            config=ShellToolkitConfig(memory_enabled=False),
            agent_id="agent-root-state-test",
            session_manager=_make_mock_session_manager(),
            agent_runtime_repo=_make_runtime_repo(runtime_id="runtime-root-state"),
            agents_store=agents_store,
        )

        state = await toolkit.update_context(_make_context())

        assert "SNAPSHOT_ROOT_RULE" in state.prompt

    @pytest.mark.asyncio
    async def test_root_agents_snapshot_updated_by_write_with_size_cap(self) -> None:
        """root AGENTS write hook updates snapshot after applying size cap."""
        agents_store = _FakeAgentsInstructionStateStore()
        toolkit = _make_builtin_toolkit(
            config=ShellToolkitConfig(memory_enabled=False),
            agent_id="agent-snapshot-test",
            agents_store=agents_store,
        )
        big_content = "x" * (70 * 1024)

        runtime_toolkit = _make_toolkit(
            agent_id="agent-snapshot-test",
            agents_store=agents_store,
        )
        await runtime_toolkit.on_after_tool_call(
            MagicMock(
                tool_name="write",
                args_json=json.dumps(
                    {"path": "/workspace/agent/AGENTS.md", "content": big_content}
                ),
            ),
            MagicMock(error=None),
        )
        state = await toolkit.update_context(_make_context())

        assert "Session Workspace Instructions" in state.prompt
        assert "... (truncated)" in state.prompt

    @pytest.mark.asyncio
    async def test_root_agents_snapshot_updated_by_edit(self) -> None:
        """root AGENTS edit hook does not leave existing snapshot stale."""
        agent_id = "agent-edit-snapshot-test"
        agents_store = _FakeAgentsInstructionStateStore()
        runtime_toolkit = _make_toolkit(agent_id=agent_id, agents_store=agents_store)
        await runtime_toolkit.on_after_tool_call(
            MagicMock(
                tool_name="write",
                args_json=json.dumps(
                    {"path": "/workspace/agent/AGENTS.md", "content": "OLD_RULE"}
                ),
            ),
            MagicMock(error=None),
        )
        await runtime_toolkit.on_after_tool_call(
            MagicMock(
                tool_name="edit",
                args_json=json.dumps(
                    {
                        "path": "/workspace/agent/AGENTS.md",
                        "old_string": "OLD",
                        "new_string": "NEW",
                    }
                ),
            ),
            MagicMock(error=None),
        )
        toolkit = _make_builtin_toolkit(
            config=ShellToolkitConfig(memory_enabled=False),
            agent_id=agent_id,
            agents_store=agents_store,
        )

        state = await toolkit.update_context(_make_context())

        assert "NEW_RULE" in state.prompt
        assert "OLD_RULE" not in state.prompt


# ---------------------------------------------------------------------------
# Domain settings prompt tests
# ---------------------------------------------------------------------------


class TestRuntimeToolkitDomainConfig:
    """ShellToolkitConfig domain fields are reflected in runtime operation/prompt."""

    @pytest.mark.asyncio
    async def test_allowed_domains_in_prompt(self) -> None:
        """allowed_domains are included in prompt."""
        config = ShellToolkitConfig(allowed_domains=["example.com"])
        toolkit = _make_toolkit(config=config)
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "example.com" in state.prompt

    @pytest.mark.asyncio
    async def test_denied_domains_in_prompt(self) -> None:
        """denied_domains are included in prompt."""
        config = ShellToolkitConfig(denied_domains=["evil.com"])
        toolkit = _make_toolkit(config=config)
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        assert "evil.com" in state.prompt

    def test_get_runtime_domain_config_reflects_config(self) -> None:
        """get_runtime_domain_config() returns allowed/denied_domains from config."""
        config = ShellToolkitConfig(allowed_domains=["a.com"], denied_domains=["b.com"])
        toolkit = _make_toolkit(config=config)
        domain = toolkit.get_runtime_domain_config()
        assert domain.allowed_domains == ("a.com",)
        assert domain.denied_domains == ("b.com",)


# ---------------------------------------------------------------------------
# Helper: utility to get specific tool from update_context
# ---------------------------------------------------------------------------


def _find_tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    """Find tool by name. AssertionError when absent."""
    for t in tools:
        if t.spec.name == name:
            return t
    available = [t.spec.name for t in tools]
    msg = f"Tool '{name}' not found. Available: {available}"
    raise AssertionError(msg)


# ---------------------------------------------------------------------------
# process tool handler tests
# ---------------------------------------------------------------------------


class TestProcessToolHandler:
    """Test process tools pass operations to runtime runner."""

    @pytest.mark.asyncio
    async def test_exec_command_calls_runtime_runner_process_start(self) -> None:
        """exec_command starts a Runner-owned process and returns metadata."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        ctx = _make_context()
        publish_event = cast(AsyncMock, ctx.publish_event)
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "exec_command")

        result = await tool.handler(json.dumps({"command": "echo hello"}))

        assert isinstance(result, FunctionToolResult)
        assert "stdout:\nhello" in result.output
        assert result.metadata["kind"] == "exec_command_result"
        assert "session_id" not in result.metadata
        assert result.metadata["process_id"] == "proc-1"
        assert runner_operations.process_start_calls == [
            {
                "command": "echo hello",
                "workdir": None,
                "yield_time_ms": 10000,
                "max_output_bytes": 65536,
                "env": None,
                "owner_session_id": "session-1",
                "process_output_callback": runner_operations.process_start_calls[0][
                    "process_output_callback"
                ],
            }
        ]
        published_event_types = [
            type(call.args[0]) for call in publish_event.await_args_list
        ]
        assert published_event_types == [RuntimeReadyEvent]
        callback = cast(
            Any,
            runner_operations.process_start_calls[0]["process_output_callback"],
        )
        assert callback is not None
        await callback(
            RuntimeProcessOutputDelta(
                process_id="proc-1",
                stream="stdout",
                chunk_id=1,
                text="live\n",
                truncated=False,
                omitted_bytes=0,
            )
        )
        assert isinstance(
            publish_event.await_args_list[-1].args[0], RuntimeProcessOutputDeltaEvent
        )

    @pytest.mark.asyncio
    async def test_exec_command_injects_envvar_peer_toolkit(self) -> None:
        """EnvVarToolkit peer is passed to runtime runner operation env.

        ``Toolkit.expose_env()`` → ``_collect_secret_env`` → runner operation env
        Prove path directly without LLM.
        """
        from azents.engine.tools.envvar import (  # noqa: PLC0415
            EnvEntryMeta,
            EnvVarToolkit,
            EnvVarToolkitConfig,
        )

        marker = "testenv-envvar-marker-001"
        envvar_peer = EnvVarToolkit(
            config=EnvVarToolkitConfig(entries=[EnvEntryMeta(name="MY_TEST_KEY")]),
            values={"MY_TEST_KEY": marker},
            toolkit_name="QA EnvVar",
        )

        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        toolkit.set_peer_toolkits([envvar_peer])

        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "exec_command")

        await tool.handler(json.dumps({"command": "echo $MY_TEST_KEY"}))

        assert runner_operations.process_start_calls[-1]["env"] == {
            "MY_TEST_KEY": marker
        }

    @pytest.mark.asyncio
    async def test_write_stdin_calls_runtime_runner_process_write(self) -> None:
        """write_stdin writes to an existing Runner process."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "write_stdin")

        result = await tool.handler(
            json.dumps({"process_id": "proc-1", "chars": "input\n"})
        )

        assert isinstance(result, FunctionToolResult)
        assert "status: running" in result.output
        assert result.metadata["kind"] == "write_stdin_result"
        assert runner_operations.process_write_calls == [
            {
                "process_id": "proc-1",
                "stdin": "input\n",
                "yield_time_ms": 10000,
                "max_output_bytes": 65536,
                "owner_session_id": "session-1",
                "process_output_callback": runner_operations.process_write_calls[0][
                    "process_output_callback"
                ],
            }
        ]

    @pytest.mark.asyncio
    async def test_exec_command_waits_when_provider_not_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """exec_command waits until Provider is ready unless running."""
        monkeypatch.setattr(
            builtin_module,
            "_RUNTIME_READY_WAIT_TIMEOUT_SECONDS",
            0.0,
        )
        toolkit = _make_toolkit(
            provider_observed_state=RuntimeProviderObservedState.STOPPED
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        with pytest.raises(FunctionToolError, match="Runtime is still starting"):
            await tool.handler(json.dumps({"command": "ls"}))

    @pytest.mark.asyncio
    async def test_exec_command_requests_start_when_runtime_stopped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runtime tool changes stopped status to start desired and waits."""
        monkeypatch.setattr(
            builtin_module,
            "_RUNTIME_READY_WAIT_TIMEOUT_SECONDS",
            0.0,
        )
        toolkit = _make_toolkit(
            desired_state=RuntimeDesiredState.STOPPED,
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            runner_state=RuntimeRunnerState.UNKNOWN,
        )
        runtime_repo = cast(Any, toolkit)._test_agent_runtime_repo
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        with pytest.raises(FunctionToolError, match="Runtime is still starting"):
            await tool.handler(json.dumps({"command": "ls"}))

        runtime_repo.set_desired_state.assert_awaited_once()
        assert runtime_repo.set_desired_state.await_args.args[2:] == (
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )

    @pytest.mark.asyncio
    async def test_exec_command_waits_until_runtime_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """exec_command waits briefly until Runtime is ready, then runs."""
        monkeypatch.setattr(
            builtin_module,
            "_RUNTIME_READY_POLL_INTERVAL_SECONDS",
            0.001,
        )
        toolkit = _make_toolkit(
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            runner_state=RuntimeRunnerState.UNKNOWN,
        )
        runtime_repo = cast(Any, toolkit)._test_agent_runtime_repo
        runtime_repo.get_by_agent_id.side_effect = [
            SimpleNamespace(
                id="runtime-1",
                desired_state=RuntimeDesiredState.RUNNING,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                provider_observed_state=RuntimeProviderObservedState.STOPPING,
                runner_state=RuntimeRunnerState.UNKNOWN,
                runner_generation=1,
            ),
            SimpleNamespace(
                id="runtime-1",
                desired_state=RuntimeDesiredState.RUNNING,
                provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
                provider_observed_state=RuntimeProviderObservedState.RUNNING,
                runner_state=RuntimeRunnerState.READY,
                runner_generation=2,
            ),
        ]
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        result = await tool.handler(json.dumps({"command": "ls"}))

        assert isinstance(result, FunctionToolResult)
        assert runner_operations.process_start_calls[-1]["command"] == "ls"
        assert runtime_repo.get_by_agent_id.await_count == 2

    @pytest.mark.asyncio
    async def test_exec_command_fails_fast_when_provider_failed(self) -> None:
        """Provider failed status is immediately delivered as error."""
        toolkit = _make_toolkit(
            provider_observed_state=RuntimeProviderObservedState.FAILED,
            runner_state=RuntimeRunnerState.UNKNOWN,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        with pytest.raises(FunctionToolError, match="Runtime failed"):
            await tool.handler(json.dumps({"command": "ls"}))

    @pytest.mark.asyncio
    async def test_exec_command_fails_fast_when_provider_disconnected(self) -> None:
        """Runtime with disconnected Provider fails explicitly."""
        toolkit = _make_toolkit(
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        with pytest.raises(FunctionToolError, match="Provider is disconnected"):
            await tool.handler(json.dumps({"command": "ls"}))

    @pytest.mark.asyncio
    async def test_exec_command_stdout_reaches_websocket_payload(self) -> None:
        """exec_command stdout reaches Chat WebSocket payload."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "exec_command")

        tool_output = await tool.handler(json.dumps({"command": "pwd"}))
        assert isinstance(tool_output, FunctionToolResult)
        assert isinstance(tool_output.output, str)
        emits = [
            durable(
                Event(
                    id="0123456789abcdef0123456789abcdef",
                    session_id="session-1",
                    kind=EventKind.CLIENT_TOOL_RESULT,
                    payload=ClientToolResultPayload(
                        call_id="call-exec-command-1",
                        name="exec_command",
                        status="completed",
                        output=tool_output.output,
                        metadata=tool_output.metadata,
                        attachments=[],
                    ),
                    created_at=datetime.now(UTC),
                )
            )
        ]
        websocket_payloads: list[dict[str, object]] = []

        async def publish(event: PublishedEvent) -> None:
            from azents.broker.serialization import serialize_event  # noqa: PLC0415

            if not isinstance(event, Event):
                raise AssertionError("expected event")
            websocket_payloads.append(serialize_event(event))

        for emit in emits:
            await handle_engine_event(
                emit,
                publish=publish,
            )

        assert websocket_payloads[0]["kind"] == "client_tool_result"
        payload = websocket_payloads[0]["payload"]
        assert isinstance(payload, dict)
        assert "stdout:" in payload["output"]

    @pytest.mark.asyncio
    async def test_exec_command_reuses_runtime_runner_without_lifecycle_events(
        self,
    ) -> None:
        """Runtime Runner process execution emits only clear ready event."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        publish_event = cast(AsyncMock, ctx.publish_event)
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "exec_command")

        result = await tool.handler(json.dumps({"command": "pwd"}))

        assert isinstance(result, FunctionToolResult)
        publish_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exec_command_operation_failure_stays_tool_observation(
        self,
    ) -> None:
        """Runner process operation failure is delivered only as tool failure."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        runner_operations.process_unavailable_message = (
            "Runner operation route unavailable: subject-1"
        )
        ctx = _make_context()
        publish_event = cast(AsyncMock, ctx.publish_event)
        state = await toolkit.update_context(ctx)
        tool = _find_tool(state.tools, "exec_command")

        with pytest.raises(
            FunctionToolError,
            match="Runner operation route unavailable",
        ):
            await tool.handler(json.dumps({"command": "pwd"}))

        publish_event.assert_awaited_once()
        await_args = publish_event.await_args
        assert await_args is not None
        published_event = await_args.args[0]
        assert isinstance(published_event, RuntimeReadyEvent)


# ---------------------------------------------------------------------------
# read handler tests
# ---------------------------------------------------------------------------


class TestReadHandler:
    """Test read tool handler reads file from storage."""

    @pytest.mark.asyncio
    async def test_read_returns_file_content(self) -> None:
        """Return file content from storage on handler call."""
        files = {"/workspace/agent/test.txt": b"file content here"}
        storage = FakeSharedStorage(files=files)
        tool = make_read_text_tool(
            session_storage=storage,
            agent_id="agent-1",
            user_id="",
        )

        result = await tool.handler(json.dumps({"path": "/workspace/agent/test.txt"}))
        assert isinstance(result, str)
        assert "file content here" in result


# ---------------------------------------------------------------------------
# write handler tests
# ---------------------------------------------------------------------------


class TestWriteHandler:
    """Test write tool handler writes file to storage."""

    @pytest.mark.asyncio
    async def test_write_creates_file(self) -> None:
        """File is created in storage on handler call."""
        storage = FakeSharedStorage()
        tool = make_write_tool(
            session_storage=storage,
            agent_id="agent-1",
            user_id="",
        )

        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/out.txt", "content": "hello world"})
        )
        assert isinstance(result, str)
        assert len(storage.put_calls) == 1


# ---------------------------------------------------------------------------
# edit handler tests
# ---------------------------------------------------------------------------


class TestEditHandler:
    """Test edit tool handler edits file content."""

    @pytest.mark.asyncio
    async def test_edit_replaces_text(self) -> None:
        """File content is replaced on handler call."""
        files = {"/workspace/agent/config.txt": b"old_value"}
        storage = FakeSharedStorage(files=files)
        tool = make_edit_tool(
            session_storage=storage,
            agent_id="agent-1",
            user_id="",
        )

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/config.txt",
                    "old_string": "old_value",
                    "new_string": "new_value",
                }
            )
        )
        assert isinstance(result, str)
        # Check file content after edit
        data = await storage.get("/workspace/agent/config.txt")
        assert b"new_value" in data
