/** Chat feature status type */

import type {
  AgentResponse,
  ChatEventResponse,
  InputActionDefinitionResponse,
  SessionInitializationEventResponse,
  SessionInitializationResponse,
} from "@azents/public-client";

// --- WebSocket event type ---

/** Token usage (turn_complete marker) */
export interface WireTokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens?: number | null;
  cache_creation_tokens?: number | null;
  reasoning_tokens?: number | null;
}

export interface TokenUsageSummary {
  promptTokens: number | null;
  completionTokens: number | null;
  totalTokens: number | null;
  cachedTokens: number | null;
  cacheCreationTokens: number | null;
  reasoningTokens: number | null;
}

export type AgentRunPhase =
  | "idle"
  | "preparing_input"
  | "waiting_for_model"
  | "streaming_model"
  | "normalizing_output"
  | "executing_tools"
  | "appending_events"
  | "compacting"
  | "stopping";

export interface ChatAttachmentSnapshot {
  attachment_id?: string | null;
  uri: string;
  name: string;
  media_type: string;
  size: number;
  text_preview?: string | null;
  availability?: "available" | "expired" | "unavailable";
  preview_title?: string | null;
  preview_thumbnail_uri?: string | null;
  preview_thumbnail_media_type?: string | null;
  preview_thumbnail_width?: number | null;
  preview_thumbnail_height?: number | null;
  preview_generated_at?: string | null;
}

export type EventAttachment = ChatAttachmentSnapshot;

export interface TextPart {
  type: "text" | "output_text" | "input_text";
  text: string;
}

export interface AttachmentPart {
  type: "attachment";
  attachment_id?: string | null;
  uri: string;
  name: string;
  media_type: string;
  size: number;
  preview_title?: string | null;
  text_preview?: string | null;
  preview_thumbnail_uri?: string | null;
  preview_thumbnail_media_type?: string | null;
  preview_thumbnail_width?: number | null;
  preview_thumbnail_height?: number | null;
  preview_generated_at?: string | null;
  availability?: "available" | "expired" | "unavailable";
}

export interface ArtifactPart {
  type: "artifact";
  artifact_id: string;
  uri: string;
  name: string;
  media_type: string;
  size: number;
  status?: "available" | "expired";
  expires_after_run_index?: number | null;
}

export interface FilePart {
  type: "file";
  model_file_id: string;
  media_type: string;
  name?: string | null;
  size?: number | null;
  kind?: "image" | "document" | "text" | "binary" | null;
  caption?: string | null;
  alt_text?: string | null;
  metadata?: Record<string, string>;
}

export type OutputPart = TextPart | AttachmentPart | ArtifactPart | FilePart;

export type UserContentPart = TextPart | FilePart;

export type ChatAction =
  | { type: "command"; name: string }
  | { type: "goal" }
  | { type: "skill"; skill_path: string };

export interface ActionMessagePayload {
  action: ChatAction;
  message: string;
}

export interface UserMessagePayload {
  content: string | UserContentPart[];
  attachments: EventAttachment[];
  metadata: Record<string, string>;
}

export interface AssistantMessagePayload {
  content: string | OutputPart[];
  attachments: EventAttachment[];
}

export interface ReasoningPayload {
  text?: string | null;
  summary?: string | null;
}

export interface ClientToolCallPayload {
  call_id: string;
  name: string;
  arguments: string;
}

export type ToolResultStatus =
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface ClientToolResultPayload {
  call_id: string;
  name?: string | null;
  status: ToolResultStatus;
  output: string | OutputPart[];
  attachments: EventAttachment[];
}

export interface ProviderToolCallPayload {
  call_id: string;
  name: string;
  arguments?: string | null;
}

export interface ProviderToolResultPayload {
  call_id: string;
  name?: string | null;
  status: ToolResultStatus;
  output: string | OutputPart[];
  attachments: EventAttachment[];
}

