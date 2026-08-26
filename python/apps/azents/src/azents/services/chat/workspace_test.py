"""Agent Workspace service tests."""

import contextlib
import datetime
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import cast

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeActions
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
    RuntimeFileTextReadResult,
    RuntimeRunnerOperationFailedError,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.runtime.transfer.workspace_download import (
    RuntimeWorkspaceDownloadService,
    WorkspaceDownloadRequest,
)
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeLifecycleSnapshot,
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.chat.workspace import AgentWorkspaceFileService
from azents.services.runtime_storage_error import RuntimeStorageError

AGENT_WORKSPACE_ROOT = PurePosixPath("/runtime/home")

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
                role=WorkspaceUserRole.MEMBER,
                created_at=_NOW,
                updated_at=_NOW,
            )
        return None


class _FakeRuntimeTargetResolver(RuntimeOperationTargetResolver):
    """Resolve a target from the configured Runtime fixture."""

    def __init__(self, runtime: AgentRuntime | None) -> None:
        self.runtime = runtime
        self.resolve_calls: list[tuple[float, bool]] = []

    async def get_lifecycle_snapshot(
        self,
        agent_id: str,
    ) -> AgentRuntimeLifecycleSnapshot:
        """Return the shared lifecycle fixture."""
        del agent_id
        runtime = self.runtime
        if runtime is None:
            return AgentRuntimeLifecycleSnapshot(
                runtime=None,
                lifecycle=None,
                actions=AgentRuntimeActions(
                    start=False,
                    stop=False,
                    restart=False,
                    reset=False,
                    use_runner=False,
                ),
            )
        service = object.__new__(AgentRuntimeService)
        configuration = None
        return AgentRuntimeLifecycleSnapshot(
            runtime=runtime,
            lifecycle=service.calculate_lifecycle(
                runtime,
                configuration=configuration,
                removing=False,
            ),
            actions=service._calculate_lifecycle_actions(
                runtime,
                configuration=configuration,
                removing=False,
            ),
        )

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Return qualified fixture evidence or the normal bounded error."""
        del agent_id, poll_interval_seconds, expected_authority
        self.resolve_calls.append((wait_timeout_seconds, start_if_stopped))
        runtime = self.runtime
        if (
            runtime is None
            or runtime.provider_observed_state
            is not RuntimeProviderObservedState.RUNNING
            or runtime.runner_state is not RuntimeRunnerState.READY
            or runtime.workspace_path is None
        ):
            raise RuntimeStorageError("Runtime runner is not ready.")
        return RuntimeOperationTarget(
            id=runtime.id,
            runtime_capability_version=1,
            desired_generation=runtime.desired_generation,
            runner_generation=runtime.runner_generation,
            configuration_sequence=1,
            configuration_digest="a" * 64,
            workspace_path=runtime.workspace_path,
        )


class _FakeRunnerOperations:
    def __init__(self) -> None:
        self.files = {
            (AGENT_WORKSPACE_ROOT / "README.md").as_posix(): b"# Workspace\n",
            (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix(): b"hello",
        }
        self.directories = {AGENT_WORKSPACE_ROOT.as_posix()}
        self.list_calls: list[tuple[str, int, str]] = []
        self.read_calls: list[tuple[str, int, str]] = []
        self.text_read_calls: list[tuple[str, int, int, str]] = []
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

    async def read_text_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        character_offset: int,
        max_characters: int,
        encoding: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileTextReadResult:
        """Return one bounded decoded preview character range."""
        del runtime_id, runner_generation, owner_session_id, deadline_at
        self.text_read_calls.append((path, character_offset, max_characters, encoding))
        text = self.files[path].decode(encoding)
        chunk = text[character_offset : character_offset + max_characters]
        return RuntimeFileTextReadResult(
            text=chunk,
            start_character=character_offset,
            end_character=character_offset + len(chunk),
            truncated=character_offset + len(chunk) < len(text),
            final_cursor="0-1",
        )

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


@dataclass
class _FakeRuntimeWorkspaceDownloadService:
    """Record authorized Workspace download transfer requests."""

    body: bytes = b"workspace download"
    calls: list[WorkspaceDownloadRequest] = field(default_factory=list)

    async def download(self, request: WorkspaceDownloadRequest) -> bytes:
        """Return configured verified transfer bytes."""
        self.calls.append(request)
        return self.body


@contextlib.asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield one unused but correctly typed test session."""
    session = AsyncSession()
    try:
        yield session
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_workspace_reads_active_runtime_with_runner() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    target_resolver = _FakeRuntimeTargetResolver(runtime)
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=target_resolver,
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    state = result.value
    assert state.lifecycle is not None
    assert state.lifecycle.availability == "ready"
    assert state.lifecycle.convergence == "stable"
    assert state.runtime.type == "RUNNING"
    assert state.workspace.type == "READY"
    assert state.actions.stop is not None
    assert state.actions.stop.type == "STOP_RUNTIME"
    assert state.actions.restart is not None
    assert state.actions.restart.type == "RESTART_RUNTIME"
    assert target_resolver.resolve_calls == [(0.0, False)]
    assert runner_operations.list_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]
    assert [entry.path for entry in state.workspace.manifest.entries] == [
        (AGENT_WORKSPACE_ROOT / "README.md").as_posix(),
        (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix(),
    ]


@pytest.mark.asyncio
async def test_get_workspace_keeps_ready_runner_when_host_controls_disconnect() -> None:
    """Runner access remains available without Provider host authority."""
    runtime = _make_agent_runtime(
        provider_connection_state=RuntimeProviderConnectionState.DISCONNECTED
    )
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    state = result.value
    assert state.lifecycle is not None
    assert state.lifecycle.availability == "ready"
    assert state.workspace.type == "READY"
    assert state.actions.start is None
    assert state.actions.stop is None
    assert state.actions.restart is None
    assert state.actions.reset is None
    assert runner_operations.list_calls == [
        ("runtime-1", 1, AGENT_WORKSPACE_ROOT.as_posix())
    ]


@pytest.mark.asyncio
async def test_get_workspace_exposes_restart_without_waiting_for_runner() -> None:
    """Provider-observed Runtime exposes recovery before Runner is ready."""
    runtime = _make_agent_runtime(runner_state=RuntimeRunnerState.DISCONNECTED)
    target_resolver = _FakeRuntimeTargetResolver(runtime)
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=_FakeRunnerOperations(),
        runtime_target_resolver=target_resolver,
        session_manager=_session_manager,
    )

    result = await service.get_workspace("agent-1", "user-1")

    assert isinstance(result, Success)
    assert result.value.lifecycle is not None
    assert result.value.lifecycle.availability == "runner_unavailable"
    assert result.value.lifecycle.reason_code == "runner_disconnected"
    assert result.value.runtime.type == "RUNNING"
    assert result.value.workspace.type == "CONTROL_UNAVAILABLE"
    assert result.value.actions.restart is not None
    assert result.value.actions.restart.type == "RESTART_RUNTIME"
    assert target_resolver.resolve_calls == [(0.0, False)]


