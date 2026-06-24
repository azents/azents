"""Agent Workspace file browser service."""

import dataclasses
import mimetypes
import posixpath
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal, TypeVar, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileListEntry,
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client

from .data import (
    AgentNotFound,
    NotWorkspaceMember,
    SessionAccessDenied,
    SessionNotFound,
)

AGENT_WORKSPACE_ROOT = PurePosixPath("/workspace/agent")
_DEFAULT_TEXT_PREVIEW_LIMIT = 64 * 1024
_DEFAULT_MEDIA_TYPE = "application/octet-stream"
_AGENT_REPOSITORY_DEP = Depends(AgentRepository)
_WORKSPACE_USER_REPOSITORY_DEP = Depends(WorkspaceUserRepository)
_RUNNER_OPERATION_CLIENT_DEP = Depends(get_runtime_runner_operation_client)
_RUNTIME_REPOSITORY_DEP = Depends(AgentRuntimeRepository)
_SESSION_MANAGER_DEP = Depends(get_session_manager)
_RUNNER_FILE_OPERATION_TIMEOUT_SECONDS = 120
_T = TypeVar("_T")


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceAction:
    """Agent Workspace state transition action."""

    type: Literal["START_RUNTIME", "STOP_RUNTIME", "RESTART_RUNTIME", "RESET_RUNTIME"]
    method: Literal["POST"]
    path: str


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceEntry:
    """Agent Workspace directory entry."""

    name: str
    path: str
    kind: Literal["file", "directory"]
    size: int | None
    media_type: str | None
    modified_at: datetime | None


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceManifest:
    """Agent Workspace panel bootstrap manifest."""

    root: str
    cwd: str
    entries: list[AgentWorkspaceEntry]
    git: dict[str, object] | None


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceRuntime:
    """Server-computed Agent Runtime state."""

    type: Literal[
        "NOT_STARTED",
        "STARTING",
        "RUNNING",
        "HIBERNATED",
        "STOPPING",
        "RESETTING",
        "RESTORE_FAILED",
        "LOST",
    ]
    runtime_id: str | None
    workspace_path: str | None = None
    detail: str | None = None


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceAccessUnavailable:
    """Workspace access is unavailable because Runtime is absent or unusable."""

    type: Literal["UNAVAILABLE"]
    reason: Literal["RUNTIME_NOT_RUNNING", "WORKSPACE_PATH_UNAVAILABLE"]


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceAccessConnecting:
    """State where workspace access must wait during Runtime transition."""

    type: Literal["CONNECTING"]


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceControlUnavailable:
    """State where Provider runtime is running but control route is not ready."""

    type: Literal["CONTROL_UNAVAILABLE"]
    detail: str
    retry_after_ms: int


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceReadFailed:
    """State where Provider runtime is running but workspace read/list failed."""

    type: Literal["READ_FAILED"]
    detail: str


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceReady:
    """State where workspace manifest can be read through Runner."""

    type: Literal["READY"]
    manifest: AgentWorkspaceManifest


AgentWorkspaceAccessState = (
    AgentWorkspaceAccessUnavailable
    | AgentWorkspaceAccessConnecting
    | AgentWorkspaceControlUnavailable
    | AgentWorkspaceReadFailed
    | AgentWorkspaceReady
)


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceActions:
    """Explicit action user can perform for Provider runtime."""

    start: AgentWorkspaceAction | None = None
    stop: AgentWorkspaceAction | None = None
    restart: AgentWorkspaceAction | None = None
    reset: AgentWorkspaceAction | None = None


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceState:
    """Workspace panel state. Express Runtime and workspace access separately."""

    runtime: AgentWorkspaceRuntime
    workspace: AgentWorkspaceAccessState
    actions: AgentWorkspaceActions


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceDirectory:
    """Agent Workspace directory fetch result."""

    type: Literal["DIRECTORY"]
    path: str
    entries: list[AgentWorkspaceEntry]


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceFile:
    """Agent Workspace file preview fetch result."""

    type: Literal["FILE"]
    path: str
    media_type: str
    size: int
    text: str | None
    truncated: bool


AgentWorkspaceFileResult = AgentWorkspaceDirectory | AgentWorkspaceFile


