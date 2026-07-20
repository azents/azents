"""BuiltinToolkit/RuntimeToolkit update_context() and handler tests."""

import asyncio
import json
import logging
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
from azents.core.tools import (
    ResolveContext,
    ShellToolkitConfig,
    ToolCallHookOutcome,
    ToolkitState,
    TurnContext,
)
from azents.engine.events.engine_events import (
    RuntimeProcessOutputDeltaEvent,
    RuntimeReadyEvent,
)
from azents.engine.events.types import ClientToolResultPayload, Event
from azents.engine.hooks.types import SessionCompactHookContext
from azents.engine.run.emit import PublishedEvent, durable, handle_engine_event
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tools import builtin as builtin_module
from azents.engine.tools.builtin import (
    BuiltinToolkit,
    BuiltinToolkitProvider,
    MemoryReadToolkit,
    MemoryWriteToolkit,
    RuntimeToolkit,
)
from azents.engine.tools.builtin_agents import AgentsAppendixDedupeState
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


def _make_resolve_context(
    *,
    agent_id: str = "agent-1",
    session_id: str = "session-1",
    user_id: str = "user-1",
    workspace_id: str = "ws-1",
) -> ResolveContext:
    """Create ResolveContext for toolkit provider tests."""
    return ResolveContext(
        toolkit_id="",
        toolkit_name="shell",
        credentials_json=None,
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        session=AsyncMock(),
        web_url="https://example.test",
        oauth_secret_key="test-secret",
        workspace_id=workspace_id,
        workspace_handle="test-workspace",
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


def _make_runtime_repo(  # pyright: ignore[reportUnusedFunction] -- retained test helper
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


class _FakeAgentsAppendixDedupeStateStore:
    """AGENTS.md appendix dedupe state store for tests."""

    def __init__(self) -> None:
        self.dedupe_states: dict[tuple[str, str], AgentsAppendixDedupeState] = {}

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Return stored appendix dedupe state."""
        return self.dedupe_states.get(
            (agent_id, session_id), AgentsAppendixDedupeState()
        )

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Apply appendix dedupe state update."""
        state = await self.load_appendix_dedupe(agent_id, session_id)
        self.dedupe_states[(agent_id, session_id)] = mutator(state)


class _FakeRunnerOperations:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.bash_calls: list[dict[str, object]] = []
        self.process_start_calls: list[dict[str, object]] = []
        self.process_write_calls: list[dict[str, object]] = []
        self.process_terminate_session_calls: list[dict[str, object]] = []
        self.file_operation_calls: list[tuple[str, str | None]] = []
        self.read_calls: list[str] = []
        self.stat_calls: list[str] = []
        self.stat_started_count = 0
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
        owner_session_id: str | None,
        command: str,
        timeout_seconds: int,
        env: dict[str, str] | None,
        deadline_at: datetime,
        cancel_check: object | None = None,
    ) -> RuntimeBashResult:
        del runtime_id, runner_generation, timeout_seconds, deadline_at, cancel_check
        self.file_operation_calls.append(("run_bash", owner_session_id))
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

    async def terminate_session_processes(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        deadline_at: datetime,
    ) -> None:
        del runtime_id, runner_generation, deadline_at
        self.process_terminate_session_calls.append(
            {"owner_session_id": owner_session_id}
        )
        if self.process_unavailable_message is not None:
            raise RuntimeRunnerOperationUnavailable(self.process_unavailable_message)

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        del runtime_id, runner_generation, deadline_at
        self.file_operation_calls.append(("read", owner_session_id))
        self.read_calls.append(path)
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
        owner_session_id: str | None = None,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        del runtime_id, runner_generation, deadline_at
        self.file_operation_calls.append(("stat", owner_session_id))
        self.stat_started_count += 1
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
        owner_session_id: str | None = None,
        path: str,
        data: bytes,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        del runtime_id, runner_generation, deadline_at
        self.file_operation_calls.append(("write", owner_session_id))
        self.files[path] = data
        return RuntimeFileWriteResult(bytes_written=len(data), final_cursor="0-1")

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        del runtime_id, runner_generation, recursive, exclude_patterns, deadline_at
        self.file_operation_calls.append(("list", owner_session_id))
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

    async def glob_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        pattern: str,
        exclude_patterns: list[str] | None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        del runtime_id, runner_generation, deadline_at
        self.file_operation_calls.append(("glob", owner_session_id))
        attachments = await FakeSharedStorage(self.files).glob(
            pattern,
            exclude_patterns=exclude_patterns,
        )
        return RuntimeFileListResult(
            entries=tuple(
                RuntimeFileListEntry(
                    path=attachment.uri,
                    type=(
                        "directory"
                        if attachment.media_type == "inode/directory"
                        else "file"
                    ),
                    size_bytes=attachment.size,
                )
                for attachment in attachments
            ),
            final_cursor="0-1",
        )

    async def grep_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
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
        self.file_operation_calls.append(("grep", owner_session_id))
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
    agents_store: _FakeAgentsAppendixDedupeStateStore | None = None,
) -> RuntimeToolkit:
    """Create RuntimeToolkit for tests."""
    runner_operations = _FakeRunnerOperations(storage_files)
    session_manager = _make_mock_session_manager()
    agent_runtime_repo = AsyncMock(spec=AgentRuntimeRepository)
    agent_runtime_repo.get_by_agent_id.return_value = SimpleNamespace(
        id="runtime-1",
        desired_state=desired_state,
        provider_connection_state=provider_connection_state,
        provider_observed_state=provider_observed_state,
        runner_state=runner_state,
        runner_generation=1,
    )
    project_repo = AsyncMock(spec=SessionWorkspaceProjectRepository)
    project_repo.list_projects.return_value = projects or []
    if agents_store is None:
        agents_store = _FakeAgentsAppendixDedupeStateStore()

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


