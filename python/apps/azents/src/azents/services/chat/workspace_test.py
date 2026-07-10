"""Agent Workspace service tests."""

import contextlib
import datetime
from collections.abc import AsyncGenerator

import pytest
from azcommon.result import Failure, Success
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
    RuntimeFileBulkDeleteResult,
    RuntimeFileBulkMoveResult,
    RuntimeFileDeleteResult,
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileMkdirResult,
    RuntimeFileMoveEntry,
    RuntimeFileMoveResult,
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
        self.directories = {AGENT_WORKSPACE_ROOT.as_posix()}
        self.list_calls: list[tuple[str, int, str]] = []
        self.read_calls: list[tuple[str, int, str]] = []
        self.stat_calls: list[tuple[str, int, str]] = []
        self.delete_calls: list[tuple[str, int, str, bool]] = []
        self.mkdir_calls: list[tuple[str, int, str, bool]] = []
        self.move_calls: list[tuple[str, int, str, str, bool]] = []
        self.bulk_delete_calls: list[tuple[str, int, tuple[str, ...], bool]] = []
        self.bulk_move_calls: list[tuple[str, int, tuple[str, ...], str, bool]] = []

    async def bulk_move_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_paths: list[str],
        destination_directory: str,
        overwrite: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileBulkMoveResult:
        """Record a fake bulk move operation."""
        del deadline_at
        self.bulk_move_calls.append(
            (
                runtime_id,
                runner_generation,
                tuple(source_paths),
                destination_directory,
                overwrite,
            )
        )
        entries: list[RuntimeFileMoveEntry] = []
        for source_path in source_paths:
            if source_path not in self.files:
                raise RuntimeRunnerOperationFailedError(
                    f"NOT_FOUND: No such file: {source_path}"
                )
            destination_path = (
                f"{destination_directory}/{source_path.rsplit('/', 1)[-1]}"
            )
            self.files[destination_path] = self.files.pop(source_path)
            entries.append(
                RuntimeFileMoveEntry(
                    source_path=source_path,
                    destination_path=destination_path,
                )
            )
        return RuntimeFileBulkMoveResult(entries=tuple(entries), final_cursor="0-1")

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileListResult:
        del recursive, exclude_patterns, deadline_at
        self.list_calls.append((runtime_id, runner_generation, path))
        entries: list[RuntimeFileListEntry] = []
        for directory_path in sorted(self.directories):
            if directory_path == path or directory_path.rsplit("/", 1)[0] != path:
                continue
            entries.append(
                RuntimeFileListEntry(
                    path=directory_path,
                    type="directory",
                    size_bytes=None,
                    modified_at="2026-05-24T00:00:00+00:00",
                )
            )
        for file_path, data in sorted(self.files.items()):
            if file_path.rsplit("/", 1)[0] != path:
                continue
            entries.append(
                RuntimeFileListEntry(
                    path=file_path,
                    type="file",
                    size_bytes=len(data),
                    modified_at="2026-05-24T00:00:00+00:00",
                )
            )
        return RuntimeFileListResult(entries=tuple(entries), final_cursor="0-1")

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
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
        owner_session_id: str | None = None,
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
                modified_at="2026-05-24T00:00:00+00:00",
                final_cursor="0-1",
            )
        if path in self.directories:
            return RuntimeFileStatResult(
                path=path,
                kind="directory",
                size_bytes=None,
                symlink=False,
                real_path=None,
                resolved_kind=None,
                modified_at="2026-05-24T00:00:00+00:00",
                final_cursor="0-1",
            )
        raise RuntimeRunnerOperationFailedError(f"NOT_FOUND: No such file: {path}")

    async def delete_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileDeleteResult:
        """Record a fake delete file operation."""
        del deadline_at
        self.delete_calls.append((runtime_id, runner_generation, path, recursive))
        if path not in self.files:
            raise RuntimeRunnerOperationFailedError(f"NOT_FOUND: No such file: {path}")
        del self.files[path]
        return RuntimeFileDeleteResult(path=path, final_cursor="0-1")

    async def bulk_delete_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        paths: list[str],
        recursive: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileBulkDeleteResult:
        """Record a fake bulk delete operation."""
        del deadline_at
        self.bulk_delete_calls.append(
            (runtime_id, runner_generation, tuple(paths), recursive)
        )
        for path in paths:
            if path not in self.files:
                raise RuntimeRunnerOperationFailedError(
                    f"NOT_FOUND: No such file: {path}"
                )
        for path in paths:
            del self.files[path]
        return RuntimeFileBulkDeleteResult(paths=tuple(paths), final_cursor="0-1")

    async def mkdir_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        parents: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileMkdirResult:
        """Record a fake mkdir file operation."""
        del deadline_at
        self.mkdir_calls.append((runtime_id, runner_generation, path, parents))
        return RuntimeFileMkdirResult(path=path, final_cursor="0-1")

    async def move_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        source_path: str,
        destination_path: str,
        overwrite: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileMoveResult:
        """Record a fake move file operation."""
        del deadline_at
        self.move_calls.append(
            (runtime_id, runner_generation, source_path, destination_path, overwrite)
        )
        if source_path not in self.files:
            raise RuntimeRunnerOperationFailedError(
                f"NOT_FOUND: No such file: {source_path}"
            )
        self.files[destination_path] = self.files.pop(source_path)
        return RuntimeFileMoveResult(
            source_path=source_path,
            destination_path=destination_path,
            final_cursor="0-1",
        )


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