export interface TurnMarkerPayload {
  run_id: string;
  usage?: WireTokenUsage | null;
}

export interface RunMarkerPayload {
  run_id: string;
  status: "completed" | "stopped" | "failed" | "interrupted";
}

export interface InterruptedPayload {
  run_id: string;
  reason: "user_requested";
}

export interface CompactionSummaryPayload {
  compaction_id: string;
  content: string;
  covered_until_event_id?: string | null;
}

export interface CompactionMarkerPayload {
  compaction_id: string;
  status: "started" | "failed";
  reason?: string | null;
  error?: string | null;
}

export interface SubagentStartPayload {
  subagent_run_id: string;
  subagent_id: string;
  subagent_name: string;
  subagent_session_id: string;
}

export interface SubagentEndPayload {
  subagent_run_id: string;
  subagent_id: string;
  subagent_session_id: string;
  status: "completed" | "failed" | "interrupted";
  result?: string | null;
  error?: string | null;
}

export interface GoalBriefingPayload {
  objective: string;
  created_at: string;
  completed_at: string;
  duration_seconds?: number | null;
}

export interface SkillLoadedPayload {
  name: string;
  skill_path: string;
  body: string;
  user_message: string;
  content_hash: string;
  source_label: string;
  relative_hint: string;
}

export interface SystemReminderPayload {
  text: string;
}

export type FailedRunFinalizationReason =
  | "retry_exhausted"
  | "retry_stopped_by_user"
  | "non_retryable";

export type FailedRunRetryability =
  | "unknown"
  | "transient"
  | "user_action_required"
  | "non_retryable";

export interface FailedRunFailureMetadata {
  kind: "failed_run";
  finalization_reason: FailedRunFinalizationReason;
  failed_attempt_count: number;
  max_retries: number;
  last_error_type?: string | null;
  retryability?: FailedRunRetryability | null;
  failure_code?: string | null;
  action_hint?: string | null;
}

export interface SystemErrorPayload {
  content: string;
  severity?: "info" | "warning" | "error" | null;
  recoverable?: boolean | null;
  reset_suggested?: boolean | null;
  failure?: FailedRunFailureMetadata | null;
}

export interface UnknownAdapterOutputPayload {
  reason?: string | null;
}

export type ChatEventPayload =
  | UserMessagePayload
  | AssistantMessagePayload
  | ReasoningPayload
  | ClientToolCallPayload
  | ClientToolResultPayload
  | ProviderToolCallPayload
  | ProviderToolResultPayload
  | TurnMarkerPayload
  | RunMarkerPayload
  | InterruptedPayload
  | CompactionMarkerPayload
  | CompactionSummaryPayload
  | SubagentStartPayload
  | SubagentEndPayload
  | GoalBriefingPayload
  | ActionMessagePayload
  | SkillLoadedPayload
  | SystemReminderPayload
  | SystemErrorPayload
  | UnknownAdapterOutputPayload;

export interface EventBase<
  Kind extends string,
  Payload extends ChatEventPayload,
> {
  id: string;
  session_id: string;
  kind: Kind;
  payload: Payload;
  external_id?: string | null;
  model?: string | null;
  created_at: string;
}

export type ChatHistoryEvent =
  | EventBase<"user_message", UserMessagePayload>
  | EventBase<"assistant_message", AssistantMessagePayload>
  | EventBase<"reasoning", ReasoningPayload>
  | EventBase<"client_tool_call", ClientToolCallPayload>
  | EventBase<"client_tool_result", ClientToolResultPayload>
  | EventBase<"provider_tool_call", ProviderToolCallPayload>
  | EventBase<"provider_tool_result", ProviderToolResultPayload>
  | EventBase<"turn_marker", TurnMarkerPayload>
  | EventBase<"run_marker", RunMarkerPayload>
  | EventBase<"interrupted", InterruptedPayload>
  | EventBase<"compaction_marker", CompactionMarkerPayload>
  | EventBase<"compaction_summary", CompactionSummaryPayload>
  | EventBase<"subagent_start", SubagentStartPayload>
  | EventBase<"subagent_end", SubagentEndPayload>
  | EventBase<"goal_continuation", UserMessagePayload>
  | EventBase<"goal_updated", UserMessagePayload>
  | EventBase<"goal_briefing", GoalBriefingPayload>
  | EventBase<"action_message", ActionMessagePayload>
  | EventBase<"skill_loaded", SkillLoadedPayload>
  | EventBase<"system_reminder", SystemReminderPayload>
  | EventBase<"system_error", SystemErrorPayload>
  | EventBase<"unknown_adapter_output", UnknownAdapterOutputPayload>;