def _make_project(*, path: str) -> SessionWorkspaceProject:
    """Create SessionWorkspaceProject for tests."""
    now = datetime.now(UTC)
    return SessionWorkspaceProject(
        id=f"project-{path.rsplit('/', maxsplit=1)[-1]}",
        session_id="session-1",
        session_agent_context_id="context-1",
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
) -> BuiltinToolkit:
    """Create BuiltinToolkit for tests."""
    toolkit = BuiltinToolkit(
        config=config or ShellToolkitConfig(),
        agent_id=agent_id,
        session_manager=session_manager or _make_mock_session_manager(),
        memory_repo=memory_repo or _make_mock_memory_repo(),
    )
    toolkit.set_session_id(session_id)
    return toolkit


# ---------------------------------------------------------------------------
# update_context() default behavior tests
# ---------------------------------------------------------------------------


class TestBuiltinToolkitProviderResolve:
    """BuiltinToolkitProvider resolve behavior tests."""

    @pytest.mark.asyncio
    async def test_resolved_runtime_toolkit_uses_required_agents_store(self) -> None:
        """Provider-resolved RuntimeToolkit persists AGENTS.md appendix dedupe."""
        agents_store = _FakeAgentsAppendixDedupeStateStore()
        project_repo = AsyncMock(spec=SessionWorkspaceProjectRepository)
        project_repo.list_projects.return_value = [
            _make_project(path="/workspace/agent/app")
        ]
        agent_runtime_repo = AsyncMock(spec=AgentRuntimeRepository)
        agent_runtime_repo.get_by_agent_id.return_value = SimpleNamespace(
            id="runtime-1",
            desired_state=RuntimeDesiredState.RUNNING,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            runner_state=RuntimeRunnerState.READY,
            runner_generation=1,
        )
        provider = BuiltinToolkitProvider(
            exchange_file_service=AsyncMock(spec=ExchangeFileService),
            artifact_service=AsyncMock(spec=ArtifactService),
            model_file_service=AsyncMock(),
            agents_store=agents_store,
            session_manager=_make_mock_session_manager(),
            memory_repo=_make_mock_memory_repo(),
            agent_runtime_repo=agent_runtime_repo,
            runner_operations=cast(
                Any,
                _FakeRunnerOperations(
                    {
                        "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                        "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
                        "/workspace/agent/app/file.py": b"print('hi')",
                    }
                ),
            ),
            project_repo=project_repo,
        )
        toolkit = await provider.resolve(
            ShellToolkitConfig(),
            _make_resolve_context(),
        )
        assert isinstance(toolkit, RuntimeToolkit)
        toolkit.set_session_id("session-1")
        await toolkit.update_context(_make_context())

        first = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            ),
            ToolCallHookOutcome(output="ONE", error=None),
        )
        second = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/other.py"}',
            ),
            ToolCallHookOutcome(output="TWO", error=None),
        )

        assert first is not None
        assert second is None
        dedupe = await agents_store.load_appendix_dedupe("agent-1", "session-1")
        assert dedupe.appended_paths == [
            "/workspace/agent/AGENTS.md",
            "/workspace/agent/app/AGENTS.md",
        ]


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
    async def test_update_context_registers_instruction_context(self) -> None:
        """Runtime instruction context is shared after update_context()."""
        toolkit = _make_toolkit(
            projects=[
                _make_project(path="/workspace/agent/zeta"),
                _make_project(path="/workspace/agent/alpha"),
            ]
        )

        await toolkit.update_context(_make_context())

        instruction_context = cast(Any, toolkit)._agents_context
        assert instruction_context is not None
        assert [project.path for project in instruction_context.projects] == [
            "/workspace/agent/alpha",
            "/workspace/agent/zeta",
        ]
        assert hasattr(instruction_context.file_storage, "get")

    @pytest.mark.asyncio
    async def test_file_storage_propagates_owner_and_reuses_runtime_snapshot(
        self,
    ) -> None:
        """Every FileStorage operation uses one owner and Runtime snapshot."""
        toolkit = _make_toolkit(
            storage_files={
                "/workspace/agent/file.txt": b"root",
                "/workspace/agent/dir/item.txt": b"needle",
            }
        )
        await toolkit.update_context(_make_context())
        storage = cast(Any, toolkit)._agents_context.file_storage
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        runtime_repo = cast(Any, toolkit)._test_agent_runtime_repo

        await storage.get("/workspace/agent/file.txt", agent_id="agent-1")
        await storage.stat("/workspace/agent/file.txt", agent_id="agent-1")
        await storage.put(
            "/workspace/agent/new.txt",
            b"new",
            agent_id="agent-1",
        )
        assert await storage.exists(
            "/workspace/agent/file.txt",
            agent_id="agent-1",
        )
        await storage.list("/workspace/agent", agent_id="agent-1")
        globbed = await storage.glob(
            "/workspace/agent/**/*.txt",
            agent_id="agent-1",
            exclude_patterns=["node_modules"],
        )
        await storage.list_dirs("/workspace/agent", agent_id="agent-1")
        await storage.grep(
            "/workspace/agent/dir",
            agent_id="agent-1",
            pattern="needle",
        )
        await storage.delete("/workspace/agent/new.txt", agent_id="agent-1")

        assert [attachment.uri for attachment in globbed] == [
            "/workspace/agent/dir/item.txt",
            "/workspace/agent/file.txt",
            "/workspace/agent/new.txt",
        ]
        assert runner_operations.file_operation_calls == [
            ("read", "session-1"),
            ("stat", "session-1"),
            ("write", "session-1"),
            ("stat", "session-1"),
            ("list", "session-1"),
            ("glob", "session-1"),
            ("list", "session-1"),
            ("grep", "session-1"),
            ("run_bash", "session-1"),
        ]
        runtime_repo.get_by_agent_id.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subagent_read_and_appendix_share_parent_runtime_with_child_owner(
        self,
    ) -> None:
        """Subagent file work uses its Session owner and parent Runtime snapshot."""
        toolkit = _make_toolkit(
            agent_id="child-agent",
            session_id="child-session",
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/file.txt": b"child",
            },
        )
        toolkit.set_runtime_agent_id("parent-agent")
        state = await toolkit.update_context(_make_context())
        read_tool = _find_tool(state.tools, "read")
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        runtime_repo = cast(Any, toolkit)._test_agent_runtime_repo

        output = await read_tool.handler(
            json.dumps({"path": "/workspace/agent/file.txt"})
        )
        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/file.txt"}',
            ),
            ToolCallHookOutcome(output=output, error=None),
        )

        assert decision is not None
        assert runner_operations.file_operation_calls == [
            ("read", "child-session"),
            ("stat", "child-session"),
            ("read", "child-session"),
        ]
        runtime_repo.get_by_agent_id.assert_awaited_once()
        assert runtime_repo.get_by_agent_id.await_args.args[1] == "parent-agent"

    @pytest.mark.asyncio
    async def test_read_and_agents_appendix_share_runtime_and_log_diagnostics(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Visible read and AGENTS appendix share Runtime and emit phase metrics."""
        caplog.set_level(logging.INFO)
        toolkit = _make_toolkit(
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/file.txt": b"body",
            }
        )
        state = await toolkit.update_context(_make_context())
        read_tool = _find_tool(state.tools, "read")
        runtime_repo = cast(Any, toolkit)._test_agent_runtime_repo

        output = await read_tool.handler(
            json.dumps({"path": "/workspace/agent/file.txt"})
        )
        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/file.txt"}',
            ),
            ToolCallHookOutcome(output=output, error=None),
        )

        assert decision is not None
        runtime_repo.get_by_agent_id.assert_awaited_once()
        tool_record = next(
            record
            for record in caplog.records
            if record.getMessage() == "Processed Runtime file tool"
        )
        tool_fields = vars(tool_record)
        assert tool_fields["tool_name"] == "read"
        assert tool_fields["tool_status"] == "completed"
        assert tool_fields["runtime_operation_count"] == 1
        assert tool_fields["session_id"] == "session-1"
        assert tool_fields["tool_duration_ms"] >= 0
        appendix_record = next(
            record
            for record in caplog.records
            if record.getMessage() == "Processed AGENTS.md read appendix"
        )
        appendix_fields = vars(appendix_record)
        assert appendix_fields["candidate_path_count"] == 1
        assert appendix_fields["discovery_cache_hit_count"] == 0
        assert appendix_fields["discovery_cache_miss_count"] == 1
        assert appendix_fields["dedupe_skipped_path_count"] == 0
        assert appendix_fields["internal_stat_operation_count"] == 1
        assert appendix_fields["internal_read_operation_count"] == 1
        assert appendix_fields["appended_path_count"] == 1
        assert appendix_fields["appendix_duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_prompt_includes_runtime_files(self) -> None:
        """Check that prompt includes Runtime Files section."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        await toolkit.update_context(ctx)
        assert "Runtime Files" in (await toolkit.get_static_prompt(_make_context()))

    @pytest.mark.asyncio
    async def test_prompt_includes_agent_workspace_path(self) -> None:
        """Prompt includes /workspace/agent path."""
        toolkit = _make_toolkit(agent_id="agent-1")
        ctx = _make_context()
        await toolkit.update_context(ctx)
        assert "/workspace/agent/" in (await toolkit.get_static_prompt(_make_context()))

    @pytest.mark.asyncio
    async def test_prompt_includes_exchange_tools_when_user_id(self) -> None:
        """When user_id exists, exchange tool guidance is included."""
        toolkit = _make_toolkit()
        ctx = _make_context(user_id="user-1")
        await toolkit.update_context(ctx)
        assert "import_file" in (await toolkit.get_static_prompt(_make_context()))
        assert "present_file" in (await toolkit.get_static_prompt(_make_context()))

    @pytest.mark.asyncio
    async def test_prompt_excludes_legacy_data_paths(self) -> None:
        """runtime prompt does not guide legacy /data path."""
        toolkit = _make_toolkit()
        ctx = _make_context()
        await toolkit.update_context(ctx)
        assert "/data/" not in (await toolkit.get_static_prompt(_make_context()))

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

        await toolkit.update_context(ctx)

        assert "Registered Projects" in (
            await toolkit.get_static_prompt(_make_context())
        )
        assert "`/workspace/agent/azents`" in (
            await toolkit.get_static_prompt(_make_context())
        )
        assert "`/workspace/agent/admin`" in (
            await toolkit.get_static_prompt(_make_context())
        )
        assert "`/workspace/agent` itself is not a Project" in (
            await toolkit.get_static_prompt(_make_context())
        )

    @pytest.mark.asyncio
    async def test_prompt_omits_project_section_when_empty(self) -> None:
        """Do not display registered Project section when Project is absent."""
        toolkit = _make_toolkit(projects=[])
        ctx = _make_context()

        await toolkit.update_context(ctx)

        assert "Registered Projects" not in (
            await toolkit.get_static_prompt(_make_context())
        )

    @pytest.mark.asyncio
    async def test_read_appends_root_and_project_agents(self) -> None:
        """Successful read appends applicable AGENTS.md files parent-to-child."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
                "/workspace/agent/app/src/AGENTS.md": b"SRC_RULE",
                "/workspace/agent/app/src/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())
        assert "ROOT_RULE" not in (await toolkit.get_static_prompt(_make_context()))
        assert "PROJECT_RULE" not in (await toolkit.get_static_prompt(_make_context()))

        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/src/file.py"}',
            ),
            ToolCallHookOutcome(output="FILE_CONTENT", error=None),
        )

        assert decision is not None
        assert decision.output_text.startswith("FILE_CONTENT")
        assert decision.output_text.index("ROOT_RULE") < decision.output_text.index(
            "PROJECT_RULE"
        )
        assert decision.output_text.index("PROJECT_RULE") < decision.output_text.index(
            "SRC_RULE"
        )

    @pytest.mark.asyncio
    async def test_read_appends_agents_only_once_until_compaction(self) -> None:
        """AGENTS.md appendix is deduped by path until compaction clears state."""
        agents_store = _FakeAgentsAppendixDedupeStateStore()
        toolkit = _make_toolkit(
            agents_store=agents_store,
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
                "/workspace/agent/app/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        first = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            ),
            ToolCallHookOutcome(output="ONE", error=None),
        )
        second = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/other.py"}',
            ),
            ToolCallHookOutcome(output="TWO", error=None),
        )

        assert first is not None
        assert second is None
        dedupe = await agents_store.load_appendix_dedupe("agent-1", "session-1")
        assert dedupe.appended_paths == [
            "/workspace/agent/AGENTS.md",
            "/workspace/agent/app/AGENTS.md",
        ]

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
        third = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/again.py"}',
            ),
            ToolCallHookOutcome(output="THREE", error=None),
        )

        assert third is not None
        assert "ROOT_RULE" in third.output_text

    @pytest.mark.asyncio
    async def test_reading_agents_file_does_not_append_itself(self) -> None:
        """Reading AGENTS.md itself does not append the same file as appendix."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
            },
        )
        await toolkit.update_context(_make_context())

        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/AGENTS.md"}',
            ),
            ToolCallHookOutcome(output="PROJECT_RULE", error=None),
        )

        assert decision is not None
        assert "ROOT_RULE" in decision.output_text
        assert decision.output_text.count("PROJECT_RULE") == 1

    @pytest.mark.asyncio
    async def test_non_read_tools_do_not_append_agents(self) -> None:
        """AGENTS.md appendix is limited to successful read results."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/AGENTS.md": b"ROOT_RULE",
                "/workspace/agent/app/AGENTS.md": b"PROJECT_RULE",
            },
        )
        await toolkit.update_context(_make_context())

        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="write",
                args_json='{"path": "/workspace/agent/app/file.py", "content": "x"}',
            ),
            ToolCallHookOutcome(output="WROTE", error=None),
        )

        assert decision is None

    @pytest.mark.asyncio
    async def test_missing_agents_candidates_use_negative_cache_until_compaction(
        self,
    ) -> None:
        """Absent AGENTS.md candidates avoid repeated stat calls within a Session."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={"/workspace/agent/app/file.py": b"print('hi')"},
        )
        await toolkit.update_context(_make_context())
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )

        first = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            ),
            ToolCallHookOutcome(output="ONE", error=None),
        )
        second = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/other.py"}',
            ),
            ToolCallHookOutcome(output="TWO", error=None),
        )

        assert first is None
        assert second is None
        assert runner_operations.stat_calls == [
            "/workspace/agent/AGENTS.md",
            "/workspace/agent/app/AGENTS.md",
        ]

        runner_operations.add_file("/workspace/agent/AGENTS.md", b"ROOT_RULE")
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
        third = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/again.py"}',
            ),
            ToolCallHookOutcome(output="THREE", error=None),
        )

        assert third is not None
        assert "ROOT_RULE" in third.output_text
        assert runner_operations.stat_calls.count("/workspace/agent/AGENTS.md") == 2

    @pytest.mark.asyncio
    async def test_parallel_reads_singleflight_agents_appendix_io(self) -> None:
        """Parallel reads perform AGENTS.md stat/read and append only once."""
        toolkit = _make_toolkit(
            storage_files={"/workspace/agent/AGENTS.md": b"ROOT_RULE"},
        )
        await toolkit.update_context(_make_context())
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        runner_operations.stat_started_event = asyncio.Event()
        runner_operations.stat_continue_event = asyncio.Event()

        first_task = asyncio.create_task(
            toolkit.append_agents_after_read(
                MagicMock(
                    tool_name="read",
                    args_json='{"path": "/workspace/agent/one.py"}',
                ),
                ToolCallHookOutcome(output="ONE", error=None),
            )
        )
        await runner_operations.stat_started_event.wait()
        second_started = asyncio.Event()

        async def run_second() -> object:
            second_started.set()
            return await toolkit.append_agents_after_read(
                MagicMock(
                    tool_name="read",
                    args_json='{"path": "/workspace/agent/two.py"}',
                ),
                ToolCallHookOutcome(output="TWO", error=None),
            )

        second_task = asyncio.create_task(run_second())
        await second_started.wait()
        await asyncio.sleep(0)
        assert runner_operations.stat_started_count == 1

        runner_operations.stat_continue_event.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert first is not None
        assert second is None
        assert runner_operations.stat_calls == ["/workspace/agent/AGENTS.md"]
        assert runner_operations.read_calls == ["/workspace/agent/AGENTS.md"]

    @pytest.mark.asyncio
    async def test_missing_or_non_file_agents_candidates_are_ignored(self) -> None:
        """Missing and non-file AGENTS.md candidates are not appended."""
        toolkit = _make_toolkit(
            projects=[_make_project(path="/workspace/agent/app")],
            storage_files={
                "/workspace/agent/app/AGENTS.md/nested.txt": b"NOT_A_RULE",
                "/workspace/agent/app/file.py": b"print('hi')",
            },
        )
        await toolkit.update_context(_make_context())

        decision = await toolkit.append_agents_after_read(
            MagicMock(
                tool_name="read",
                args_json='{"path": "/workspace/agent/app/file.py"}',
            ),
            ToolCallHookOutcome(output="FILE", error=None),
        )

        assert decision is None


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
        await toolkit.update_context(ctx)
        assert (await toolkit.get_static_prompt(_make_context())) == ""
        assert "Memories" in (await toolkit.get_dynamic_prompt(ctx))
        dynamic_prompt = await toolkit.get_dynamic_prompt(ctx)
        assert "Memory Rules" in dynamic_prompt
        assert "loaded memory summaries as the primary index" in dynamic_prompt
        assert "ranked partial matches" in dynamic_prompt

    @pytest.mark.asyncio
    async def test_memory_disabled_excludes_memory(self) -> None:
        """When memory_enabled=False, there is no memory-related prompt."""
        config = ShellToolkitConfig(memory_enabled=False)
        toolkit = _make_builtin_toolkit(config=config)
        ctx = _make_context()
        await toolkit.update_context(ctx)
        assert "Memories" not in (await toolkit.get_static_prompt(_make_context()))
        assert (await toolkit.get_dynamic_prompt(ctx)) == ""

    @pytest.mark.asyncio
    async def test_memory_write_prompt_reuses_read_shared_rules(self) -> None:
        """Read prompt owns shared memory rules because write is never bound alone."""
        config = ShellToolkitConfig(memory_enabled=True)
        session_manager = _make_mock_session_manager()
        memory_repo = _make_mock_memory_repo()
        read_toolkit = MemoryReadToolkit(
            config=config,
            agent_id="agent-1",
            session_manager=session_manager,
            memory_repo=memory_repo,
        )
        write_toolkit = MemoryWriteToolkit(
            config=config,
            agent_id="agent-1",
            session_manager=session_manager,
            memory_repo=memory_repo,
        )
        ctx = _make_context()

        read_prompt = await read_toolkit.get_dynamic_prompt(ctx)
        write_prompt = await write_toolkit.get_dynamic_prompt(ctx)

        assert "Types of memory" in read_prompt
        assert "Scope selection" in read_prompt
        assert "Types of memory" not in write_prompt
        assert "Scope selection" not in write_prompt
        assert "What NOT to save" in write_prompt
        assert "Duplicate prevention" in write_prompt
        assert "empty search result alone" in write_prompt

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
        await toolkit.update_context(ctx)
        assert "my-project" in (await toolkit.get_dynamic_prompt(ctx))
        assert "my project description" in (await toolkit.get_dynamic_prompt(ctx))

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
        assert "Runtime Files" not in (await toolkit.get_static_prompt(_make_context()))
        assert "Memories" in (await toolkit.get_dynamic_prompt(ctx))


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
        await toolkit.update_context(ctx)
        assert "example.com" in (await toolkit.get_static_prompt(_make_context()))

    @pytest.mark.asyncio
    async def test_denied_domains_in_prompt(self) -> None:
        """denied_domains are included in prompt."""
        config = ShellToolkitConfig(denied_domains=["evil.com"])
        toolkit = _make_toolkit(config=config)
        ctx = _make_context()
        await toolkit.update_context(ctx)
        assert "evil.com" in (await toolkit.get_static_prompt(_make_context()))

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
    async def test_exec_command_cancel_terminates_session_processes(self) -> None:
        """User stop cancel hook terminates all session-owned processes."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "exec_command")

        assert tool.cancel_handler is not None
        await tool.cancel_handler(
            FunctionToolCancelRequest(
                call_id="call-1",
                name="exec_command",
                arguments='{"command": "sleep 30"}',
            )
        )

        assert runner_operations.process_terminate_session_calls == [
            {"owner_session_id": "session-1"}
        ]

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
                "yield_time_ms": 250,
                "max_output_bytes": 65536,
                "owner_session_id": "session-1",
                "process_output_callback": runner_operations.process_write_calls[0][
                    "process_output_callback"
                ],
            }
        ]

    @pytest.mark.asyncio
    async def test_write_stdin_empty_poll_defaults_to_longer_yield(self) -> None:
        """Empty write_stdin polls use the Codex-style polling default."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "write_stdin")

        await tool.handler(json.dumps({"process_id": "proc-1"}))

        assert runner_operations.process_write_calls[-1]["stdin"] == ""
        assert runner_operations.process_write_calls[-1]["yield_time_ms"] == 5000

    @pytest.mark.asyncio
    async def test_write_stdin_accepts_zero_yield_for_all_modes(self) -> None:
        """write_stdin forwards zero yields for immediate process snapshots."""
        toolkit = _make_toolkit()
        runner_operations = cast(
            _FakeRunnerOperations,
            cast(Any, toolkit)._test_runner_operations,
        )
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "write_stdin")

        await tool.handler(json.dumps({"process_id": "proc-1", "yield_time_ms": 0}))
        await tool.handler(
            json.dumps(
                {
                    "process_id": "proc-1",
                    "chars": "input\n",
                    "yield_time_ms": 0,
                }
            )
        )

        assert runner_operations.process_write_calls[-2]["yield_time_ms"] == 0
        assert runner_operations.process_write_calls[-2]["stdin"] == ""
        assert runner_operations.process_write_calls[-1]["yield_time_ms"] == 0
        assert runner_operations.process_write_calls[-1]["stdin"] == "input\n"

    @pytest.mark.asyncio
    async def test_write_stdin_rejects_non_empty_yield_above_maximum(self) -> None:
        """Non-empty write_stdin calls keep their shorter maximum yield."""
        toolkit = _make_toolkit()
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "write_stdin")

        with pytest.raises(FunctionToolError, match="non-empty write yield_time_ms"):
            await tool.handler(
                json.dumps(
                    {
                        "process_id": "proc-1",
                        "chars": "input\n",
                        "yield_time_ms": 60000,
                    }
                )
            )

    @pytest.mark.asyncio
    async def test_process_tool_schema_documents_codex_yield_defaults(self) -> None:
        """Process tool schemas document Codex-style defaults and ranges."""
        toolkit = _make_toolkit()
        state = await toolkit.update_context(_make_context())
        exec_tool = _find_tool(state.tools, "exec_command")
        write_tool = _find_tool(state.tools, "write_stdin")

        exec_properties = cast(
            dict[str, Any], exec_tool.spec.input_schema["properties"]
        )
        write_properties = cast(
            dict[str, Any], write_tool.spec.input_schema["properties"]
        )
        exec_yield = cast(dict[str, Any], exec_properties["yield_time_ms"])
        write_yield = cast(dict[str, Any], write_properties["yield_time_ms"])
        assert exec_yield["default"] == 10000
        assert exec_yield["minimum"] == 250
        assert exec_yield["maximum"] == 30000
        assert "accepted range is 250-30000 ms" in exec_yield["description"]
        assert write_yield["default"] == 250
        assert write_yield["minimum"] == 0
        assert write_yield["maximum"] == 300000
        assert (
            "Zero returns currently buffered output immediately"
            in write_yield["description"]
        )
        assert "Non-empty writes default to 250 ms" in write_yield["description"]
        assert "empty polls default to 5000 ms" in write_yield["description"]

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
