"""Agent Workspace service tests."""

import contextlib
import datetime
from collections.abc import AsyncGenerator

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileReadResult,
    RuntimeFileStatResult,
    RuntimeRunnerOperationFailedError,
)
from azents.services.chat.workspace import (
    AGENT_WORKSPACE_ROOT,
    AgentWorkspaceFileService,
)

_NOW = datetime.datetime(2026, 5, 24, tzinfo=datetime.UTC)


class _FakeAgentRepository(AgentRepository):
    async def get_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        del session
        if agent_id != "agent-1":
            return None
        return Agent.model_construct(id="agent-1", workspace_id="workspace-1")


class _FakeWorkspaceUserRepository(WorkspaceUserRepository):
    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        del session
        if workspace_id == "workspace-1" and user_id == "user-1":
            return WorkspaceUser(
                id="workspace-user-1",
                workspace_id=workspace_id,
                user_id=user_id,
                name="User",
                locale="ko-KR",
                role=WorkspaceUserRole.MEMBER,
                created_at=_NOW,
                updated_at=_NOW,
            )
        return None


class _FakeRuntimeRepository(AgentRuntimeRepository):
    def __init__(self, runtime: AgentRuntime | None) -> None:
        self._runtime = runtime

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        del session, agent_id
        return self._runtime

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        del session, agent_id, default_runtime_provider_id
        if self._runtime is None:
            self._runtime = _make_agent_runtime()
        return self._runtime


class _FakeRunnerOperations:
    def __init__(self) -> None:
        self.files = {
            (AGENT_WORKSPACE_ROOT / "README.md").as_posix(): b"# Workspace\n",
            (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix(): b"hello",
        }
        self.list_calls: list[tuple[str, int, str]] = []
        self.read_calls: list[tuple[str, int, str]] = []
        self.stat_calls: list[tuple[str, int, str]] = []

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileListResult:
        del recursive, exclude_patterns, deadline_at
        self.list_calls.append((runtime_id, runner_generation, path))
        return RuntimeFileListResult(
            entries=(
                *(
                    RuntimeFileListEntry(
                        path=file_path,
                        type="file",
                        size_bytes=len(data),
                    )
                    for file_path, data in self.files.items()
                ),
            ),
            final_cursor="0-1",
        )

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileReadResult:
        del deadline_at
        self.read_calls.append((runtime_id, runner_generation, path))
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
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        del deadline_at
        self.stat_calls.append((runtime_id, runner_generation, path))
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
        if path == AGENT_WORKSPACE_ROOT.as_posix():
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


@contextlib.asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession]:
    yield object()  # pyright: ignore[reportReturnType]


@pytest.mark.asyncio
async def test_get_workspace_reads_active_runtime_with_runner() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    state = result.value
    assert state.runtime.type == "RUNNING"
    assert state.workspace.type == "READY"
    assert state.actions.stop is not None
    assert state.actions.stop.type == "STOP_RUNTIME"
    assert runner_operations.list_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]
    assert [entry.path for entry in state.workspace.manifest.entries] == [
        (AGENT_WORKSPACE_ROOT / "README.md").as_posix(),
        (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix(),
    ]


@pytest.mark.asyncio
async def test_get_workspace_uses_agent_runtime_without_session_match() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    state = result.value
    assert state.runtime.type == "RUNNING"
    assert state.workspace.type == "READY"
    assert state.actions.stop is not None
    assert state.actions.stop.type == "STOP_RUNTIME"
    assert runner_operations.list_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]


@pytest.mark.asyncio
async def test_get_workspace_reports_missing_provider_workspace_path() -> None:
    runtime = _make_agent_runtime(
        workspace_path=None,
    )
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    state = result.value
    assert state.runtime.type == "RUNNING"
    assert state.workspace.type == "UNAVAILABLE"
    assert state.workspace.reason == "WORKSPACE_PATH_UNAVAILABLE"
    assert runner_operations.list_calls == []


@pytest.mark.asyncio
async def test_get_workspace_reports_stopped_runtime_not_started() -> None:
    """Workspace state follows Provider observed state."""
    runtime = _make_agent_runtime(
        provider_observed_state=RuntimeProviderObservedState.UNKNOWN,
        desired_state=RuntimeDesiredState.STOPPED,
    )
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=_FakeRunnerOperations(),  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    assert result.value.runtime.type == "NOT_STARTED"
    assert result.value.actions.start is not None


@pytest.mark.asyncio
async def test_get_workspace_shows_starting_when_start_requested() -> None:
    """start desired state is starting even if Provider still reports stopped."""
    runtime = _make_agent_runtime(
        provider_observed_state=RuntimeProviderObservedState.STOPPED,
        desired_state=RuntimeDesiredState.RUNNING,
    )
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=_FakeRunnerOperations(),  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    assert result.value.runtime.type == "STARTING"
    assert result.value.workspace.type == "CONNECTING"
    assert result.value.actions.stop is not None
    assert result.value.actions.stop.type == "STOP_RUNTIME"


@pytest.mark.asyncio
async def test_get_workspace_error_exposes_restart_action() -> None:
    """Expose Pod restart action in Provider failure state."""
    runtime = _make_agent_runtime(
        provider_observed_state=RuntimeProviderObservedState.FAILED,
        desired_state=RuntimeDesiredState.RUNNING,
    )
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=_FakeRunnerOperations(),  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    assert result.value.runtime.type == "LOST"
    assert result.value.actions.stop is not None
    assert result.value.actions.stop.type == "STOP_RUNTIME"
    assert result.value.actions.restart is not None
    assert result.value.actions.restart.type == "RESTART_RUNTIME"


@pytest.mark.asyncio
async def test_read_path_uses_stat_to_return_file_preview() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )
    file_path = (AGENT_WORKSPACE_ROOT / "README.md").as_posix()

    result = await service.read_path("agent-1", "user-1", file_path)

    assert isinstance(result, Success)
    assert result.value.type == "FILE"
    assert result.value.path == file_path
    assert result.value.media_type == "text/markdown"
    assert result.value.text == "# Workspace\n"
    assert runner_operations.stat_calls == [("runtime-1", 1, file_path)]
    assert runner_operations.read_calls == [("runtime-1", 1, file_path)]
    assert runner_operations.list_calls == []


@pytest.mark.asyncio
async def test_read_path_uses_stat_to_return_directory_listing() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.read_path(
        "agent-1",
        "user-1",
        AGENT_WORKSPACE_ROOT.as_posix(),
    )

    assert isinstance(result, Success)
    assert result.value.type == "DIRECTORY"
    assert result.value.path == AGENT_WORKSPACE_ROOT.as_posix()
    assert [entry.name for entry in result.value.entries] == [
        "README.md",
        "test-file.txt",
    ]
    assert runner_operations.stat_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]
    assert runner_operations.read_calls == []
    assert runner_operations.list_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]


def _make_agent_runtime(
    *,
    workspace_path: str | None = AGENT_WORKSPACE_ROOT.as_posix(),
    provider_observed_state: RuntimeProviderObservedState | None = None,
    desired_state: RuntimeDesiredState | None = None,
) -> AgentRuntime:
    if provider_observed_state is None:
        provider_observed_state = RuntimeProviderObservedState.RUNNING
    if desired_state is None:
        desired_state = (
            RuntimeDesiredState.RUNNING
            if provider_observed_state == RuntimeProviderObservedState.RUNNING
            else RuntimeDesiredState.STOPPED
        )
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        desired_state=desired_state,
        provider_observed_state=provider_observed_state,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=1,
        workspace_path=workspace_path,
        created_at=_NOW,
        updated_at=_NOW,
    )
