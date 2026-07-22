"""Domain enum definitions."""

import enum


class WorkspaceUserRole(enum.StrEnum):
    """WorkspaceUser role."""

    OWNER = "owner"
    MANAGER = "manager"
    MEMBER = "member"


class SystemUserRole(enum.StrEnum):
    """Instance-wide User role."""

    SYSTEM_ADMIN = "system_admin"


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
    ANTHROPIC = "anthropic"
    GOOGLE_GEMINI = "google_gemini"
    AWS_BEDROCK = "aws_bedrock"
    GOOGLE_VERTEX_AI = "google_vertex_ai"
    CHATGPT_OAUTH = "chatgpt_oauth"
    XAI_OAUTH = "xai_oauth"
    XAI = "xai"
    OPENROUTER = "openrouter"
    KIMI_OAUTH = "kimi_oauth"


class LLMModelDeveloper(enum.StrEnum):
    """LLM model developer."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    XAI = "xai"
    MOONSHOT = "moonshot"
    META = "meta"
    MISTRAL = "mistral"
    OTHER = "other"


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


class AgentLifecycleStatus(enum.StrEnum):
    """Durable Agent lifecycle admission state."""

    ACTIVE = "active"
    DECOMMISSIONING = "decommissioning"


class AgentDecommissionStatus(enum.StrEnum):
    """Durable Agent decommission job state."""

    PENDING = "pending"
    RETIRING_SESSIONS = "retiring_sessions"
    WAITING_RETENTION = "waiting_retention"
    FINALIZING = "finalizing"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"


class AgentSessionRunState(enum.StrEnum):
    """Engine execution status of AgentSession."""

    IDLE = "idle"
    RUNNING = "running"


class AgentSessionKind(enum.StrEnum):
    """AgentSession listing category."""

    ROOT = "root"
    SUBAGENT = "subagent"


class SessionAgentKind(enum.StrEnum):
    """SessionAgent tree node kind."""

    ROOT = "root"
    SUBAGENT = "subagent"


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
    """Live TurnAction execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionExecutionEventKind(enum.StrEnum):
    """Live TurnAction execution event kind."""

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


class ArchivedSessionRetentionApplicationStatus(enum.StrEnum):
    """Durable existing-archive retention application status."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"


class ArchivedSessionPurgeStatus(enum.StrEnum):
    """Durable archived-session purge status."""

    PENDING = "pending"
    FENCING = "fencing"
    CLEANING = "cleaning"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ArchivedSessionPurgeParticipantPhase(enum.StrEnum):
    """Last durable checkpoint completed by one purge participant."""

    PENDING = "pending"
    PREPARED = "prepared"
    CLEANUP_COMPLETED = "cleanup_completed"
    VERIFIED = "verified"


class InputBufferKind(enum.StrEnum):
    """InputBuffer payload kind."""

    USER_MESSAGE = "user_message"
    GOAL_CONTINUATION = "goal_continuation"
    ACTION_MESSAGE = "action_message"
    AGENT_MESSAGE = "agent_message"
    EXTERNAL_CHANNEL_INVOCATION = "external_channel_invocation"


class InputBufferSchedulingMode(enum.StrEnum):
    """Whether pending input can start or resume an idle session."""

    QUEUE_ONLY = "queue_only"
    WAKE_SESSION = "wake_session"


class EventKind(enum.StrEnum):
    """Event transcript event kind."""

    USER_MESSAGE = "user_message"
    GOAL_CONTINUATION = "goal_continuation"
    GOAL_UPDATED = "goal_updated"
    ACTION_MESSAGE = "action_message"
    AGENT_MESSAGE = "agent_message"
    EXTERNAL_CHANNEL_MESSAGE = "external_channel_message"
    ACTION_EXECUTION_RESULT = "action_execution_result"
    SKILL_LOADED = "skill_loaded"
    GOAL_BRIEFING = "goal_briefing"
    ASSISTANT_MESSAGE = "assistant_message"
    REASONING = "reasoning"
    CLIENT_TOOL_CALL = "client_tool_call"
    CLIENT_TOOL_RESULT = "client_tool_result"
    PROVIDER_TOOL_CALL = "provider_tool_call"
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

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class AgentRunParentResultDeliveryState(enum.StrEnum):
    """Finalized parent mailbox delivery state for a subagent Run."""

    SUPPRESSED = "suppressed"
    ENQUEUED = "enqueued"


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
    EXTERNAL_CHANNEL = "external_channel"
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


class RuntimeProviderRegistrationMethod(enum.StrEnum):
    """Origin that first established a Runtime Provider."""

    ADMIN = "admin"
    BOOTSTRAP = "bootstrap"


class RuntimeProviderLifecycleState(enum.StrEnum):
    """Permanent administrative lifecycle for a Runtime Provider."""

    ACTIVE = "active"
    DECOMMISSIONING = "decommissioning"
    DECOMMISSIONED = "decommissioned"
    FORCE_RETIRED = "force_retired"


class RuntimeProviderAvailabilityMode(enum.StrEnum):
    """Workspace availability policy for a Runtime Provider."""

    PLATFORM_WIDE = "platform_wide"
    SELECTED_WORKSPACES = "selected_workspaces"


class RuntimeProviderBootstrapAdapterKind(enum.StrEnum):
    """Trusted adapter that supplies authoritative Provider declarations."""

    HELM_FILE = "helm_file"


class RuntimeProviderBootstrapDeclarationState(enum.StrEnum):
    """Current reconciliation state of one bootstrap declaration."""

    PRESENT = "present"
    ABSENT = "absent"
    CONFLICT = "conflict"


class RuntimeProviderAuditEventType(enum.StrEnum):
    """Metadata-only Provider aggregate audit event."""

    REGISTERED = "registered"
    BOOTSTRAP_RECONCILED = "bootstrap_reconciled"
    BOOTSTRAP_WITHDRAWN = "bootstrap_withdrawn"
    BOOTSTRAP_CONFLICT = "bootstrap_conflict"
    ENABLED = "enabled"
    DISABLED = "disabled"
    AVAILABILITY_CHANGED = "availability_changed"


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


class ExternalChannelProvider(enum.StrEnum):
    """External collaboration provider."""

    SLACK = "slack"


class ExternalChannelTransport(enum.StrEnum):
    """Inbound transport selected for one external connection."""

    HTTP = "http"
    SOCKET = "socket"


class ExternalChannelConnectionStatus(enum.StrEnum):
    """External connection lifecycle status."""

    CONFIGURING = "configuring"
    ACTIVE = "active"
    DEGRADED = "degraded"
    RECONNECT_REQUIRED = "reconnect_required"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"


class ExternalChannelRouteStatus(enum.StrEnum):
    """External connection to Agent route lifecycle status."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class ExternalChannelRouteMode(enum.StrEnum):
    """External connection routing behavior."""

    DEDICATED = "dedicated"
    PLATFORM = "platform"


