"""Chat v1 API data models."""

from __future__ import annotations

import datetime
from typing import Literal, Self, assert_never

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
)
from azents.engine.events.types import Event
from azents.engine.tools.goal import GoalStateSnapshot
from azents.engine.tools.todo import TodoItemSnapshot, TodoStateSnapshot
from azents.repos.agent_project_preset.data import AgentProjectPreset
from azents.repos.agent_session.data import AgentSession
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectRegistrationRequest,
)
from azents.services.chat.context import (
    SessionContext,
    SessionContextBreakdownSegment,
    SessionContextRawEvent,
    SessionContextSession,
    SessionContextStats,
    SessionContextSystemPrompt,
    SessionContextSystemPromptFragment,
)
from azents.services.chat.data import (
    ChatLiveRunRetryState,
    ChatLiveRunState,
    NewSessionProjectDefaults,
    NewSessionProjectDefaultsSource,
)
from azents.services.chat.workspace import (
    AgentWorkspaceAccessConnecting,
    AgentWorkspaceAccessState,
    AgentWorkspaceAccessUnavailable,
    AgentWorkspaceAction,
    AgentWorkspaceActions,
    AgentWorkspaceBulkDeleteResult,
    AgentWorkspaceBulkMoveResult,
    AgentWorkspaceControlUnavailable,
    AgentWorkspaceDirectory,
    AgentWorkspaceEntry,
    AgentWorkspaceFile,
    AgentWorkspaceManifest,
    AgentWorkspaceMoveResult,
    AgentWorkspaceMutationResult,
    AgentWorkspacePathStat,
    AgentWorkspaceReadFailed,
    AgentWorkspaceReady,
    AgentWorkspaceRuntime,
    AgentWorkspaceState,
)


class UploadResponse(BaseModel):
    """File upload response."""

    attachment_id: str = Field(description="Exchange attachment ID")
    uri: str = Field(description="Uploaded file URI")
    media_type: str = Field(description="File MIME type")
    size: int = Field(description="File size in bytes")
    name: str = Field(description="Display filename")


class ChatMessageWriteRequest(BaseModel):
    """REST message write request."""

    agent_id: str = Field(description="Agent ID")
    client_request_id: str = Field(
        min_length=1,
        max_length=64,
        description="Client-generated idempotency key",
    )
    message: str = Field(description="Message content")
    attachments: list[str] | None = Field(
        default=None,
        description="Attachment reference list, exchange:// URIs received after upload",
    )


class ChatSessionCreateMessageWriteRequest(BaseModel):
    """REST first message write request for a draft AgentSession."""

    client_request_id: str = Field(
        min_length=1,
        max_length=64,
        description="Client-generated idempotency key",
    )
    message: str = Field(description="Message content")
    project_paths: list[str] = Field(
        description="Exact Project paths to register on the created session",
    )
    attachments: list[str] | None = Field(
        default=None,
        description="Attachment reference list, exchange:// URIs received after upload",
    )


class AgentSessionCreateRequest(BaseModel):
    """REST non-primary AgentSession create request."""

    project_paths: list[str] = Field(
        description="Exact Project paths to register on the created session",
    )


class ChatEditMessageWriteRequest(BaseModel):
    """REST user message edit request."""

    agent_id: str = Field(description="Agent ID")
    client_request_id: str = Field(
        min_length=1,
        max_length=64,
        description="Client-generated idempotency key",
    )
    message_id: str = Field(description="Existing user_message event ID to edit")
    message: str = Field(description="Edited message content")
    attachments: list[str] | None = Field(
        default=None,
        description="Attachment reference list, exchange:// URIs received after upload",
    )


class ChatCommandWriteRequest(BaseModel):
    """REST slash command request."""

    agent_id: str = Field(description="Agent ID")
    client_request_id: str = Field(
        min_length=1,
        max_length=64,
        description="Client-generated idempotency key",
    )
    command: str = Field(description="Command name, for example compact")


class ChatWriteAcceptedResponse(BaseModel):
    """REST write accepted target."""

    type: Literal["input_buffer", "edit_message", "command"] = Field(
        description="Accepted target type"
    )
    id: str = Field(description="Accepted target ID")


class PartialHistoryResponse(BaseModel):
    """Partial history live projection response to compose into Chat timeline."""

    items: list[ChatEventResponse] = Field(
        description="Partial history event projection list"
    )


class TodoItemResponse(BaseModel):
    """Chat live todo item response."""

    content: str = Field(description="Todo text")
    status: Literal["pending", "in_progress", "completed"] = Field(
        description="Todo status"
    )

    @classmethod
    def from_domain(cls, item: TodoItemSnapshot) -> Self:
        """Convert from domain snapshot."""
        return cls(content=item.content, status=item.status)