class AgentWorkspacePathDenied(RuntimeError):
    """Path access outside Agent Workspace root."""


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceRuntimeInactive:
    """Runtime is inactive."""

    action: AgentWorkspaceAction


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceFileNotFound:
    """Agent Workspace file not found."""


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceFileReadError:
    """Known daemon error while fetching Agent Workspace file."""

    detail: str


@dataclasses.dataclass(frozen=True)
class AgentWorkspaceFileTooLarge:
    """Agent Workspace file preview limit exceeded."""

    size: int
    limit: int


class AgentWorkspacePathUnavailable(RuntimeError):
    """Provider has not reported Agent Workspace path yet."""


AgentWorkspaceError = (
    AgentNotFound
    | NotWorkspaceMember
    | SessionNotFound
    | SessionAccessDenied
    | AgentWorkspacePathDenied
    | AgentWorkspaceRuntimeInactive
    | AgentWorkspaceFileNotFound
    | AgentWorkspaceFileReadError
    | AgentWorkspaceFileTooLarge
    | AgentWorkspacePathUnavailable
)


def agent_workspace_root(workspace_path: str | None) -> PurePosixPath:
    """Return Agent Workspace root reported by Provider.

    :param workspace_path: Agent Workspace absolute path in Runtime metadata
    :return: Normalized Agent Workspace root
    """
    if workspace_path is None or not workspace_path.strip():
        raise AgentWorkspacePathUnavailable()
    path = PurePosixPath(posixpath.normpath(workspace_path.strip()))
    if not path.is_absolute():
        raise AgentWorkspacePathUnavailable()
    return path


def normalize_agent_workspace_path(
    raw_path: str | None,
    *,
    workspace_root: PurePosixPath = AGENT_WORKSPACE_ROOT,
) -> PurePosixPath:
    """Normalize request path as absolute path under Agent Workspace root.

    :param raw_path: Request path
    :param workspace_root: Agent Workspace root reported by Provider
    :return: Normalized Agent Workspace path
    :raises AgentWorkspacePathDenied: When path is outside Agent Workspace root
    """
    if raw_path is None or raw_path in {"", "."}:
        return workspace_root
    path = PurePosixPath(raw_path)
    if not path.is_absolute():
        path = workspace_root / path
    normalized = PurePosixPath(posixpath.normpath(path.as_posix()))
    if normalized != workspace_root and workspace_root not in normalized.parents:
        raise AgentWorkspacePathDenied()
    return normalized


def _guess_media_type(path: PurePosixPath) -> str:
    """Infer media type from filename."""
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or _DEFAULT_MEDIA_TYPE


def _start_action(agent_id: str) -> AgentWorkspaceAction:
    """Create Runtime start action descriptor."""
    del agent_id
    return AgentWorkspaceAction(
        type="START_RUNTIME",
        method="POST",
        path="",
    )


def _stop_action(agent_id: str) -> AgentWorkspaceAction:
    """Create Runtime stop action descriptor."""
    del agent_id
    return AgentWorkspaceAction(
        type="STOP_RUNTIME",
        method="POST",
        path="",
    )


def _reset_action(agent_id: str) -> AgentWorkspaceAction:
    """Create Runtime reset action descriptor."""
    del agent_id
    return AgentWorkspaceAction(
        type="RESET_RUNTIME",
        method="POST",
        path="",
    )


def _restart_action(agent_id: str) -> AgentWorkspaceAction:
    """Create Runtime restart action descriptor."""
    del agent_id
    return AgentWorkspaceAction(
        type="RESTART_RUNTIME",
        method="POST",
        path="",
    )


def _actions_for_runtime(
    agent_id: str,
    runtime: AgentWorkspaceRuntime,
) -> AgentWorkspaceActions:
    """Return lifecycle action set matching Provider runtime state."""
    match runtime.type:
        case "NOT_STARTED":
            return AgentWorkspaceActions(start=_start_action(agent_id))
        case "RUNNING":
            return AgentWorkspaceActions(
                stop=_stop_action(agent_id),
                reset=_reset_action(agent_id),
            )
        case "HIBERNATED":
            return AgentWorkspaceActions(
                start=_start_action(agent_id),
                reset=_reset_action(agent_id),
            )
        case "RESTORE_FAILED" | "LOST":
            return AgentWorkspaceActions(
                start=_start_action(agent_id),
                stop=_stop_action(agent_id),
                restart=_restart_action(agent_id),
                reset=_reset_action(agent_id),
            )
        case "STARTING" | "RESETTING":
            return AgentWorkspaceActions(stop=_stop_action(agent_id))
        case "STOPPING":
            return AgentWorkspaceActions()