class ExternalChannelResourceType(enum.StrEnum):
    """Provider resource type represented by an external conversation."""

    THREAD = "thread"


class ExternalChannelResourceStatus(enum.StrEnum):
    """External provider resource availability."""

    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    DELETED = "deleted"


class ExternalChannelHydrationStatus(enum.StrEnum):
    """Initial provider-history hydration state for one external resource."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    BOUNDED = "bounded"
    INCOMPLETE = "incomplete"


class ExternalChannelEventEligibilityState(enum.StrEnum):
    """Classification state for one admitted provider event."""

    UNCLASSIFIED = "unclassified"
    TRACKED = "tracked"
    IGNORED = "ignored"
    PROCESSED = "processed"


class ExternalChannelEventStatus(enum.StrEnum):
    """Asynchronous processing status for one admitted provider event."""

    ACCEPTED = "accepted"
    IGNORED_UNLINKED = "ignored_unlinked"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class ExternalChannelPrincipalAuthorType(enum.StrEnum):
    """External principal author category."""

    HUMAN = "human"
    BOT = "bot"
    APP = "app"
    SYSTEM = "system"


class ExternalChannelMessageLifecycle(enum.StrEnum):
    """Current provider lifecycle state for an external message."""

    CURRENT = "current"
    EDITED = "edited"
    DELETED = "deleted"


class ExternalChannelMessageRevisionKind(enum.StrEnum):
    """Provider lifecycle change represented by one message revision."""

    ORIGINAL = "original"
    EDIT = "edit"
    DELETE = "delete"


class ExternalChannelBindingStatus(enum.StrEnum):
    """Session binding lifecycle status."""

    ACTIVE = "active"
    DISCONNECTED = "disconnected"


class ExternalChannelBindingActivationStatus(enum.StrEnum):
    """Initial invocation activation state for one active binding."""

    WAITING_HYDRATION = "waiting_hydration"
    ACTIVE = "active"


class ExternalChannelAccessRequestStatus(enum.StrEnum):
    """External invocation access-request state."""

    PENDING = "pending"
    ALLOWED = "allowed"
    DENIED = "denied"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class ExternalChannelAccessGrantScope(enum.StrEnum):
    """Scope of an external principal invocation grant."""

    SESSION = "session"
    AGENT = "agent"


class ExternalChannelWorkStatus(enum.StrEnum):
    """Binding-scoped Channel Work lifecycle status."""

    ACTIVE = "active"
    FINISHED = "finished"


class ExternalChannelWorkTaskStatus(enum.StrEnum):
    """Status of one ordered Channel Work task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ExternalChannelActionMode(enum.StrEnum):
    """Atomic Channel Action mode."""

    FINISH = "finish"
    CONTINUE = "continue"


class ExternalChannelDeliveryOriginType(enum.StrEnum):
    """Domain origin that committed a provider delivery intent."""

    CHANNEL_ACTION = "channel_action"
    ACCESS_REQUEST = "access_request"
    BINDING_DISCONNECT = "binding_disconnect"
    CONNECTION_DISCONNECT = "connection_disconnect"
    MANAGER_OPERATION = "manager_operation"


class ExternalChannelDeliveryOperation(enum.StrEnum):
    """External provider side effect requested by a delivery intent."""

    REPLY = "reply"
    PROGRESS_CREATE = "progress_create"
    PROGRESS_UPDATE = "progress_update"
    PROGRESS_DELETE = "progress_delete"
    CONTROL_MESSAGE = "control_message"


class ExternalChannelDeliveryStatus(enum.StrEnum):
    """Outcome state of one external provider delivery attempt."""

    PENDING = "pending"
    ATTEMPTING = "attempting"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_ATTEMPTED = "not_attempted"