class TodoStateResponse(BaseModel):
    """Chat live todo state response."""

    items: list[TodoItemResponse] = Field(description="Todo item list")

    @classmethod
    def from_domain(cls, state: TodoStateSnapshot) -> Self:
        """Convert from domain snapshot."""
        return cls(items=[TodoItemResponse.from_domain(item) for item in state.items])


class GoalStateResponse(BaseModel):
    """Chat live goal state response."""

    objective: str | None = Field(default=None, description="Goal objective")
    status: Literal["active", "paused", "blocked", "complete"] | None = Field(
        default=None, description="Goal status"
    )
    created_at: str | None = Field(default=None, description="Goal created timestamp")
    updated_at: str | None = Field(default=None, description="Goal updated timestamp")

    @classmethod
    def from_domain(cls, state: GoalStateSnapshot) -> Self:
        """Convert from domain snapshot."""
        return cls(
            objective=state.objective,
            status=state.status,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


class GoalUpdateRequest(BaseModel):
    """Session goal update request."""

    objective: str | None = Field(
        default=None,
        max_length=4000,
        description="Goal objective. Null clears the goal.",
    )


class GoalStatusUpdateRequest(BaseModel):
    """User-controlled Goal status update request."""

    status: Literal["active", "paused"] = Field(
        description=(
            "User-controlled goal status. Active resumes paused or blocked goals; "
            "paused pauses active goals."
        )
    )
    resume_hint: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Optional user-provided hint for resuming a paused or blocked goal."
        ),
    )


class ChatWriteSnapshotResponse(BaseModel):
    """Authoritative live snapshot after REST write."""

    partial_history_events: list[ChatEventResponse] = Field(
        description="Partial history projection list to compose into Chat timeline",
    )
    input_buffer_events: list[ChatEventResponse] = Field(
        description="Pending input buffer projection list",
    )
    run: ChatLiveRunStateResponse | None = Field(
        default=None,
        description="Currently running run status",
    )
    session_run_state: AgentSessionRunState = Field(
        description="Authoritative run_state for the current session",
    )
    todo: TodoStateResponse | None = Field(
        default=None,
        description="Current session todo snapshot",
    )
    goal: GoalStateResponse | None = Field(
        default=None,
        description="Current session goal snapshot",
    )


class ChatWriteResponse(BaseModel):
    """REST chat write response."""

    session_id: str = Field(description="AgentSession ID")
    client_request_id: str = Field(description="Client-generated idempotency key")
    accepted: ChatWriteAcceptedResponse = Field(description="Accepted write target")
    snapshot: ChatWriteSnapshotResponse = Field(
        description="Authoritative live snapshot after commit"
    )
    history_reload_required: bool = Field(
        description="Whether durable history reload is needed"
    )


class ChatStopResponse(BaseModel):
    """REST stop response."""

    session_id: str = Field(description="AgentSession ID")


class SlashCommandResponse(BaseModel):
    """Slash command response."""

    name: str = Field(description="Command name without leading slash")
    description: str = Field(description="Command description")


class SlashCommandListResponse(BaseModel):
    """Slash command list response."""

    items: list[SlashCommandResponse] = Field(
        description="Available slash command list"
    )


