"""Domain enum definitions."""

import enum


class WorkspaceUserRole(enum.StrEnum):
    """WorkspaceUser role."""

    OWNER = "owner"
    MANAGER = "manager"
    MEMBER = "member"


class InvitationStatus(enum.StrEnum):
    """Workspace invitation status."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class SignupTokenDeliveryMethod(enum.StrEnum):
    """Signup token delivery method."""

    MANUAL = "manual"
    EMAIL = "email"


class AgentType(enum.StrEnum):
    """Agent visibility scope."""

    PUBLIC = "public"
    PRIVATE = "private"


class LLMProvider(enum.StrEnum):
    """LLM hosting provider."""

    OPENAI = "openai"
    CHATGPT_OAUTH = "chatgpt_oauth"
    ANTHROPIC = "anthropic"
    GOOGLE_GEMINI = "google_gemini"
    AWS_BEDROCK = "aws_bedrock"
    GOOGLE_VERTEX_AI = "google_vertex_ai"


class LLMModelDeveloper(enum.StrEnum):
    """LLM model developer."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    META = "meta"
    MISTRAL = "mistral"


class LLMModelLifecycleStatus(enum.StrEnum):
    """LLM provider model lifecycle status."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REMOVED_FROM_SOURCE = "removed_from_source"
    LOCAL_ONLY = "local_only"
    DISABLED = "disabled"


class LLMCatalogScope(enum.StrEnum):
    """LLM catalog ownership scope."""

    SYSTEM = "system"
    INTEGRATION = "integration"


class LLMCatalogLowererTarget(enum.StrEnum):
    """Runtime lowerer target used for catalog projection."""

    LITELLM = "litellm"


class LLMCatalogAttemptStatus(enum.StrEnum):
    """LLM catalog source/projection attempt status."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class LLMCatalogEntryVisibility(enum.StrEnum):
    """Projected catalog entry visibility."""

    SELECTABLE = "selectable"
    HIDDEN = "hidden"


class AgentProjectCatalogStatus(enum.StrEnum):
    """Agent Project catalog filesystem status projection."""

    UNCHECKED = "unchecked"
    AVAILABLE = "available"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class AgentProjectDefaultItemType(enum.StrEnum):
    """New-session default workspace item kind."""

    EXISTING_PROJECT = "existing_project"
    GIT_WORKTREE = "git_worktree"


class AgentSessionRunState(enum.StrEnum):
    """Engine execution status of AgentSession."""

    IDLE = "idle"
    RUNNING = "running"


class AgentSessionTitleSource(enum.StrEnum):
    """Source of the current AgentSession title."""

    MANUAL = "manual"
    AUTO_INITIAL = "auto_initial"
    AUTO_GENERATED = "auto_generated"


class SessionGitWorktreeStatus(enum.StrEnum):
    """Azents-owned Git worktree lifecycle status."""

    PENDING = "pending"
    CREATING = "creating"
    READY = "ready"
    FAILED = "failed"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANED = "cleaned"
    CLEANUP_FAILED = "cleanup_failed"


class SessionGitWorktreeBranchCreatedBy(enum.StrEnum):
    """Creator of a session Git worktree branch."""

    AZENTS = "azents"


class ActionExecutionStatus(enum.StrEnum):
    """Durable TurnAction execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    FAILED_FINAL = "failed_final"


class ActionExecutionEventKind(enum.StrEnum):
    """Durable TurnAction execution event kind."""

    INFO = "info"
    STEP_STARTED = "step_started"
    COMMAND_STARTED = "command_started"
    STDOUT = "stdout"
    STDERR = "stderr"
    COMMAND_COMPLETED = "command_completed"
    WARNING = "warning"
    FAILED = "failed"
    RETRY_REQUESTED = "retry_requested"
    FAILED_FINALIZED = "failed_finalized"
    COMPLETED = "completed"


class ScheduledTaskStatus(enum.StrEnum):
    """Current scheduler task status."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InputBufferKind(enum.StrEnum):
    """InputBuffer payload kind."""

    USER_MESSAGE = "user_message"
    EDITED_USER_MESSAGE = "edited_user_message"
    BACKGROUND_COMPLETION = "background_completion"
    GOAL_CONTINUATION = "goal_continuation"
    ACTION_MESSAGE = "action_message"


class EventKind(enum.StrEnum):
    """Event transcript event kind."""

    USER_MESSAGE = "user_message"
    BACKGROUND_COMPLETION = "background_completion"
    GOAL_CONTINUATION = "goal_continuation"
    GOAL_UPDATED = "goal_updated"
    ACTION_MESSAGE = "action_message"
    ACTION_EXECUTION_RESULT = "action_execution_result"
    SKILL_LOADED = "skill_loaded"
    GOAL_BRIEFING = "goal_briefing"
    ASSISTANT_MESSAGE = "assistant_message"
    REASONING = "reasoning"
    CLIENT_TOOL_CALL = "client_tool_call"
    CLIENT_TOOL_RESULT = "client_tool_result"
    PROVIDER_TOOL_CALL = "provider_tool_call"
    PROVIDER_TOOL_RESULT = "provider_tool_result"
    TURN_MARKER = "turn_marker"
    RUN_MARKER = "run_marker"
    INTERRUPTED = "interrupted"
    COMPACTION_MARKER = "compaction_marker"
    COMPACTION_SUMMARY = "compaction_summary"
    SYSTEM_REMINDER = "system_reminder"
    SYSTEM_ERROR = "system_error"
    UNKNOWN_ADAPTER_OUTPUT = "unknown_adapter_output"