@pytest.mark.asyncio
async def test_read_path_marks_git_repository_directories() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    plain_path = (AGENT_WORKSPACE_ROOT / "plain").as_posix()
    git_directory_path = (AGENT_WORKSPACE_ROOT / "repo-dir").as_posix()
    worktree_path = (AGENT_WORKSPACE_ROOT / "repo-worktree").as_posix()
    runner_operations.directories.update(
        {
            plain_path,
            git_directory_path,
            (AGENT_WORKSPACE_ROOT / "repo-dir" / ".git").as_posix(),
            worktree_path,
        }
    )
    runner_operations.files[
        (AGENT_WORKSPACE_ROOT / "repo-worktree" / ".git").as_posix()
    ] = b"gitdir: ../.git/worktrees/repo-worktree\n"
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
    repository_types = {
        entry.name: entry.repository_type for entry in result.value.entries
    }
    assert repository_types["plain"] is None
    assert repository_types["repo-dir"] == "git"
    assert repository_types["repo-worktree"] == "git"


@pytest.mark.asyncio
async def test_stat_path_returns_inspector_metadata() -> None:
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

    result = await service.stat_path("agent-1", "user-1", file_path)

    assert isinstance(result, Success)
    assert result.value.path == file_path
    assert result.value.name == "README.md"
    assert result.value.kind == "file"
    assert result.value.size == 12
    assert result.value.media_type == "text/markdown"
    assert result.value.modified_at == datetime.datetime(
        2026, 5, 24, tzinfo=datetime.UTC
    )


@pytest.mark.asyncio
async def test_mkdir_path_calls_runner_with_normalized_path() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.mkdir_path("agent-1", "user-1", "reports", parents=False)

    assert isinstance(result, Success)
    assert result.value.path == (AGENT_WORKSPACE_ROOT / "reports").as_posix()
    assert runner_operations.mkdir_calls == [
        ("runtime-1", 1, (AGENT_WORKSPACE_ROOT / "reports").as_posix(), False)
    ]


@pytest.mark.asyncio
async def test_delete_path_rejects_workspace_root() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.delete_path(
        "agent-1",
        "user-1",
        AGENT_WORKSPACE_ROOT.as_posix(),
        recursive=True,
    )

    assert isinstance(result, Failure)
    assert runner_operations.delete_calls == []


@pytest.mark.asyncio
async def test_move_path_rejects_destination_outside_workspace_root() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )

    result = await service.move_path(
        "agent-1",
        "user-1",
        (AGENT_WORKSPACE_ROOT / "README.md").as_posix(),
        "/etc/passwd",
        overwrite=False,
    )

    assert isinstance(result, Failure)
    assert runner_operations.move_calls == []


@pytest.mark.asyncio
async def test_move_path_calls_runner_for_rename() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )
    source = (AGENT_WORKSPACE_ROOT / "README.md").as_posix()
    destination = (AGENT_WORKSPACE_ROOT / "README-renamed.md").as_posix()

    result = await service.move_path(
        "agent-1",
        "user-1",
        source,
        destination,
        overwrite=False,
    )

    assert isinstance(result, Success)
    assert result.value.source_path == source
    assert result.value.destination_path == destination
    assert runner_operations.move_calls == [
        ("runtime-1", 1, source, destination, False)
    ]


@pytest.mark.asyncio
async def test_bulk_delete_paths_calls_runner() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )
    first = (AGENT_WORKSPACE_ROOT / "README.md").as_posix()
    second = (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix()

    result = await service.bulk_delete_paths(
        "agent-1", "user-1", [first, second], recursive=False
    )

    assert isinstance(result, Success)
    assert result.value.paths == [first, second]
    assert runner_operations.bulk_delete_calls == [
        ("runtime-1", 1, (first, second), False)
    ]


@pytest.mark.asyncio
async def test_bulk_move_paths_calls_runner() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,  # pyright: ignore[reportArgumentType]
        runtime_repository=_FakeRuntimeRepository(runtime),
        session_manager=_session_manager,
    )
    first = (AGENT_WORKSPACE_ROOT / "README.md").as_posix()
    second = (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix()
    destination = (AGENT_WORKSPACE_ROOT / "archive").as_posix()

    result = await service.bulk_move_paths(
        "agent-1",
        "user-1",
        [first, second],
        destination,
        overwrite=False,
    )

    assert isinstance(result, Success)
    assert [entry.source_path for entry in result.value.entries] == [first, second]
    assert runner_operations.bulk_move_calls == [
        ("runtime-1", 1, (first, second), destination, False)
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