// ---------------------------------------------------------------------------
// EngineEvent — top-level discriminator + flat fields (Pydantic discriminated
// union dump as-is). events-unification format does not change after.
// ---------------------------------------------------------------------------

/** run completion control event */
export interface RunCompleteControlEvent {
  type: "run_complete";
}

/** run start — notify client that processing is in progress */
export interface RunStartedEvent {
  type: "run_started";
  run_id: string;
  phase?: AgentRunPhase | null;
}

/** run phase change — UI activity source */
export interface RunPhaseChangedEvent {
  type: "run_phase_changed";
  run_id: string;
  phase: AgentRunPhase;
}

/** run stop — user stopped run */
export interface RunStoppedEvent {
  type: "run_stopped";
}

/** Runtime allocating */
export interface RuntimeInitializingEvent {
  type: "runtime_initializing";
}

/** Runtime ready */
export interface RuntimeReadyEvent {
  type: "runtime_ready";
}

/** Runtime error */
export interface RuntimeErrorEvent {
  type: "runtime_error";
  message: string;
}

/** OAuth2 authorization request — per-user auth sent when required */
export interface AuthorizationRequestEvent {
  type: "authorization_request";
  toolkit_id: string;
  toolkit_name: string;
}

/** account linking nudge — per-user auth required when */
export interface AccountLinkNudgeEvent {
  type: "account_link_nudge";
  toolkit_name: string;
  toolkit_type: string;
  toolkit_id: string;
}

/** Compaction start — context compression in progress */
export interface CompactionStartedEvent {
  type: "compaction_started";
  continuing?: boolean;
}

/** Compaction complete — context compression complete */
export interface CompactionCompleteEvent {
  type: "compaction_complete";
  continuing?: boolean;
}

/** session create complete — server assigned session_id */
export interface SessionCreatedEvent {
  type: "session_created";
  session_id: string;
}

export type TodoStatus = "pending" | "in_progress" | "completed";

export interface TodoItem {
  content: string;
  status: TodoStatus;
}

export interface TodoStateSnapshot {
  items: TodoItem[];
}

export type GoalStatus = "active" | "paused" | "blocked" | "complete";