class AgentWorkspaceFileService:
    """Agent Workspace file fetch service."""

    def __init__(
        self,
        agent_repository: AgentRepository = _AGENT_REPOSITORY_DEP,
        workspace_user_repository: WorkspaceUserRepository = (
            _WORKSPACE_USER_REPOSITORY_DEP
        ),
        runner_operations: RuntimeRunnerOperationClient = _RUNNER_OPERATION_CLIENT_DEP,
        runtime_repository: AgentRuntimeRepository = _RUNTIME_REPOSITORY_DEP,
        session_manager: SessionManager[AsyncSession] = _SESSION_MANAGER_DEP,
    ) -> None:
        self._agent_repository = agent_repository
        self._workspace_user_repository = workspace_user_repository
        self._runner_operations = runner_operations
        self._runtime_repository = runtime_repository
        self._session_manager = session_manager

    async def get_workspace(
        self,
        agent_id: str,
        user_id: str,
    ) -> Result[AgentWorkspaceState, AgentWorkspaceError]:
        """Return Agent Workspace bootstrap state."""
        access_result = await self._get_agent_for_user(agent_id, user_id=user_id)
        match access_result:
            case Success(agent):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access_result)

        runtime = await self._get_runtime(agent.id)
        return await self._workspace_panel_state(
            agent,
            runtime=runtime,
            user_id=user_id,
        )

    async def _get_agent_for_user(
        self,
        agent_id: str,
        *,
        user_id: str,
    ) -> Result[Agent, AgentWorkspaceError]:
        """Fetch Agent and check workspace membership."""
        async with self._session_manager() as session:
            agent = await self._agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self._workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            return Success(agent)

    async def _get_runtime(
        self,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Fetch AgentRuntime."""
        async with self._session_manager() as session:
            return await self._runtime_repository.get_by_agent_id(session, agent_id)

    async def _ensure_runtime(self, agent_id: str) -> AgentRuntime:
        """Ensure AgentRuntime."""
        async with self._session_manager() as session:
            return await self._runtime_repository.ensure_for_agent(session, agent_id)

    async def _workspace_panel_state(
        self,
        agent: Agent,
        *,
        runtime: AgentRuntime | None,
        user_id: str,
    ) -> Result[AgentWorkspaceState, AgentWorkspaceError]:
        """Return Provider runtime and workspace access separately."""
        runtime_panel = self._runtime_panel_state(runtime)
        workspace_state = await self._workspace_access_state(
            agent,
            runtime_panel=runtime_panel,
            user_id=user_id,
        )
        return Success(
            AgentWorkspaceState(
                runtime=runtime_panel,
                workspace=workspace_state,
                actions=_actions_for_runtime(agent.id, runtime_panel),
            )
        )

    def _runtime_panel_state(
        self,
        runtime: AgentRuntime | None,
    ) -> AgentWorkspaceRuntime:
        """Convert Agent Runtime raw axes to workspace panel state."""
        if runtime is None:
            return AgentWorkspaceRuntime(type="NOT_STARTED", runtime_id=None)
        failure_detail = _current_runtime_failure_detail(runtime)
        if failure_detail is not None:
            return AgentWorkspaceRuntime(
                type="LOST",
                runtime_id=runtime.id,
                workspace_path=runtime.workspace_path,
                detail=failure_detail,
            )
        match runtime.provider_observed_state:
            case RuntimeProviderObservedState.RUNNING:
                return AgentWorkspaceRuntime(
                    type="RUNNING",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )
            case (
                RuntimeProviderObservedState.STARTING
                | RuntimeProviderObservedState.RECOVERING
            ):
                return AgentWorkspaceRuntime(
                    type="STARTING",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )
            case RuntimeProviderObservedState.STOPPING:
                return AgentWorkspaceRuntime(
                    type="STOPPING",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )
            case RuntimeProviderObservedState.RESETTING:
                return AgentWorkspaceRuntime(
                    type="RESETTING",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )
            case RuntimeProviderObservedState.STOPPED:
                if runtime.desired_state == RuntimeDesiredState.RUNNING:
                    return AgentWorkspaceRuntime(
                        type="STARTING",
                        runtime_id=runtime.id,
                        workspace_path=runtime.workspace_path,
                    )
                return AgentWorkspaceRuntime(
                    type="NOT_STARTED",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )
            case RuntimeProviderObservedState.FAILED:
                return AgentWorkspaceRuntime(
                    type="LOST",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                    detail="Runtime provider reported failure.",
                )
            case RuntimeProviderObservedState.UNKNOWN:
                if runtime.desired_state == RuntimeDesiredState.RUNNING:
                    return AgentWorkspaceRuntime(
                        type="STARTING",
                        runtime_id=runtime.id,
                        workspace_path=runtime.workspace_path,
                    )
                return AgentWorkspaceRuntime(
                    type="NOT_STARTED",
                    runtime_id=runtime.id,
                    workspace_path=runtime.workspace_path,
                )

    async def _workspace_access_state(
        self,
        agent: Agent,
        *,
        runtime_panel: AgentWorkspaceRuntime,
        user_id: str,
    ) -> AgentWorkspaceAccessState:
        """Return workspace access state owned by Runner."""
        if runtime_panel.type in {"STARTING", "RESETTING"}:
            return AgentWorkspaceAccessConnecting(type="CONNECTING")
        if runtime_panel.type != "RUNNING":
            return AgentWorkspaceAccessUnavailable(
                type="UNAVAILABLE",
                reason="RUNTIME_NOT_RUNNING",
            )
        runtime_id = runtime_panel.runtime_id
        if runtime_id is None:
            return AgentWorkspaceControlUnavailable(
                type="CONTROL_UNAVAILABLE",
                detail="Agent runtime id is unavailable.",
                retry_after_ms=1000,
            )
        try:
            workspace_root = agent_workspace_root(runtime_panel.workspace_path)
        except AgentWorkspacePathUnavailable:
            return AgentWorkspaceAccessUnavailable(
                type="UNAVAILABLE",
                reason="WORKSPACE_PATH_UNAVAILABLE",
            )
        runtime = await self._get_runtime(agent.id)
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            return AgentWorkspaceControlUnavailable(
                type="CONTROL_UNAVAILABLE",
                detail="Runtime runner is not ready.",
                retry_after_ms=1000,
            )
        ready = await self._ready_access(
            runtime,
            workspace_root=workspace_root,
        )
        match ready:
            case Success(access):
                return access
            case Failure(AgentWorkspaceFileReadError(detail=detail)):
                if _is_runner_unavailable_detail(detail):
                    return AgentWorkspaceControlUnavailable(
                        type="CONTROL_UNAVAILABLE",
                        detail=detail,
                        retry_after_ms=1000,
                    )
                return AgentWorkspaceReadFailed(type="READ_FAILED", detail=detail)
            case Failure(error):
                return AgentWorkspaceReadFailed(type="READ_FAILED", detail=str(error))
            case _:
                assert_never(ready)

    async def read_path(
        self,
        agent_id: str,
        user_id: str,
        raw_path: str | None,
        *,
        limit: int = _DEFAULT_TEXT_PREVIEW_LIMIT,
    ) -> Result[AgentWorkspaceFileResult, AgentWorkspaceError]:
        """Fetch Agent Workspace directory or file preview."""
        access = await self._ensure_active_runtime(agent_id, user_id)
        match access:
            case Success(runtime):
                try:
                    workspace_root = agent_workspace_root(runtime.workspace_path)
                except AgentWorkspacePathUnavailable as error:
                    return Failure(error)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        try:
            path = normalize_agent_workspace_path(
                raw_path,
                workspace_root=workspace_root,
            )
        except AgentWorkspacePathDenied as error:
            return Failure(error)

        stat_result = await self._stat_path(runtime, path)
        match stat_result:
            case Success(stat):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(stat_result)

        target_kind = stat.resolved_kind if stat.kind == "symlink" else stat.kind
        match target_kind:
            case "directory":
                entries_result = await self._list_entries(runtime, path)
                match entries_result:
                    case Success(entries):
                        return Success(
                            AgentWorkspaceDirectory(
                                type="DIRECTORY",
                                path=path.as_posix(),
                                entries=entries,
                            )
                        )
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(entries_result)
            case "file":
                read_result = await self._read_file(runtime, path, limit=limit)
                match read_result:
                    case Success(file):
                        return Success(file)
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(read_result)
            case "missing":
                return Failure(AgentWorkspaceFileNotFound())
            case "symlink" | "other" | None:
                return Failure(
                    AgentWorkspaceFileReadError(
                        detail=f"Unsupported Agent Workspace path type: {stat.kind}.",
                    )
                )

    async def download_file(
        self,
        agent_id: str,
        user_id: str,
        raw_path: str,
    ) -> Result[tuple[PurePosixPath, bytes, str], AgentWorkspaceError]:
        """Return Agent Workspace file download data."""
        access = await self._ensure_active_runtime(agent_id, user_id)
        match access:
            case Success(runtime):
                try:
                    workspace_root = agent_workspace_root(runtime.workspace_path)
                except AgentWorkspacePathUnavailable as error:
                    return Failure(error)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access)

        try:
            path = normalize_agent_workspace_path(
                raw_path,
                workspace_root=workspace_root,
            )
        except AgentWorkspacePathDenied as error:
            return Failure(error)

        read_result = await self._runner_read_file(runtime, path, max_bytes=None)
        match read_result:
            case Success(data):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(read_result)
        return Success((path, data, _guess_media_type(path)))

    async def _ready_access(
        self,
        runtime: AgentRuntime,
        *,
        workspace_root: PurePosixPath,
    ) -> Result[AgentWorkspaceReady, AgentWorkspaceError]:
        """Build READY Agent Workspace access state."""
        entries_result = await self._list_entries(runtime, workspace_root)
        match entries_result:
            case Success(entries):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(entries_result)
        return Success(
            AgentWorkspaceReady(
                type="READY",
                manifest=AgentWorkspaceManifest(
                    root=workspace_root.as_posix(),
                    cwd=workspace_root.as_posix(),
                    entries=entries,
                    git=None,
                ),
            )
        )

    async def _ensure_active_runtime(
        self,
        agent_id: str,
        user_id: str,
    ) -> Result[AgentRuntime, AgentWorkspaceError]:
        """Check Agent access permission and Runtime active state."""
        access_result = await self._get_agent_for_user(agent_id, user_id=user_id)
        match access_result:
            case Success(agent):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(access_result)

        runtime = await self._get_runtime(agent.id)
        if (
            runtime is None
            or runtime.provider_observed_state != RuntimeProviderObservedState.RUNNING
        ):
            return Failure(
                AgentWorkspaceRuntimeInactive(action=_start_action(agent.id))
            )
        if runtime.runner_state != RuntimeRunnerState.READY:
            return Failure(
                AgentWorkspaceFileReadError(detail="Runtime runner is not ready.")
            )
        return Success(runtime)

    async def _list_entries(
        self,
        runtime: AgentRuntime,
        path: PurePosixPath,
    ) -> Result[list[AgentWorkspaceEntry], AgentWorkspaceError]:
        """Create Agent Workspace directory entry list."""
        result = await self._runner_list_files(runtime, path)
        match result:
            case Success(entries):
                return Success(_list_entries_from_runner(entries))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def _read_file(
        self,
        runtime: AgentRuntime,
        path: PurePosixPath,
        limit: int,
    ) -> Result[AgentWorkspaceFileResult, AgentWorkspaceError]:
        """Create Agent Workspace file preview."""
        data_result = await self._runner_read_file(runtime, path, max_bytes=limit + 1)
        match data_result:
            case Success(data):
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(data_result)

        size = len(data)
        if size > limit:
            return Failure(AgentWorkspaceFileTooLarge(size=len(data), limit=limit))
        preview_bytes = data[:limit]
        text: str | None
        try:
            text = preview_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        return Success(
            AgentWorkspaceFile(
                type="FILE",
                path=path.as_posix(),
                media_type=_guess_media_type(path),
                size=size,
                text=text,
                truncated=False,
            )
        )

    async def _stat_path(
        self,
        runtime: AgentRuntime,
        path: PurePosixPath,
    ) -> Result[RuntimeFileStatResult, AgentWorkspaceError]:
        """Stat a path through the active Runtime Runner."""
        try:
            return Success(
                await self._runner_operations.stat_file(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    path=path.as_posix(),
                    deadline_at=_runner_file_operation_deadline(),
                )
            )
        except RuntimeRunnerOperationUnavailable as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationGenerationError as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationFailedError as error:
            return _runner_file_error(error)

    async def _runner_list_files(
        self,
        runtime: AgentRuntime,
        path: PurePosixPath,
    ) -> Result[tuple[RuntimeFileListEntry, ...], AgentWorkspaceError]:
        """List files through the active Runtime Runner."""
        try:
            result = await self._runner_operations.list_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                path=path.as_posix(),
                deadline_at=_runner_file_operation_deadline(),
            )
            return Success(result.entries)
        except RuntimeRunnerOperationUnavailable as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationGenerationError as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationFailedError as error:
            return _runner_file_error(error)

    async def _runner_read_file(
        self,
        runtime: AgentRuntime,
        path: PurePosixPath,
        *,
        max_bytes: int | None,
    ) -> Result[bytes, AgentWorkspaceError]:
        """Read a file through the active Runtime Runner."""
        try:
            result = await self._runner_operations.read_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                path=path.as_posix(),
                offset=0,
                max_bytes=max_bytes,
                deadline_at=_runner_file_operation_deadline(),
            )
            return Success(result.data)
        except RuntimeRunnerOperationUnavailable as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationGenerationError as error:
            return Failure(AgentWorkspaceFileReadError(detail=str(error)))
        except RuntimeRunnerOperationFailedError as error:
            return _runner_file_error(error)


def _runner_file_error(
    error: RuntimeRunnerOperationFailedError,
) -> Result[_T, AgentWorkspaceError]:
    """Map Runner operation failures into workspace file errors."""
    message = str(error)
    if _is_not_found_detail(message):
        return Failure(AgentWorkspaceFileNotFound())
    return Failure(AgentWorkspaceFileReadError(detail=message))


def _runner_file_operation_deadline() -> datetime:
    """Return Agent Workspace file operation round trip deadline."""
    return datetime.now(UTC) + timedelta(seconds=_RUNNER_FILE_OPERATION_TIMEOUT_SECONDS)


def _is_runner_unavailable_detail(detail: str) -> bool:
    """Return whether a Runner error means the route is temporarily unavailable."""
    return (
        "route unavailable" in detail
        or "generation is stale" in detail
        or "runner is not ready" in detail
    )


def _is_not_found_detail(detail: str) -> bool:
    """Return whether a Runner file error means the target path was not found."""
    lowered = detail.lower()
    return (
        "no such file" in lowered
        or "not found" in lowered
        or "does not exist" in lowered
    )


def _current_runtime_failure_detail(runtime: AgentRuntime) -> str | None:
    """Return the current desired-generation failure message, if any."""
    if runtime.failure_generation != runtime.desired_generation:
        return None
    if runtime.failure_generation is None:
        return None
    if runtime.failure_message is None:
        return None
    return runtime.failure_message


def _list_entries_from_runner(
    runner_entries: tuple[RuntimeFileListEntry, ...],
) -> list[AgentWorkspaceEntry]:
    """Build Agent Workspace entries from Runner file list output."""
    entries: list[AgentWorkspaceEntry] = []
    for item in runner_entries:
        if item.type not in {"file", "directory"}:
            continue
        child = PurePosixPath(item.path)
        entries.append(
            AgentWorkspaceEntry(
                name=child.name,
                path=child.as_posix(),
                kind="directory" if item.type == "directory" else "file",
                size=item.size_bytes if item.type == "file" else None,
                media_type=_guess_media_type(child) if item.type == "file" else None,
                modified_at=None,
            )
        )
    return sorted(entries, key=lambda entry: (entry.kind != "directory", entry.name))