@pytest.mark.asyncio
async def test_get_workspace_uses_agent_runtime_without_session_match() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=_FakeRunnerOperations(),
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=_FakeRunnerOperations(),
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=_FakeRunnerOperations(),
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
        session_manager=_session_manager,
    )
    file_path = (AGENT_WORKSPACE_ROOT / "README.md").as_posix()

    result = await service.read_path("agent-1", "user-1", file_path)

    assert isinstance(result, Success)
    assert result.value.type == "FILE"
    assert result.value.path == file_path
    assert result.value.media_type == "text/markdown"
    assert result.value.text == "# Workspace\n"
    assert runner_operations.read_calls == []
    assert runner_operations.text_read_calls == [(file_path, 0, 64 * 1024, "utf-8")]
    assert runner_operations.stat_calls == [("runtime-1", 1, file_path)]
    assert runner_operations.list_calls == []


@pytest.mark.asyncio
async def test_text_preview_uses_character_limit_not_file_byte_size() -> None:
    """Multibyte text is bounded by decoded characters and reports truncation."""
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    file_path = (AGENT_WORKSPACE_ROOT / "large.txt").as_posix()
    runner_operations.files[file_path] = ("가" * (64 * 1024 + 1)).encode()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
        session_manager=_session_manager,
    )

    result = await service.read_path("agent-1", "user-1", file_path)

    assert isinstance(result, Success)
    assert result.value.type == "FILE"
    assert result.value.text is not None
    assert len(result.value.text) == 64 * 1024
    assert result.value.truncated is True


@pytest.mark.asyncio
async def test_download_uses_verified_transfer_not_runner_file_read() -> None:
    """Complete Workspace downloads avoid the Runner Control file body path."""
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    transfer = _FakeRuntimeWorkspaceDownloadService()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
        session_manager=_session_manager,
        runtime_workspace_download_service=cast(
            RuntimeWorkspaceDownloadService,
            transfer,
        ),
    )
    file_path = (AGENT_WORKSPACE_ROOT / "test-file.txt").as_posix()

    result = await service.download_file("agent-1", "user-1", file_path)

    assert isinstance(result, Success)
    assert result.value == (
        AGENT_WORKSPACE_ROOT / "test-file.txt",
        b"workspace download",
        "text/plain",
    )
    assert runner_operations.read_calls == []
    assert transfer.calls == [
        WorkspaceDownloadRequest(
            agent_id="agent-1",
            runtime_path=file_path,
            expected_size=5,
            target=ServerToRuntimeTarget(
                runtime_id="runtime-1",
                desired_generation=7,
            ),
        )
    ]


@pytest.mark.asyncio
async def test_read_path_uses_stat_to_return_directory_listing() -> None:
    runtime = _make_agent_runtime()
    runner_operations = _FakeRunnerOperations()
    service = AgentWorkspaceFileService(
        agent_repository=_FakeAgentRepository(),
        workspace_user_repository=_FakeWorkspaceUserRepository(),
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
        runner_operations=runner_operations,
        runtime_target_resolver=_FakeRuntimeTargetResolver(runtime),
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
    provider_connection_state: RuntimeProviderConnectionState = (
        RuntimeProviderConnectionState.CONNECTED
    ),
    desired_state: RuntimeDesiredState | None = None,
    desired_generation: int = 7,
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
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
        terminal_delete_acknowledgement_kind=None,
        desired_state=desired_state,
        desired_generation=desired_generation,
        provider_connection_state=provider_connection_state,
        provider_observed_state=provider_observed_state,
        runner_state=runner_state,
        runner_generation=1,
        workspace_path=workspace_path,
        created_at=_NOW,
        updated_at=_NOW,
    )