export interface GoalStateSnapshot {
  objective: string | null;
  status: GoalStatus | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TodoStateChangedEvent {
  type: "todo_state_changed";
  todo: TodoStateSnapshot;
}

// ---------------------------------------------------------------------------
// Event envelope — events-unification after durable items  of wire shape.
// Pydantic Event  of model_dump result: top-level type (computed_field  with
// item.type delegation) + envelope field + ``item`` discriminated union.
// ---------------------------------------------------------------------------

/** TurnComplete payload */
export interface TurnCompletePayload {
  type: "turn_complete";
  usage: WireTokenUsage | null;
}

/** RunComplete payload */
export interface RunCompletePayload {
  type: "run_complete";
}

/** UnknownItem payload — ignored target */
export interface UnknownItemPayload {
  type: "unknown_item";
}

/** Error item payload (envelope inside of content) */
export interface ErrorItemPayload {
  type: "error";
  content: string;
}

/** SubagentStart payload */
export interface EngineSubagentStartPayload {
  type: "subagent_start";
  subagent_id: string;
  subagent_name: string;
  subagent_session_id: string;
}

/** SubagentEnd payload */
export interface EngineSubagentEndPayload {
  type: "subagent_end";
  subagent_id: string;
  subagent_session_id: string;
  result: string;
}

/** Compaction summary item payload */
export interface CompactionItemPayload {
  type: "compaction";
  content: string;
}

/** UI  handled envelope item payloads */
export type ChatEventItemPayload =
  | TurnCompletePayload
  | RunCompletePayload
  | UnknownItemPayload
  | ErrorItemPayload
  | EngineSubagentStartPayload
  | EngineSubagentEndPayload
  | CompactionItemPayload;

/** Event envelope common wrapper.
 *
 * computed_field type  top-level + item.type both to appears the same.
 * dispatch  top-level type  with is possible, but, payload field ``item`` inside to
 * position.
 */
export interface ChatEnvelope<T extends ChatEventItemPayload> {
  type: T["type"];
  id: string;
  item: T;
  external_id: string | null;
  source_model: string | null;
}

export type TurnCompleteEvent = ChatEnvelope<TurnCompletePayload>;
export type RunCompleteEvent = ChatEnvelope<RunCompletePayload>;
export type UnknownItemEvent = ChatEnvelope<UnknownItemPayload>;
export type ErrorEvent = ChatEnvelope<ErrorItemPayload>;
export type SubagentStartEvent = ChatEnvelope<EngineSubagentStartPayload>;
export type SubagentEndEvent = ChatEnvelope<EngineSubagentEndPayload>;
export type CompactionItemEvent = ChatEnvelope<CompactionItemPayload>;

/** Runtime status (for UI display) */
export type RuntimeStatus = "idle" | "initializing" | "ready" | "error";

export interface HistoryEventAppendedEvent {
  type: "history_event_appended";
  session_id: string;
  event: ChatEventResponse;
}

export interface LiveEventUpsertedEvent {
  type: "live_event_upserted";
  session_id: string;
  event: ChatEventResponse;
}

export interface LiveEventRemovedEvent {
  type: "live_event_removed";
  session_id: string;
  event_id: string;
}

export interface SubscribedEvent {
  type: "subscribed";
  session_id: string;
}

export interface InputActionsUpdatedEvent {
  type: "input_actions_updated";
  session_id: string;
}

export interface SessionInitializationUpdatedEvent {
  type: "session_initialization_updated";
  session_id: string;
  initialization: SessionInitializationResponse;
}

export interface SessionInitializationEventAppendedEvent {
  type: "session_initialization_event_appended";
  session_id: string;
  event: SessionInitializationEventResponse;
}

export type SessionInitializationDetailState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      events: SessionInitializationEventResponse[];
    };

export interface SubscriptionHealthCheckAckEvent {
  type: "subscription_health_check_ack";
  session_id: string;
  request_id?: string | null;
}

export type AgentRunStatus =
  | "running"
  | "completed"
  | "stopped"
  | "failed"
  | "interrupted";

export interface ChatLiveRunState {
  run_id: string;
  phase: AgentRunPhase;
  status: AgentRunStatus;
}

export type ChatEvent =
  | ErrorEvent
  | TurnCompleteEvent
  | UnknownItemEvent
  | RunCompleteEvent
  | RunCompleteControlEvent
  | RunStartedEvent
  | RunPhaseChangedEvent
  | RunStoppedEvent
  | RuntimeInitializingEvent
  | RuntimeReadyEvent
  | RuntimeErrorEvent
  | AuthorizationRequestEvent
  | CompactionStartedEvent
  | CompactionCompleteEvent
  | SubagentStartEvent
  | SubagentEndEvent
  | CompactionItemEvent
  | SessionCreatedEvent
  | TodoStateChangedEvent
  | AccountLinkNudgeEvent
  | HistoryEventAppendedEvent
  | LiveEventUpsertedEvent
  | LiveEventRemovedEvent
  | SubscribedEvent
  | InputActionsUpdatedEvent
  | SessionInitializationUpdatedEvent
  | SessionInitializationEventAppendedEvent
  | SubscriptionHealthCheckAckEvent
  | ChatHistoryEvent;