class AgentRunPhase(enum.StrEnum):
    """Agent run phase."""

    IDLE = "idle"
    PREPARING_INPUT = "preparing_input"
    WAITING_FOR_MODEL = "waiting_for_model"
    STREAMING_MODEL = "streaming_model"
    NORMALIZING_OUTPUT = "normalizing_output"
    EXECUTING_TOOLS = "executing_tools"
    APPENDING_EVENTS = "appending_events"
    COMPACTING = "compacting"
    STOPPING = "stopping"


class AgentRunStatus(enum.StrEnum):
    """Agent run status."""

    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class AgentSessionStatus(enum.StrEnum):
    """AgentSession lifecycle status."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentSessionPrimaryKind(enum.StrEnum):
    """AgentSession primary role."""

    TEAM_PRIMARY = "team_primary"


class AgentSessionStartReason(enum.StrEnum):
    """AgentSession start reason."""

    INITIAL = "initial"
    SYSTEM_RECOVERY = "system_recovery"


class AgentSessionEndReason(enum.StrEnum):
    """AgentSession end reason."""

    IDLE = "idle"
    SAFETY = "safety"
    DELETED = "deleted"


class ExchangeFileOrigin(enum.StrEnum):
    """Exchange file creation source."""

    UPLOAD = "upload"
    ARTIFACT = "artifact"


class ExchangeFileStatus(enum.StrEnum):
    """Exchange file lifecycle status."""

    AVAILABLE = "available"
    EXPIRED = "expired"


class ArtifactStatus(enum.StrEnum):
    """Artifact lifecycle status."""

    AVAILABLE = "available"
    EXPIRED = "expired"


class ModelFileStatus(enum.StrEnum):
    """ModelFile lifecycle status."""

    AVAILABLE = "available"
    DELETED = "deleted"


class RuntimeDesiredState(enum.StrEnum):
    """Agent Runtime desired lifecycle status."""

    RUNNING = "running"
    STOPPED = "stopped"


class RuntimeLifecycleCommandType(enum.StrEnum):
    """Agent Runtime lifecycle command type."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RESET = "reset"
    OBSERVE = "observe"


class RuntimeProviderObservedState(enum.StrEnum):
    """Agent Runtime status reported by provider."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    RESETTING = "resetting"
    FAILED = "failed"


class RuntimeProviderConnectionState(enum.StrEnum):
    """Runtime Provider connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class RuntimeRunnerState(enum.StrEnum):
    """Runtime Runner status."""

    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


class RuntimeSummary(enum.StrEnum):
    """Server-computed Agent Runtime summary status."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESETTING = "resetting"
    RECOVERING = "recovering"
    PROVIDER_DISCONNECTED = "provider_disconnected"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    FAILED = "failed"


class RuntimeProviderScope(enum.StrEnum):
    """Runtime Provider settings scope."""

    SYSTEM = "system"
    WORKSPACE = "workspace"


class RuntimeProviderKind(enum.StrEnum):
    """Runtime Provider implementation kind."""

    KUBERNETES = "kubernetes"
    DOCKER = "docker"


class SnapshotKind(enum.StrEnum):
    """Snapshot creation reason.

    ``HIBERNATE`` is a snapshot left when tearing down a container after idle
    timeout. ``DEBOUNCE`` is a debounce snapshot taken periodically within a
    certain time after state-change events such as exec/write.
    """

    HIBERNATE = "hibernate"
    DEBOUNCE = "debounce"


class MessageRole(enum.StrEnum):
    """Message role for chat API response (ChatMessage).

    After events unification, the DB ENUM was removed, but this Python enum remains
    to preserve chat API response format. _TYPE_TO_ROLE in repos/message/__init__.py
    owns EventType to MessageRole mapping.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    TURN_COMPLETE = "turn_complete"
    RUN_COMPLETE = "run_complete"
    COMPACTION = "compaction"
    COMPACTION_STARTED = "compaction_started"


class EventType(enum.StrEnum):
    """Type classification for the events table.

    Values map 1:1 to Postgres ENUM 'event_type'.

    UI rendering unit is one type. Three groups: SDK origin, Azents formatted,
    and Azents meta.
    """

    # SDK origin (raw_data NOT NULL, Passthrough formatter)
    TEXT_ITEM = "text_item"
    REASONING_ITEM = "reasoning_item"
    TOOL_CALL_ITEM = "tool_call_item"
    TOOL_CALL_OUTPUT_ITEM = "tool_call_output_item"
    IMAGE_GENERATION_ITEM = "image_generation_item"
    UNKNOWN_ITEM = "unknown_item"

    # Azents formatted; raw_data NULL, formatter wraps user role
    USER_INPUT = "user_input"
    SYSTEM_REMINDER = "system_reminder"
    COMPACTION = "compaction"

    # Azents meta; raw_data NULL, model hidden
    TURN_COMPLETE = "turn_complete"
    RUN_COMPLETE = "run_complete"
    COMPACTION_STARTED = "compaction_started"
    ERROR = "error"


# Type groups for events: source of truth for CHECK constraints and formatter dispatch.
SDK_ORIGIN_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.TEXT_ITEM,
        EventType.REASONING_ITEM,
        EventType.TOOL_CALL_ITEM,
        EventType.TOOL_CALL_OUTPUT_ITEM,
        EventType.IMAGE_GENERATION_ITEM,
        EventType.UNKNOWN_ITEM,
    }
)

AZ_ORIGIN_EVENT_TYPES: frozenset[EventType] = (
    frozenset(EventType) - SDK_ORIGIN_EVENT_TYPES
)


class JoinRequestStatus(enum.StrEnum):
    """Workspace join request status."""

    PENDING = "pending"
    MUTED = "muted"


class ToolkitScopeType(enum.StrEnum):
    """Toolkit assignment scope type."""

    WORKSPACE = "workspace"


class MCPOAuthConnectionStatus(enum.StrEnum):
    """MCP OAuth connection lifecycle status."""

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"