class SessionWorkspaceProjectResponse(BaseModel):
    """Agent Workspace Project response."""

    id: str = Field(description="Project ID")
    path: str = Field(description="Agent Workspace absolute path")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def from_domain(cls, project: SessionWorkspaceProject) -> Self:
        """Convert from service model."""
        return cls(
            id=project.id,
            path=project.path,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class SessionWorkspaceProjectListResponse(BaseModel):
    """Agent Workspace Project list response."""

    items: list[SessionWorkspaceProjectResponse] = Field(description="Project list")


class AgentProjectPresetResponse(BaseModel):
    """Agent Project preset response."""

    id: str = Field(description="Project preset ID")
    path: str = Field(description="Agent Workspace absolute path")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def from_domain(cls, preset: AgentProjectPreset) -> Self:
        """Convert from service model."""
        return cls(
            id=preset.id,
            path=preset.path,
            created_at=preset.created_at,
            updated_at=preset.updated_at,
        )


class AgentProjectPresetListResponse(BaseModel):
    """Agent Project preset list response."""

    items: list[AgentProjectPresetResponse] = Field(description="Project presets")


class AgentSessionProjectDefaultsSourceResponse(BaseModel):
    """New AgentSession Project defaults source metadata response."""

    type: Literal["empty", "last_created_session"] = Field(
        description="Default source type"
    )
    session_id: str | None = Field(default=None, description="Source session ID")

    @classmethod
    def from_domain(cls, source: NewSessionProjectDefaultsSource) -> Self:
        """Convert from service model."""
        return cls(type=source.type, session_id=source.session_id)


class AgentSessionProjectDefaultsResponse(BaseModel):
    """New AgentSession Project defaults response."""

    project_paths: list[str] = Field(description="Default selected Project paths")
    source: AgentSessionProjectDefaultsSourceResponse = Field(
        description="Default source metadata",
    )

    @classmethod
    def from_domain(cls, defaults: NewSessionProjectDefaults) -> Self:
        """Convert from service model."""
        return cls(
            project_paths=defaults.project_paths,
            source=AgentSessionProjectDefaultsSourceResponse.from_domain(
                defaults.source
            ),
        )


class SessionWorkspaceProjectRegisterRequest(BaseModel):
    """Existing Agent Workspace folder Project registration request."""

    path: str = Field(description="Existing directory path under /workspace/agent")


class SessionWorkspaceProjectRegistrationRequestResponse(BaseModel):
    """Agent Workspace Project registration request response."""

    id: str = Field(description="Request ID")
    path: str = Field(description="Requested Project path")
    reason: str = Field(description="Request reason provided by the Agent")
    status: str = Field(description="Request status")
    project_id: str | None = Field(default=None, description="Approved Project ID")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def from_domain(cls, request: SessionWorkspaceProjectRegistrationRequest) -> Self:
        """Convert from service model."""
        return cls(
            id=request.id,
            path=request.path,
            reason=request.reason,
            status=request.status.value,
            project_id=request.project_id,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )


class SessionWorkspaceProjectRegistrationRequestListResponse(BaseModel):
    """Agent Workspace Project registration request list response."""

    items: list[SessionWorkspaceProjectRegistrationRequestResponse] = Field(
        description="Project registration request list"
    )


class AgentWorkspaceActionResponse(BaseModel):
    """Agent Workspace state transition action response."""

    type: Literal[
        "START_RUNTIME", "STOP_RUNTIME", "RESTART_RUNTIME", "RESET_RUNTIME"
    ] = Field(description="Action type")
    method: Literal["POST"] = Field(description="HTTP method")
    path: str = Field(description="API path to call")


def _workspace_action_response_from_domain(
    action: AgentWorkspaceAction,
) -> AgentWorkspaceActionResponse:
    """Convert a service model action to an API response."""
    return AgentWorkspaceActionResponse(
        type=action.type,
        method=action.method,
        path=action.path,
    )


class AgentWorkspaceEntryResponse(BaseModel):
    """Agent Workspace directory entry response."""

    name: str = Field(description="File or directory name")
    path: str = Field(description="Agent Workspace absolute path")
    kind: Literal["file", "directory"] = Field(description="Entry kind")
    size: int | None = Field(default=None, description="File size")
    media_type: str | None = Field(default=None, description="MIME type")
    modified_at: datetime.datetime | None = Field(
        default=None,
        description="Updated time",
    )

    @classmethod
    def from_domain(cls, entry: AgentWorkspaceEntry) -> Self:
        """Convert from service model."""
        return cls(
            name=entry.name,
            path=entry.path,
            kind=entry.kind,
            size=entry.size,
            media_type=entry.media_type,
            modified_at=entry.modified_at,
        )


class AgentWorkspaceManifestResponse(BaseModel):
    """Agent Workspace manifest response."""

    root: str = Field(description="Agent Workspace root")
    cwd: str = Field(description="Initial working directory")
    entries: list[AgentWorkspaceEntryResponse] = Field(description="Root entry list")
    git: dict[str, object] | None = Field(
        default=None,
        description="Git status. Null until Phase 4",
    )

    @classmethod
    def from_domain(cls, manifest: AgentWorkspaceManifest) -> Self:
        """Convert from service model."""
        return cls(
            root=manifest.root,
            cwd=manifest.cwd,
            entries=[
                AgentWorkspaceEntryResponse.from_domain(e) for e in manifest.entries
            ],
            git=manifest.git,
        )


class AgentWorkspaceRuntimeResponse(BaseModel):
    """Server-computed Agent Runtime status response."""

    type: Literal[
        "NOT_STARTED",
        "STARTING",
        "RUNNING",
        "HIBERNATED",
        "STOPPING",
        "RESETTING",
        "RESTORE_FAILED",
        "LOST",
    ] = Field(description="Provider runtime status")
    runtime_id: str | None = Field(description="AgentRuntime ID")
    workspace_path: str | None = Field(
        default=None,
        description="Agent Workspace path reported by the provider",
    )
    detail: str | None = Field(default=None, description="Status description")

    @classmethod
    def from_domain(cls, state: AgentWorkspaceRuntime) -> Self:
        """Convert from service model."""
        return cls(
            type=state.type,
            runtime_id=state.runtime_id,
            workspace_path=state.workspace_path,
            detail=state.detail,
        )


class AgentWorkspaceUnavailableAccessResponse(BaseModel):
    """Workspace unavailable response."""

    type: Literal["UNAVAILABLE"] = Field(description="Response type")
    reason: Literal[
        "RUNTIME_NOT_RUNNING",
        "WORKSPACE_PATH_UNAVAILABLE",
    ] = Field(description="Unavailable reason")

    @classmethod
    def from_domain(cls, state: AgentWorkspaceAccessUnavailable) -> Self:
        """Convert from service model."""
        return cls(type=state.type, reason=state.reason)


class AgentWorkspaceConnectingAccessResponse(BaseModel):
    """Workspace connecting response."""

    type: Literal["CONNECTING"] = Field(description="Response type")

    @classmethod
    def from_domain(cls, state: AgentWorkspaceAccessConnecting) -> Self:
        """Convert from service model."""
        return cls(type=state.type)


class AgentWorkspaceControlUnavailableAccessResponse(BaseModel):
    """Runner route/stream unavailable response."""

    type: Literal["CONTROL_UNAVAILABLE"] = Field(description="Response type")
    detail: str = Field(description="Status description")
    retry_after_ms: int = Field(description="Recommended retry delay")

    @classmethod
    def from_domain(cls, state: AgentWorkspaceControlUnavailable) -> Self:
        """Convert from service model."""
        return cls(
            type=state.type,
            detail=state.detail,
            retry_after_ms=state.retry_after_ms,
        )


class AgentWorkspaceReadFailedAccessResponse(BaseModel):
    """Workspace read/list failure response."""

    type: Literal["READ_FAILED"] = Field(description="Response type")
    detail: str = Field(description="Status description")

    @classmethod
    def from_domain(cls, state: AgentWorkspaceReadFailed) -> Self:
        """Convert from service model."""
        return cls(type=state.type, detail=state.detail)


class AgentWorkspaceReadyAccessResponse(BaseModel):
    """Agent Workspace ready access response."""

    type: Literal["READY"] = Field(description="Response type")
    manifest: AgentWorkspaceManifestResponse = Field(
        description="Agent Workspace manifest",
    )

    @classmethod
    def from_domain(cls, state: AgentWorkspaceReady) -> Self:
        """Convert from service model."""
        return cls(
            type=state.type,
            manifest=AgentWorkspaceManifestResponse.from_domain(state.manifest),
        )


AgentWorkspaceAccessResponse = (
    AgentWorkspaceUnavailableAccessResponse
    | AgentWorkspaceConnectingAccessResponse
    | AgentWorkspaceControlUnavailableAccessResponse
    | AgentWorkspaceReadFailedAccessResponse
    | AgentWorkspaceReadyAccessResponse
)


class AgentWorkspaceActionsResponse(BaseModel):
    """Agent Runtime lifecycle action set response."""

    start: AgentWorkspaceActionResponse | None = Field(default=None)
    stop: AgentWorkspaceActionResponse | None = Field(default=None)
    restart: AgentWorkspaceActionResponse | None = Field(default=None)
    reset: AgentWorkspaceActionResponse | None = Field(default=None)

    @classmethod
    def from_domain(cls, actions: AgentWorkspaceActions) -> Self:
        """Convert from service model."""
        return cls(
            start=(
                _workspace_action_response_from_domain(actions.start)
                if actions.start is not None
                else None
            ),
            stop=(
                _workspace_action_response_from_domain(actions.stop)
                if actions.stop is not None
                else None
            ),
            restart=(
                _workspace_action_response_from_domain(actions.restart)
                if actions.restart is not None
                else None
            ),
            reset=(
                _workspace_action_response_from_domain(actions.reset)
                if actions.reset is not None
                else None
            ),
        )


class AgentWorkspaceResponse(BaseModel):
    """Agent Workspace panel bootstrap response."""

    runtime: AgentWorkspaceRuntimeResponse = Field(
        description="Provider runtime status"
    )
    workspace: AgentWorkspaceAccessResponse = Field(
        description="Workspace access status"
    )
    actions: AgentWorkspaceActionsResponse = Field(
        description="Runtime lifecycle actions"
    )

    @classmethod
    def from_domain(cls, state: AgentWorkspaceState) -> Self:
        """Convert from service model."""
        return cls(
            runtime=AgentWorkspaceRuntimeResponse.from_domain(state.runtime),
            workspace=_workspace_access_response_from_domain(state.workspace),
            actions=AgentWorkspaceActionsResponse.from_domain(state.actions),
        )


def _workspace_access_response_from_domain(
    state: AgentWorkspaceAccessState,
) -> AgentWorkspaceAccessResponse:
    """Convert Workspace access service model to API response."""
    match state:
        case AgentWorkspaceAccessUnavailable():
            return AgentWorkspaceUnavailableAccessResponse.from_domain(state)
        case AgentWorkspaceAccessConnecting():
            return AgentWorkspaceConnectingAccessResponse.from_domain(state)
        case AgentWorkspaceControlUnavailable():
            return AgentWorkspaceControlUnavailableAccessResponse.from_domain(state)
        case AgentWorkspaceReadFailed():
            return AgentWorkspaceReadFailedAccessResponse.from_domain(state)
        case AgentWorkspaceReady():
            return AgentWorkspaceReadyAccessResponse.from_domain(state)
        case _:
            assert_never(state)


class AgentWorkspaceDirectoryResponse(BaseModel):
    """Agent Workspace directory response."""

    type: Literal["DIRECTORY"] = Field(description="Response type")
    path: str = Field(description="Directory path")
    entries: list[AgentWorkspaceEntryResponse] = Field(description="Entry list")

    @classmethod
    def from_domain(cls, directory: AgentWorkspaceDirectory) -> Self:
        """Convert from service model."""
        return cls(
            type=directory.type,
            path=directory.path,
            entries=[
                AgentWorkspaceEntryResponse.from_domain(e) for e in directory.entries
            ],
        )


class AgentWorkspaceFileResponse(BaseModel):
    """Agent Workspace file preview response."""

    type: Literal["FILE"] = Field(description="Response type")
    path: str = Field(description="File path")
    media_type: str = Field(description="MIME type")
    size: int = Field(description="File size")
    text: str | None = Field(default=None, description="UTF-8 text preview")
    truncated: bool = Field(description="Whether preview was truncated")

    @classmethod
    def from_domain(cls, file: AgentWorkspaceFile) -> Self:
        """Convert from service model."""
        return cls(
            type=file.type,
            path=file.path,
            media_type=file.media_type,
            size=file.size,
            text=file.text,
            truncated=file.truncated,
        )


AgentWorkspaceFileResponseUnion = (
    AgentWorkspaceDirectoryResponse | AgentWorkspaceFileResponse
)


class AgentWorkspaceStatResponse(BaseModel):
    """Agent Workspace path metadata response."""

    path: str = Field(description="Agent Workspace path")
    name: str = Field(description="Path basename")
    kind: Literal["file", "directory", "symlink", "other", "missing"] = Field(
        description="Path kind"
    )
    size: int | None = Field(default=None, description="File size in bytes")
    media_type: str | None = Field(default=None, description="MIME type")
    modified_at: datetime.datetime | None = Field(
        default=None,
        description="Modified time",
    )
    symlink: bool = Field(description="Whether the path itself is a symlink")
    real_path: str | None = Field(default=None, description="Symlink target path")
    resolved_kind: (
        Literal["file", "directory", "symlink", "other", "missing"] | None
    ) = Field(default=None, description="Symlink target kind")

    @classmethod
    def from_domain(cls, stat: AgentWorkspacePathStat) -> Self:
        """Convert from service model."""
        return cls(
            path=stat.path,
            name=stat.name,
            kind=stat.kind,
            size=stat.size,
            media_type=stat.media_type,
            modified_at=stat.modified_at,
            symlink=stat.symlink,
            real_path=stat.real_path,
            resolved_kind=stat.resolved_kind,
        )


class AgentWorkspaceMkdirRequest(BaseModel):
    """Agent Workspace mkdir request."""

    path: str = Field(description="Directory path to create")
    parents: bool = Field(default=False, description="Create parent directories")


class AgentWorkspaceDeleteRequest(BaseModel):
    """Agent Workspace delete request."""

    path: str = Field(description="File or directory path to delete")
    recursive: bool = Field(default=False, description="Delete directories recursively")


class AgentWorkspaceBulkDeleteRequest(BaseModel):
    """Agent Workspace bulk delete request."""

    paths: list[str] = Field(description="File or directory paths to delete")
    recursive: bool = Field(default=False, description="Delete directories recursively")


class AgentWorkspaceMoveRequest(BaseModel):
    """Agent Workspace move request."""

    source_path: str = Field(description="Source path")
    destination_path: str = Field(description="Destination path")
    overwrite: bool = Field(default=False, description="Overwrite existing destination")


class AgentWorkspaceBulkMoveRequest(BaseModel):
    """Agent Workspace bulk move request."""

    source_paths: list[str] = Field(description="Source paths")
    destination_directory: str = Field(description="Destination directory")
    overwrite: bool = Field(
        default=False, description="Overwrite existing destinations"
    )


class AgentWorkspaceMutationResponse(BaseModel):
    """Agent Workspace mutation response."""

    path: str = Field(description="Affected path")

    @classmethod
    def from_domain(cls, result: AgentWorkspaceMutationResult) -> Self:
        """Convert from service model."""
        return cls(path=result.path)


class AgentWorkspaceMoveResponse(BaseModel):
    """Agent Workspace move response."""

    source_path: str = Field(description="Moved source path")
    destination_path: str = Field(description="Move destination path")

    @classmethod
    def from_domain(cls, result: AgentWorkspaceMoveResult) -> Self:
        """Convert from service model."""
        return cls(
            source_path=result.source_path,
            destination_path=result.destination_path,
        )


class AgentWorkspaceBulkDeleteResponse(BaseModel):
    """Agent Workspace bulk delete response."""

    paths: list[str] = Field(description="Deleted paths")

    @classmethod
    def from_domain(cls, result: AgentWorkspaceBulkDeleteResult) -> Self:
        """Convert from service model."""
        return cls(paths=result.paths)


class AgentWorkspaceBulkMoveResponse(BaseModel):
    """Agent Workspace bulk move response."""

    entries: list[AgentWorkspaceMoveResponse] = Field(description="Moved entries")

    @classmethod
    def from_domain(cls, result: AgentWorkspaceBulkMoveResult) -> Self:
        """Convert from service model."""
        return cls(
            entries=[AgentWorkspaceMoveResponse.from_domain(e) for e in result.entries]
        )


class AgentWorkspaceInactiveErrorResponse(BaseModel):
    """Runtime inactive error response."""

    code: Literal["RUNTIME_INACTIVE"] = Field(description="Error code")
    message: str = Field(description="Error message")
    action: AgentWorkspaceActionResponse = Field(description="Recommended action")


class SessionContextSessionResponse(BaseModel):
    """Session context session response."""

    id: str = Field(description="AgentSession ID")
    agent_id: str = Field(description="Agent ID")
    created_at: datetime.datetime | None = Field(default=None)
    updated_at: datetime.datetime | None = Field(default=None)

    @classmethod
    def from_domain(cls, session: SessionContextSession) -> Self:
        """Convert from domain model."""
        return cls(
            id=session.id,
            agent_id=session.agent_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class SessionContextStatsResponse(BaseModel):
    """Session context statistics response."""

    total_events: int = Field(description="Raw event count")
    user_messages: int = Field(description="User message count")
    assistant_messages: int = Field(description="Assistant message count")
    reasoning_events: int = Field(description="Reasoning event count")
    tool_calls: int = Field(description="Tool call count")
    tool_results: int = Field(description="Tool result count")
    turn_markers: int = Field(description="Turn marker count")
    total_cost_usd: float | None = Field(default=None, description="Total cost")

    @classmethod
    def from_domain(cls, stats: SessionContextStats) -> Self:
        """Convert from domain model."""
        return cls(
            total_events=stats.total_events,
            user_messages=stats.user_messages,
            assistant_messages=stats.assistant_messages,
            reasoning_events=stats.reasoning_events,
            tool_calls=stats.tool_calls,
            tool_results=stats.tool_results,
            turn_markers=stats.turn_markers,
            total_cost_usd=stats.total_cost_usd,
        )


class SessionContextBreakdownSegmentResponse(BaseModel):
    """Session context breakdown segment response."""

    key: Literal["system", "user", "assistant", "tool", "other"] = Field(
        description="Breakdown key"
    )
    tokens: int = Field(description="Prompt character count")
    percent: float = Field(description="Known prompt character percentage")

    @classmethod
    def from_domain(
        cls,
        segment: SessionContextBreakdownSegment,
    ) -> Self:
        """Convert from domain model."""
        return cls(
            key=segment.key,
            tokens=segment.tokens,
            percent=segment.percent,
        )


class SessionContextSystemPromptFragmentResponse(BaseModel):
    """Session context system prompt fragment response."""

    id: str = Field(description="Prompt fragment ID")
    source: Literal["agent", "toolkit", "turn_injected", "final"] = Field(
        description="Prompt fragment source"
    )
    label: str = Field(description="Display label")
    content: str = Field(description="Full prompt content")
    preview: str = Field(description="Prompt preview")
    length: int = Field(description="Prompt content length")
    metadata: dict[str, str] = Field(description="Source metadata")

    @classmethod
    def from_domain(cls, fragment: SessionContextSystemPromptFragment) -> Self:
        """Convert from domain model."""
        return cls(
            id=fragment.id,
            source=fragment.source,
            label=fragment.label,
            content=fragment.content,
            preview=fragment.preview,
            length=fragment.length,
            metadata=dict(fragment.metadata),
        )


class SessionContextSystemPromptResponse(BaseModel):
    """Session context system prompt analysis response."""

    agent_prompt: SessionContextSystemPromptFragmentResponse | None = Field(
        default=None,
        description="Agent prompt fragment",
    )
    toolkit_prompts: list[SessionContextSystemPromptFragmentResponse] = Field(
        description="Toolkit prompt fragments"
    )
    injected_prompts: list[SessionContextSystemPromptFragmentResponse] = Field(
        description="Turn injected prompt fragments"
    )
    final_prompt: SessionContextSystemPromptFragmentResponse | None = Field(
        default=None,
        description="Final composed system prompt",
    )

    @classmethod
    def from_domain(cls, prompt: SessionContextSystemPrompt) -> Self:
        """Convert from domain model."""
        return cls(
            agent_prompt=(
                SessionContextSystemPromptFragmentResponse.from_domain(
                    prompt.agent_prompt
                )
                if prompt.agent_prompt is not None
                else None
            ),
            toolkit_prompts=[
                SessionContextSystemPromptFragmentResponse.from_domain(fragment)
                for fragment in prompt.toolkit_prompts
            ],
            injected_prompts=[
                SessionContextSystemPromptFragmentResponse.from_domain(fragment)
                for fragment in prompt.injected_prompts
            ],
            final_prompt=(
                SessionContextSystemPromptFragmentResponse.from_domain(
                    prompt.final_prompt
                )
                if prompt.final_prompt is not None
                else None
            ),
        )


class SessionContextRawEventResponse(BaseModel):
    """Session context raw event response."""

    id: str = Field(description="Event ID")
    kind: str = Field(description="Event kind")
    payload: dict[str, object] = Field(description="Event payload")
    external_id: str | None = Field(default=None)
    adapter: str | None = Field(default=None)
    provider: str | None = Field(default=None)
    model: str | None = Field(default=None)
    native_format: str | None = Field(default=None)
    schema_version: str = Field(description="Schema version")
    created_at: datetime.datetime = Field(description="Created time")

    @classmethod
    def from_domain(cls, event: SessionContextRawEvent) -> Self:
        """Convert from domain model."""
        return cls(
            id=event.id,
            kind=event.kind.value,
            payload=dict(event.payload),
            external_id=event.external_id,
            adapter=event.adapter,
            provider=event.provider,
            model=event.model,
            native_format=event.native_format,
            schema_version=event.schema_version,
            created_at=event.created_at,
        )


class SessionContextResponse(BaseModel):
    """Agent session context inspector response."""

    session: SessionContextSessionResponse = Field(description="Session summary")
    usage: dict[str, object] | None = Field(default=None, description="Latest usage")
    stats: SessionContextStatsResponse = Field(description="Aggregate stats")
    breakdown: list[SessionContextBreakdownSegmentResponse] = Field(
        description="Prompt character breakdown"
    )
    system_prompt: SessionContextSystemPromptResponse | None = Field(
        default=None,
        description="System prompt analysis",
    )
    raw_events: list[SessionContextRawEventResponse] = Field(description="Raw events")

    @classmethod
    def from_domain(cls, context: SessionContext) -> Self:
        """Convert from domain model."""
        return cls(
            session=SessionContextSessionResponse.from_domain(context.session),
            usage=(
                context.usage.model_dump(mode="json", exclude_none=True)
                if context.usage is not None
                else None
            ),
            stats=SessionContextStatsResponse.from_domain(context.stats),
            breakdown=[
                SessionContextBreakdownSegmentResponse.from_domain(segment)
                for segment in context.breakdown
            ],
            system_prompt=(
                SessionContextSystemPromptResponse.from_domain(context.system_prompt)
                if context.system_prompt is not None
                else None
            ),
            raw_events=[
                SessionContextRawEventResponse.from_domain(event)
                for event in context.raw_events
            ],
        )


class ChatEventResponse(BaseModel):
    """Event chat event response."""

    id: str = Field(description="Event ID")
    session_id: str = Field(description="AgentSession ID")
    kind: EventKind = Field(description="Event kind")
    payload: dict[str, object] = Field(description="Event payload")
    model_order: int = Field(description="Model input logical order")
    external_id: str | None = Field(default=None, description="Dedup key")
    adapter: str | None = Field(default=None, description="Adapter name")
    provider: str | None = Field(default=None, description="Provider name")
    model: str | None = Field(default=None, description="Model name")
    native_format: str | None = Field(default=None, description="Native format")
    schema_version: str = Field(description="Event schema version")
    created_at: datetime.datetime = Field(description="Created at")

    @classmethod
    def from_domain(cls, event: Event) -> Self:
        """Convert from Event domain model."""
        return cls(
            id=event.id,
            session_id=event.session_id,
            kind=event.kind,
            payload=event.payload.model_dump(mode="json", exclude_none=True),
            model_order=event.model_order,
            external_id=event.external_id,
            adapter=event.adapter,
            provider=event.provider,
            model=event.model,
            native_format=event.native_format,
            schema_version=event.schema_version,
            created_at=event.created_at,
        )


class ChatEventPageResponse(BaseModel):
    """Event chat event page response."""

    items: list[ChatEventResponse] = Field(description="Event list")
    has_more: bool = Field(description="Whether older events exist")
    has_newer: bool = Field(
        default=False,
        description="Whether newer events exist",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Next backward page cursor, oldest event ID",
    )
    previous_cursor: str | None = Field(
        default=None,
        description="Next forward page cursor, newest event ID",
    )


class ChatLiveRunRetryStateResponse(BaseModel):
    """Current live failed-run retry state response."""

    status: str = Field(description="Current retry status")
    last_error_message: str = Field(description="Latest user-safe error message")
    failed_attempt_count: int = Field(description="Failed attempt count")
    max_retries: int = Field(description="Maximum retry count")
    backoff_seconds: int = Field(description="Current backoff duration in seconds")
    next_retry_at: str = Field(description="Absolute next retry timestamp")

    @classmethod
    def from_domain(cls, retry: ChatLiveRunRetryState) -> Self:
        """Convert from live run retry state domain model."""
        return cls(
            status=retry.status,
            last_error_message=retry.last_error_message,
            failed_attempt_count=retry.failed_attempt_count,
            max_retries=retry.max_retries,
            backoff_seconds=retry.backoff_seconds,
            next_retry_at=retry.next_retry_at,
        )


class ChatLiveRunStateResponse(BaseModel):
    """Current live run state response."""

    run_id: str = Field(description="AgentRun ID")
    phase: AgentRunPhase = Field(description="Current run phase")
    status: AgentRunStatus = Field(description="Current run status")
    retry: ChatLiveRunRetryStateResponse | None = Field(
        default=None,
        description="Current failed-run retry state",
        exclude_if=lambda value: value is None,
    )

    @classmethod
    def from_domain(cls, run: ChatLiveRunState) -> Self:
        """Convert from live run state domain model."""
        return cls(
            run_id=run.run_id,
            phase=run.phase,
            status=run.status,
            retry=None
            if run.retry is None
            else ChatLiveRunRetryStateResponse.from_domain(run.retry),
        )


class LiveEventListResponse(BaseModel):
    """Current live state taxonomy snapshot response."""

    partial_history: PartialHistoryResponse = Field(
        description="Partial history projection list to compose into Chat timeline",
    )
    input_buffers: list[ChatEventResponse] = Field(
        description="Pending input buffer projection list",
    )
    run: ChatLiveRunStateResponse | None = Field(
        default=None,
        description="Currently running run status",
    )
    session_run_state: AgentSessionRunState = Field(
        description="Authoritative run_state for the current session",
    )
    todo: TodoStateResponse | None = Field(
        default=None,
        description="Current session todo snapshot",
    )
    goal: GoalStateResponse | None = Field(
        default=None,
        description="Current session goal snapshot",
    )


class AgentSessionTitleUpdateRequest(BaseModel):
    """AgentSession title update request."""

    title: str | None = Field(
        description=(
            "User-facing session title. Null clears the custom title. "
            "Non-null values are trimmed and must be 200 characters or fewer."
        ),
    )


class AgentSessionResponse(BaseModel):
    """Conversation session response."""

    id: str = Field(description="Session ID")
    agent_id: str = Field(description="Agent ID")
    title: str | None = Field(description="User-facing session title")
    title_source: AgentSessionTitleSource | None = Field(
        description="Source of the current session title",
    )
    status: AgentSessionStatus = Field(description="Session status")
    primary_kind: AgentSessionPrimaryKind | None = Field(
        default=None,
        description="Primary session role",
    )
    run_state: AgentSessionRunState = Field(
        description="Session execution state",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def from_domain(cls, session: AgentSession) -> Self:
        """Convert from domain model."""
        return cls(
            id=session.id,
            agent_id=session.agent_id,
            title=session.title,
            title_source=session.title_source,
            status=session.status,
            primary_kind=session.primary_kind,
            run_state=session.run_state,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class AgentSessionListResponse(BaseModel):
    """Conversation session list response."""

    items: list[AgentSessionResponse] = Field(description="Session list")


class WsTicketResponse(BaseModel):
    """Short-lived ticket response for WebSocket connection."""

    ticket: str = Field(
        description="Short-lived HMAC-signed ticket, valid for 30 seconds"
    )