/** authorization request data (UIfor camelCase convert).
 *
 * current wire (events-unification)  of ``authorization_request``
 * URL  textdotext textso with ``authorizationUrl``  empty string fallback.
 * REST based URL text follow-up text temporary keep (#3153).
 */
export interface AuthorizationRequest {
  toolkitId: string;
  toolkitName: string;
  authorizationUrl: string;
}

/** file attachment see (session data integration) */
export interface FileAttachment {
  attachmentId?: string | null;
  uri: string;
  mediaType: string;
  size?: number;
  name?: string;
  textPreview?: string | null;
  availability?: "available" | "expired" | "unavailable";
  previewTitle?: string | null;
  previewThumbnailUri?: string | null;
  previewThumbnailMediaType?: string | null;
  previewThumbnailWidth?: number | null;
  previewThumbnailHeight?: number | null;
  previewGeneratedAt?: string | null;
}

/** model turn not yet not injected user input */
export interface PendingInputBuffer {
  id: string;
  sessionId: string;
  content: string;
  action?: ChatAction | null;
  attachments: string[];
  fileParts?: FilePart[];
  attachmentFiles?: FileAttachment[];
  metadata: Record<string, string>;
  createdAt: string;
  status: "sending" | "pending" | "deleting";
}

export type InputActionDefinition = Omit<
  InputActionDefinitionResponse,
  "action"
> & {
  action: ChatAction;
  source_label?: string | null;
  relative_hint?: string | null;
};

/** WebSocket stop request */
// --- UI status type ---

/** in-progress tool call status */
export interface ActiveToolCall {
  id: string;
  callId?: string;
  name: string;
  arguments: string;
  result?: string;
  status: "preparing" | "running" | ToolResultStatus;
  attachments?: FileAttachment[];
}

export interface ProviderToolCall {
  id: string;
  callId?: string;
  name: string;
  arguments: string;
  status: "completed" | "failed" | "running" | "unknown";
}

/** message status — WS streamingand REST common */
export type MessageStatus = "partial" | "complete";

/** chat message (for UI display) */
export interface ChatMessage {
  id: string;
  role:
    | "user"
    | "assistant"
    | "system"
    | "tool"
    | "error"
    | "turn_complete"
    | "run_complete"
    | "interrupted"
    | "compaction"
    | "compaction_started"
    | "goal_continuation"
    | "goal_updated"
    | "goal_briefing"
    | "skill_loaded"
    | "subagent_start"
    | "subagent_end";
  content: string | null;
  toolCalls?: ActiveToolCall[];
  providerToolCalls?: ProviderToolCall[];
  toolCallId?: string | null;
  createdAt: string;
  /** message status: partial=streaming, complete=complete */
  status?: MessageStatus;
  attachments?: FileAttachment[];
  /** Reasoning/thinking summary text (collapsible for display) */
  reasoningSummary?: string;
  /** textper token usage (turn_complete usage text toonly text) */
  usage?: Record<string, unknown> | null;
  /** selected action for action-message user input */
  action?: ChatAction | null;
  /** message metadata (subagent event etc.) */
  metadata?: Record<string, string> | null;
}

/** Agent list status */
export type AgentListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; agents: AgentResponse[] };

/** WebSocket connection status */
export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting";

/** chat view status */
export type ChatViewState =
  | { type: "EMPTY" }
  | { type: "LOADING_HISTORY" }
  | { type: "READY" };

/** chat timeline rendering mode */
export type ChatTimelineState =
  | { type: "LATEST_FOLLOWING" }
  | {
      type: "DETACHED_HISTORY_BROWSING";
      hasNewer: boolean;
      newestCursor: string | null;
    };
