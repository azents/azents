"use client";

/**
 * Single-session container hook.
 *
 * WebSocket connection, message history, pagination, authorization request, compaction status etc.
 * that must be isolated per session status manages.. parent(useChatPageContainer) in
 * key based remount with when session switches  hook  of instance is completely replaced
 * previous session of WebSocket/buffer new session to ensures it does not leak.
 */

import * as Sentry from "@sentry/nextjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  applyProviderToolCallItem,
  applyProviderToolCallOutput,
} from "../hooks/providerToolCallProjection";
import {
  applyFunctionCallItem,
  applyFunctionCallOutput,
} from "../hooks/toolCallMerge";
import { useChatWebSocket } from "../hooks/useChatWebSocket";
import type { UploadedFile } from "../hooks/useFileUpload";
import type {
  ActionExecutionProjection,
  AgentRunPhase,
  AgentRunStatus,
  AuthorizationRequest,
  ChatAction,
  ChatEvent,
  ChatLiveRunState,
  ChatMessage,
  ChatTimelineState,
  ChatViewState,
  ConnectionStatus,
  FailedRunAttemptSummary,
  FailedRunFailureMetadata,
  FailedRunFinalizationReason,
  FailedRunRetryability,
  FileAttachment,
  GoalStateSnapshot,
  InputActionDefinition,
  PendingInputBuffer,
  TodoStateSnapshot,
  TokenUsageSummary,
  ToolResultStatus,
} from "../types";
import type {
  ActionExecutionProjectionResponse,
  AgentResponse,
  AppliedInferenceProfile,
  ChatEventResponse,
  ChatWriteResponse,
  LiveEventListResponse,
  RequestedInferenceProfile,
} from "@azents/public-client";

export type SessionRunState = "idle" | "running";

type WritableChatAction = Extract<
  ChatAction,
  { type: "command" } | { type: "goal" } | { type: "skill" }
>;

function writableChatAction(
  action?: ChatAction | null,
): WritableChatAction | null {
  if (action == null) {
    return null;
  }
  switch (action.type) {
    case "command":
    case "goal":
    case "skill":
      return action;
    case "create_git_worktree":
      return null;
  }
}

interface ChatSessionContainerProps {
  /** URL-selected AgentSession ID */
  sessionId: string;
  /** this session agent */
  agent: AgentResponse;
  /** WebSocket connection status parent to push (for sidebar badge) */
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export interface ChatSessionContainerOutput {
  /** current session ID */
  sessionId: string;
  /** chat view status */
  chatViewState: ChatViewState;
  /** chat timeline rendering mode */
  chatTimelineState: ChatTimelineState;
  /** chat message list */
  messages: ChatMessage[];
  /** not yet model turn  to not injected pending input buffers */
  pendingInputBuffers: PendingInputBuffer[];
  /** WebSocket connection status */
  connectionStatus: ConnectionStatus;
  /** waiting for response */
  isResponsePending: boolean;
  /** REST write request sending */
  isWritePending: boolean;
  /** whether to show model response waiting/streaming indicator */
  isModelResponsePending: boolean;
  /** current live run snapshot, including retry recovery state */
  liveRun: ChatLiveRunState | null;
  /** whether older messages exist */
  hasMore: boolean;
  /** older messages loading */
  isLoadingMore: boolean;
  /** newer messages loading */
  isLoadingNewer: boolean;
  /** profile used when Composer has no local unsent override */
  defaultInferenceProfile: RequestedInferenceProfile;
  /** message send */
  onSendInput: (
    message: string,
    action: ChatAction | null,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** delete pending input buffer */
  onDeletePendingInputBuffer: (bufferId: string) => void;
  /** Goal delete */
  onClearGoal: () => Promise<boolean>;
  /** Goal update */
  onUpdateGoal: (objective: string) => Promise<boolean>;
  /** Goal textwhentext */
  onPauseGoal: () => Promise<boolean>;
  /** Goal text */
  onResumeGoal: (hint?: string) => Promise<boolean>;
  /** load older events, optionally preserving latest-follow state */
  onLoadMore: (options?: { detachFromLatest?: boolean }) => void;
  /** newer messages  withtext */
  onLoadNewer: () => void;
  /** latest reset */
  onResetToLatest: () => void;
  /** submit user message edit */
  onSubmitMessageEdit: (
    messageId: string,
    message: string,
    inferenceProfile: RequestedInferenceProfile,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** retry the latest terminal failed run */
  onRetryFailedRun: (failedEventId: string) => Promise<boolean>;
  /** Context compaction whether in progress */
  isCompacting: boolean;
  /** whether commands are blocked during Run */
  wasCommandBlocked: boolean;
  /** Session run_state based on stop button exposed whether */
  isStopAvailable: boolean;
  /** whether stop request is being sent */
  isStopPending: boolean;
  /** run stop request */
  onStopRequest: () => void;
  /** server-managed input action list */
  inputActions: InputActionDefinition[];
  /** pending OAuth authorization request list */
  authorizationRequests: AuthorizationRequest[];
  /** auth complete when remove corresponding request */
  onAuthorizationComplete: (toolkitId: string) => void;
  /** current operation TurnAction execution projections */
  actionExecutions: ActionExecutionProjection[];
  /** latest turn usage */
  tokenUsage: TokenUsageSummary | null;
  /** current session goal snapshot */
  goal: GoalStateSnapshot;
  /** current session todo snapshot */
  todo: TodoStateSnapshot;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringField(
  record: Record<string, unknown>,
  key: string,
): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function numberField(
  record: Record<string, unknown>,
  key: string,
): number | null {
  const value = record[key];
  return typeof value === "number" ? value : null;
}

function booleanField(
  record: Record<string, unknown>,
  key: string,
): boolean | null {
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

function reasoningEffortFromValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function requestedInferenceProfileFromValue(
  value: unknown,
): RequestedInferenceProfile | null {
  if (!isRecord(value)) {
    return null;
  }
  const modelTargetLabel = stringField(value, "model_target_label");
  if (modelTargetLabel === null) {
    return null;
  }
  const effortValue = value.reasoning_effort;
  const reasoningEffort = reasoningEffortFromValue(effortValue);
  if (effortValue != null && reasoningEffort === null) {
    return null;
  }
  return {
    model_target_label: modelTargetLabel,
    reasoning_effort: reasoningEffort,
  };
}

function eventRequestedInferenceProfile(
  event: ChatEventResponse,
): RequestedInferenceProfile | null {
  return requestedInferenceProfileFromValue(
    event.payload.requested_inference_profile,
  );
}

function appliedInferenceProfileFromValue(
  value: unknown,
): AppliedInferenceProfile | null {
  if (!isRecord(value)) {
    return null;
  }
  const modelTargetLabel = stringField(value, "model_target_label");
  const hasModelDisplayName = "model_display_name" in value;
  const modelDisplayName = value.model_display_name;
  const hasReasoningEffort = "reasoning_effort" in value;
  const effortValue = value.reasoning_effort;
  const reasoningEffort = reasoningEffortFromValue(effortValue);
  if (
    modelTargetLabel === null ||
    modelTargetLabel.length === 0 ||
    (hasModelDisplayName &&
      modelDisplayName !== null &&
      (typeof modelDisplayName !== "string" ||
        modelDisplayName.length === 0)) ||
    (hasReasoningEffort && effortValue !== null && reasoningEffort === null)
  ) {
    return null;
  }
  return {
    model_target_label: modelTargetLabel,
    model_display_name:
      typeof modelDisplayName === "string" ? modelDisplayName : null,
    reasoning_effort: reasoningEffort,
  };
}

function chatActionFromValue(value: unknown): ChatAction | null {
  if (!isRecord(value) || typeof value.type !== "string") {
    return null;
  }
  if (
    value.type === "command" &&
    "name" in value &&
    typeof value.name === "string"
  ) {
    return { type: "command", name: value.name };
  }
  if (value.type === "goal") {
    return { type: "goal" };
  }
  if (
    value.type === "skill" &&
    "skill_path" in value &&
    typeof value.skill_path === "string"
  ) {
    return { type: "skill", skill_path: value.skill_path };
  }
  if (
    value.type === "create_git_worktree" &&
    typeof value.source_project_path === "string" &&
    typeof value.starting_ref === "string"
  ) {
    return {
      type: "create_git_worktree",
      source_project_path: value.source_project_path,
      starting_ref: value.starting_ref,
    };
  }
  return null;
}

interface DurableInferenceIntent {
  modelOrder: number;
  profile: RequestedInferenceProfile;
}

function latestDurableInferenceIntent(
  events: ChatEventResponse[],
): DurableInferenceIntent | null {
  let latest: DurableInferenceIntent | null = null;
  for (const event of events) {
    if (event.kind !== "user_message" && event.kind !== "action_message") {
      continue;
    }
    const profile = eventRequestedInferenceProfile(event);
    if (
      profile !== null &&
      (latest === null || event.model_order >= latest.modelOrder)
    ) {
      latest = { modelOrder: event.model_order, profile };
    }
  }
  return latest;
}

function toolResultStatusFromPayload(
  payload: Record<string, unknown>,
): ToolResultStatus {
  switch (payload.status) {
    case "failed":
    case "cancelled":
    case "interrupted":
      return payload.status;
    default:
      return "completed";
  }
}

function providerToolCallStatusFromPayload(
  payload: Record<string, unknown>,
): "completed" | "failed" | "running" | "unknown" {
  switch (payload.status) {
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "running":
    case "in_progress":
      return "running";
    default:
      return "unknown";
  }
}

function agentRunPhaseFromValue(value: unknown): AgentRunPhase | null {
  switch (value) {
    case "idle":
    case "preparing_input":
    case "waiting_for_model":
    case "streaming_model":
    case "normalizing_output":
    case "executing_tools":
    case "appending_events":
    case "compacting":
    case "stopping":
      return value;
    default:
      return null;
  }
}

function isModelRunPhase(phase: AgentRunPhase | null): boolean {
  return phase === "waiting_for_model" || phase === "streaming_model";
}

function isUserBlockingRunPhase(phase: AgentRunPhase | null): boolean {
  return phase !== null && phase !== "idle";
}

function agentRunStatusFromValue(value: unknown): AgentRunStatus | null {
  switch (value) {
    case "pending":
    case "running":
    case "completed":
    case "stopped":
    case "failed":
    case "interrupted":
    case "cancelled":
      return value;
    default:
      return null;
  }
}

function failedRunFinalizationReasonFromValue(
  value: unknown,
): FailedRunFinalizationReason | null {
  switch (value) {
    case "retry_exhausted":
    case "retry_stopped_by_user":
    case "non_retryable":
      return value;
    default:
      return null;
  }
}

function failedRunRetryabilityFromValue(
  value: unknown,
): FailedRunRetryability | null {
  switch (value) {
    case "unknown":
    case "transient":
    case "user_action_required":
    case "non_retryable":
      return value;
    default:
      return null;
  }
}

function failedRunAttemptFromRecord(
  record: Record<string, unknown>,
): FailedRunAttemptSummary | null {
  const attemptNumber = numberField(record, "attempt_number");
  const userMessage = stringField(record, "user_message");
  const errorType = stringField(record, "error_type");
  const source = stringField(record, "source");
  const failedAt = stringField(record, "failed_at");
  const backoffSeconds = numberField(record, "backoff_seconds");
  const nextRetryAt = stringField(record, "next_retry_at");
  const retryability = stringField(record, "retryability");
  const truncated = booleanField(record, "truncated");
  if (
    attemptNumber === null ||
    userMessage === null ||
    errorType === null ||
    source === null ||
    failedAt === null ||
    backoffSeconds === null ||
    nextRetryAt === null ||
    retryability === null ||
    truncated === null
  ) {
    return null;
  }
  return {
    attemptNumber,
    userMessage,
    errorType,
    source,
    failedAt,
    backoffSeconds,
    nextRetryAt,
    retryability,
    failureCode: stringField(record, "failure_code"),
    truncated,
  };
}

function failedRunAttemptsFromValue(value: unknown): FailedRunAttemptSummary[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (!isRecord(item)) {
      return [];
    }
    const attempt = failedRunAttemptFromRecord(item);
    return attempt === null ? [] : [attempt];
  });
}

function failedRunFailureFromValue(
  failure: unknown,
): FailedRunFailureMetadata | null {
  if (!isRecord(failure) || failure.kind !== "failed_run") {
    return null;
  }
  const finalizationReason = failedRunFinalizationReasonFromValue(
    failure.finalization_reason,
  );
  const failedAttemptCount = numberField(failure, "failed_attempt_count");
  const maxRetries = numberField(failure, "max_retries");
  if (
    finalizationReason === null ||
    failedAttemptCount === null ||
    maxRetries === null
  ) {
    return null;
  }
  return {
    kind: "failed_run",
    finalization_reason: finalizationReason,
    failed_attempt_count: failedAttemptCount,
    max_retries: maxRetries,
    last_error_type: stringField(failure, "last_error_type"),
    retryability: failedRunRetryabilityFromValue(failure.retryability),
    failure_code: stringField(failure, "failure_code"),
    action_hint: stringField(failure, "action_hint"),
    attempts: failedRunAttemptsFromValue(failure.attempts),
  };
}

function liveRunRetryFromRecord(
  record: Record<string, unknown>,
): ChatLiveRunState["retry"] {
  const status = stringField(record, "status");
  const lastErrorMessage = stringField(record, "last_error_message");
  const failedAttemptCount = numberField(record, "failed_attempt_count");
  const maxRetries = numberField(record, "max_retries");
  const backoffSeconds = numberField(record, "backoff_seconds");
  const nextRetryAt = stringField(record, "next_retry_at");
  if (
    status === null ||
    lastErrorMessage === null ||
    failedAttemptCount === null ||
    maxRetries === null ||
    backoffSeconds === null ||
    nextRetryAt === null
  ) {
    return null;
  }
  return {
    status,
    lastErrorMessage,
    failedAttemptCount,
    maxRetries,
    backoffSeconds,
    nextRetryAt,
    attempts: failedRunAttemptsFromValue(record.attempts),
  };
}

function chatLiveRunStateFromValue(value: unknown): ChatLiveRunState | null {
  if (!isRecord(value)) {
    return null;
  }
  const runId = stringField(value, "run_id");
  const phase = agentRunPhaseFromValue(value.phase);
  const status = agentRunStatusFromValue(value.status);
  const inferenceProfile = appliedInferenceProfileFromValue(
    value.inference_profile,
  );
  if (
    runId === null ||
    phase === null ||
    status === null ||
    inferenceProfile === null
  ) {
    return null;
  }
  const retry = isRecord(value.retry)
    ? liveRunRetryFromRecord(value.retry)
    : null;
  return {
    run_id: runId,
    phase,
    status,
    inferenceProfile,
    retry,
  };
}

function usageNumberField(
  usage: Record<string, unknown>,
  key: string,
): number | null {
  const value = usage[key];
  return typeof value === "number" ? value : null;
}

function tokenUsageFromRecord(
  usage: Record<string, unknown>,
): TokenUsageSummary | null {
  const totalTokens = usageNumberField(usage, "total_tokens");
  if (totalTokens === null) {
    return null;
  }
  return {
    runId: stringField(usage, "run_id"),
    inferenceProfile: appliedInferenceProfileFromValue(
      usage.applied_inference_profile,
    ),
    effectiveContextWindowTokens: usageNumberField(
      usage,
      "effective_context_window_tokens",
    ),
    effectiveAutoCompactionThresholdTokens: usageNumberField(
      usage,
      "effective_auto_compaction_threshold_tokens",
    ),
    promptTokens: usageNumberField(usage, "prompt_tokens"),
    completionTokens: usageNumberField(usage, "completion_tokens"),
    totalTokens,
    cachedTokens: usageNumberField(usage, "cached_tokens"),
    cacheCreationTokens: usageNumberField(usage, "cache_creation_tokens"),
    reasoningTokens: usageNumberField(usage, "reasoning_tokens"),
  };
}

function latestTokenUsage(messages: ChatMessage[]): TokenUsageSummary | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.role !== "turn_complete" || message.usage == null) {
      continue;
    }
    const usage = tokenUsageFromRecord(message.usage);
    if (usage !== null) {
      return usage;
    }
  }
  return null;
}

type LiveRunSnapshot =
  | { type: "ABSENT" }
  | { type: "INVALID"; value: unknown }
  | { type: "PRESENT"; run: ChatLiveRunState };

function liveRunSnapshotFromResponse(live: unknown): LiveRunSnapshot {
  if (!isRecord(live)) {
    return { type: "INVALID", value: live };
  }
  if (live.run == null) {
    return { type: "ABSENT" };
  }
  const run = chatLiveRunStateFromValue(live.run);
  return run === null
    ? { type: "INVALID", value: live.run }
    : { type: "PRESENT", run };
}

function liveRunPhase(liveRun: ChatLiveRunState | null): AgentRunPhase | null {
  return liveRun?.status === "running" ? liveRun.phase : null;
}

function sessionRunStateFromResponse(live: unknown): SessionRunState {
  if (!isRecord(live)) {
    return "idle";
  }
  return live.session_run_state === "running" ? "running" : "idle";
}

function recordArrayField(
  record: Record<string, unknown>,
  key: string,
): Record<string, unknown>[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(isRecord);
}

function attachmentFromRecord(
  record: Record<string, unknown>,
): FileAttachment | null {
  const uri = stringField(record, "uri");
  const mediaType = stringField(record, "media_type");
  const name = stringField(record, "name");
  if (uri === null || mediaType === null || name === null) {
    return null;
  }
  const size = record.size;
  return {
    attachmentId: stringField(record, "attachment_id"),
    uri,
    mediaType,
    name,
    ...(typeof size === "number" ? { size } : {}),
    textPreview: stringField(record, "text_preview"),
    availability:
      record.availability === "expired" || record.availability === "unavailable"
        ? record.availability
        : "available",
    previewTitle: stringField(record, "preview_title"),
    previewThumbnailUri: stringField(record, "preview_thumbnail_uri"),
    previewThumbnailMediaType: stringField(
      record,
      "preview_thumbnail_media_type",
    ),
    previewThumbnailWidth:
      typeof record.preview_thumbnail_width === "number"
        ? record.preview_thumbnail_width
        : null,
    previewThumbnailHeight:
      typeof record.preview_thumbnail_height === "number"
        ? record.preview_thumbnail_height
        : null,
    previewGeneratedAt: stringField(record, "preview_generated_at"),
  };
}

function eventAttachments(payload: Record<string, unknown>): FileAttachment[] {
  return recordArrayField(payload, "attachments").flatMap((item) => {
    const attachment = attachmentFromRecord(item);
    return attachment === null ? [] : [attachment];
  });
}

function contentAttachments(value: unknown): FileAttachment[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (!isRecord(item)) {
      return [];
    }
    if (item.type !== "attachment" && item.type !== "artifact") {
      return [];
    }
    const attachment = attachmentFromRecord(item);
    return attachment === null ? [] : [attachment];
  });
}

function contentText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (!Array.isArray(value)) {
    return "";
  }
  return value
    .flatMap((item) => {
      if (!isRecord(item)) {
        return [];
      }
      if (
        item.type === "text" ||
        item.type === "output_text" ||
        item.type === "input_text"
      ) {
        const text = stringField(item, "text");
        return text === null ? [] : [text];
      }
      return [];
    })
    .join("\n");
}

function eventMetadata(event: ChatEventResponse): Record<string, string> {
  return {
    event_id: event.id,
    event_render_key: eventRenderKey(event),
  };
}

function failedRunMetadataRecord(
  failure: FailedRunFailureMetadata | null,
): Record<string, string> | null {
  if (failure === null) {
    return null;
  }

  return {
    failed_run_kind: "failed_run",
    failed_run_finalization_reason: failure.finalization_reason,
    failed_run_failed_attempt_count: String(failure.failed_attempt_count),
    failed_run_max_retries: String(failure.max_retries),
    failed_run_last_error_type: failure.last_error_type ?? "",
    failed_run_retryability: failure.retryability ?? "",
    failed_run_failure_code: failure.failure_code ?? "",
    failed_run_action_hint: failure.action_hint ?? "",
  };
}

function nativeArtifactItem(
  event: ChatEventResponse,
): Record<string, unknown> | null {
  const artifact = event.payload.native_artifact;
  if (!isRecord(artifact)) {
    return null;
  }
  const item = artifact.item;
  return isRecord(item) ? item : null;
}

function eventProjectionRoot(event: ChatEventResponse): string {
  return event.external_id?.split(":", 1)[0] ?? event.id;
}

function eventRenderKey(event: ChatEventResponse): string {
  const projectionRoot = eventProjectionRoot(event);
  switch (event.kind) {
    case "assistant_message": {
      const item = nativeArtifactItem(event);
      if (item !== null) {
        const nativeId = stringField(item, "id");
        if (nativeId !== null) {
          return `assistant:native:${nativeId}`;
        }
        const contentIndex = item.content_index;
        if (typeof contentIndex === "number") {
          return `assistant:${projectionRoot}:content:${contentIndex}`;
        }
        const outputIndex = item.output_index;
        if (typeof outputIndex === "number") {
          return `assistant:${projectionRoot}:output:${outputIndex}`;
        }
      }
      return `assistant:event:${projectionRoot}`;
    }
    case "reasoning": {
      const item = nativeArtifactItem(event);
      const nativeId = item === null ? null : stringField(item, "id");
      return nativeId === null
        ? `reasoning:event:${projectionRoot}`
        : `reasoning:native:${nativeId}`;
    }
    case "client_tool_call": {
      const callId = stringField(event.payload, "call_id");
      return callId === null
        ? `tool:event:${event.external_id ?? event.id}`
        : `tool:${callId}`;
    }
    case "provider_tool_call": {
      const callId = stringField(event.payload, "call_id");
      return callId === null
        ? `provider-tool:event:${event.external_id ?? event.id}`
        : `provider-tool:${callId}`;
    }
    case "client_tool_result": {
      const callId = stringField(event.payload, "call_id");
      return callId === null
        ? `tool-result:event:${event.external_id ?? event.id}`
        : `tool-result:${callId}`;
    }
    case "provider_tool_result": {
      const callId = stringField(event.payload, "call_id");
      return callId === null
        ? `provider-tool-result:event:${event.external_id ?? event.id}`
        : `provider-tool-result:${callId}`;
    }
    default:
      return `event:${event.external_id ?? event.id}`;
  }
}

interface MapEventsOptions {
  initialMessages?: ChatMessage[];
  renderIncompleteToolCalls: boolean;
  messageStatus?: ChatMessage["status"];
}

function toolResultCallIds(items: ChatEventResponse[]): Set<string> {
  return new Set(
    items.flatMap((event) => {
      if (event.kind !== "client_tool_result") {
        return [];
      }
      const callId = stringField(event.payload, "call_id");
      return callId === null ? [] : [callId];
    }),
  );
}

function mapEvents(
  items: ChatEventResponse[],
  options: MapEventsOptions,
): ChatMessage[] {
  const renderableToolCallIds = options.renderIncompleteToolCalls
    ? null
    : toolResultCallIds(items);
  const messageStatus = options.messageStatus ?? "complete";
  return items.reduce<ChatMessage[]>((messages, event) => {
    const payload = event.payload;
    switch (event.kind) {
      case "user_message": {
        const content = contentText(payload.content);
        const attachments = [
          ...eventAttachments(payload),
          ...contentAttachments(payload.content),
        ];
        return [
          ...messages,
          {
            id: event.id,
            role: "user",
            content,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
            inferenceProfile: eventRequestedInferenceProfile(event),
            ...(attachments.length > 0 ? { attachments } : {}),
          },
        ];
      }
      case "action_message": {
        const action = chatActionFromValue(payload.action);
        if (action?.type === "skill") {
          return messages;
        }
        return [
          ...messages,
          {
            id: event.id,
            role: "user",
            content: stringField(payload, "message") ?? "",
            action,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
            inferenceProfile: eventRequestedInferenceProfile(event),
          },
        ];
      }
      case "agent_message": {
        return [
          ...messages,
          {
            id: event.id,
            role: "user",
            content: stringField(payload, "content") ?? "",
            createdAt: event.created_at,
            status: messageStatus,
            metadata: {
              ...eventMetadata(event),
              source: "agent_mailbox",
              message_kind: stringField(payload, "message_kind") ?? "",
              source_path: stringField(payload, "source_path") ?? "",
              target_path: stringField(payload, "target_path") ?? "",
            },
          },
        ];
      }
      case "assistant_message": {
        const content = contentText(payload.content);
        const attachments = [
          ...eventAttachments(payload),
          ...contentAttachments(payload.content),
        ];
        return [
          ...messages,
          {
            id: event.id,
            role: "assistant",
            content,
            createdAt: event.created_at,
            status: messageStatus,
            metadata: eventMetadata(event),
            ...(attachments.length > 0 ? { attachments } : {}),
          },
        ];
      }
      case "reasoning": {
        return [
          ...messages,
          {
            id: event.id,
            role: "assistant",
            content: null,
            createdAt: event.created_at,
            status: messageStatus,
            metadata: eventMetadata(event),
            reasoningSummary:
              stringField(payload, "summary") ??
              stringField(payload, "text") ??
              "",
          },
        ];
      }
      case "client_tool_call": {
        const callId = stringField(payload, "call_id");
        const name = stringField(payload, "name");
        if (callId === null || name === null) {
          return messages;
        }
        if (
          renderableToolCallIds !== null &&
          !renderableToolCallIds.has(callId)
        ) {
          return messages;
        }
        return applyFunctionCallItem(
          messages,
          {
            id: callId,
            callId,
            name,
            arguments: stringField(payload, "arguments") ?? "",
            status: "running",
          },
          event.id,
          event.created_at,
          messageStatus,
        );
      }
      case "provider_tool_call": {
        const callId = stringField(payload, "call_id");
        const name = stringField(payload, "name");
        if (callId === null || name === null) {
          return messages;
        }
        return applyProviderToolCallItem(
          messages,
          {
            id: callId,
            callId,
            name,
            arguments: stringField(payload, "arguments") ?? "",
            status:
              messageStatus === "partial"
                ? "running"
                : providerToolCallStatusFromPayload(payload),
          },
          event.id,
          event.created_at,
          messageStatus,
        );
      }
      case "client_tool_result": {
        const callId = stringField(payload, "call_id");
        if (callId === null) {
          return messages;
        }
        return applyFunctionCallOutput(messages, {
          callId,
          content: contentText(payload.output),
          status: toolResultStatusFromPayload(payload),
          attachments: [
            ...eventAttachments(payload),
            ...contentAttachments(payload.output),
          ],
        });
      }
      case "provider_tool_result": {
        const callId = stringField(payload, "call_id");
        if (callId === null) {
          return messages;
        }
        return applyProviderToolCallOutput(messages, {
          callId,
          name: stringField(payload, "name") ?? "Provider tool",
          output: contentText(payload.output),
          status:
            payload.status === "completed" || payload.status === "success"
              ? "completed"
              : "failed",
          attachments: [
            ...eventAttachments(payload),
            ...contentAttachments(payload.output),
          ],
          fallbackMessageId: event.id,
          createdAt: event.created_at,
          messageStatus,
        });
      }
      case "turn_marker": {
        const usage = isRecord(payload.usage)
          ? {
              ...payload.usage,
              run_id: stringField(payload, "run_id"),
              applied_inference_profile:
                payload.applied_inference_profile ?? null,
              effective_context_window_tokens: numberField(
                payload,
                "effective_context_window_tokens",
              ),
              effective_auto_compaction_threshold_tokens: numberField(
                payload,
                "effective_auto_compaction_threshold_tokens",
              ),
            }
          : null;
        return [
          ...messages,
          {
            id: event.id,
            role: "turn_complete",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            usage,
          },
        ];
      }
      case "run_marker": {
        if (payload.status !== "completed") {
          return messages;
        }
        return [
          ...messages,
          {
            id: event.id,
            role: "run_complete",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
      }
      case "interrupted": {
        return [
          ...messages,
          {
            id: event.id,
            role: "interrupted",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
      }
      case "compaction_summary": {
        return [
          ...messages,
          {
            id: event.id,
            role: "compaction",
            content: stringField(payload, "content"),
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
      }
      case "compaction_marker": {
        return [
          ...messages,
          {
            id: event.id,
            role: payload.status === "started" ? "compaction_started" : "error",
            content:
              stringField(payload, "reason") ??
              stringField(payload, "error") ??
              null,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
      }

      case "system_error": {
        const failedRunFailure = failedRunFailureFromValue(payload.failure);
        const failureMetadata = failedRunMetadataRecord(failedRunFailure);
        return [
          ...messages,
          {
            id: event.id,
            role: "error",
            content: stringField(payload, "content"),
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              ...(failureMetadata ?? {}),
            },
            failedRunFailure,
          },
        ];
      }
      case "goal_continuation": {
        return upsertMessageByMergeKey(messages, {
          id: event.id,
          role: "goal_continuation",
          content: null,
          createdAt: event.created_at,
          status: "complete",
          metadata: eventMetadata(event),
        });
      }
      case "goal_updated": {
        const metadata = isRecord(payload.metadata) ? payload.metadata : {};
        return [
          ...messages,
          {
            id: event.id,
            role: "goal_updated",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              objective: stringField(metadata, "goal_objective") ?? "",
            },
          },
        ];
      }
      case "goal_briefing": {
        return [
          ...messages,
          {
            id: event.id,
            role: "goal_briefing",
            content: stringField(payload, "objective"),
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              objective: stringField(payload, "objective") ?? "",
              created_at: stringField(payload, "created_at") ?? "",
              completed_at: stringField(payload, "completed_at") ?? "",
              duration_seconds:
                typeof payload.duration_seconds === "number"
                  ? String(payload.duration_seconds)
                  : "",
            },
          },
        ];
      }
      case "skill_loaded": {
        return [
          ...messages,
          {
            id: event.id,
            role: "skill_loaded",
            content: stringField(payload, "body"),
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              name: stringField(payload, "name") ?? "",
              skill_path: stringField(payload, "skill_path") ?? "",
              user_message: stringField(payload, "user_message") ?? "",
              content_hash: stringField(payload, "content_hash") ?? "",
              source_label: stringField(payload, "source_label") ?? "",
              relative_hint: stringField(payload, "relative_hint") ?? "",
            },
          },
        ];
      }
      case "action_execution_result":
      case "system_reminder":
      case "unknown_adapter_output": {
        return messages;
      }
    }
    return messages;
  }, options.initialMessages ?? []);
}

function isInputBufferLiveEvent(event: ChatEventResponse): boolean {
  if (event.kind === "action_message") {
    return true;
  }
  if (event.kind !== "user_message") {
    return false;
  }
  const metadata = event.payload.metadata;
  return isRecord(metadata) && metadata.live_projection === "input_buffer";
}

function isActionMessageInputBuffer(buffer: PendingInputBuffer): boolean {
  return buffer.metadata.action === "true";
}

function hasModelPendingInputBuffers(buffers: PendingInputBuffer[]): boolean {
  return buffers.some((buffer) => !isActionMessageInputBuffer(buffer));
}

function pendingInputBufferWaitsForModel(event: ChatEventResponse): boolean {
  return event.kind !== "action_message";
}

function pendingBufferMatchesEvent(
  buffer: PendingInputBuffer,
  event: ChatEventResponse,
): boolean {
  const externalId = event.external_id ?? null;
  const externalRoot = externalId?.split(":", 1)[0] ?? null;
  return (
    buffer.id === event.id ||
    buffer.id === externalId ||
    buffer.id === externalRoot
  );
}

function shouldRemovePendingBufferForEvent(event: ChatEventResponse): boolean {
  switch (event.kind) {
    case "user_message":
    case "action_message":
    case "goal_continuation":
    case "goal_updated":
    case "system_error":
      return true;
    default:
      return false;
  }
}

function removePendingBuffersForEvent(
  buffers: PendingInputBuffer[],
  event: ChatEventResponse,
): PendingInputBuffer[] {
  if (!shouldRemovePendingBufferForEvent(event)) {
    return buffers;
  }
  return buffers.filter((buffer) => !pendingBufferMatchesEvent(buffer, event));
}

function upsertActionExecutionProjection(
  actionExecutions: ActionExecutionProjection[],
  actionExecution: ActionExecutionProjection,
): ActionExecutionProjection[] {
  const index = actionExecutions.findIndex(
    (item) => item.execution.id === actionExecution.execution.id,
  );
  if (index === -1) {
    return [...actionExecutions, actionExecution];
  }
  if (
    actionExecutions[index]?.provenance === "durable" &&
    actionExecution.provenance !== "durable"
  ) {
    return actionExecutions;
  }
  return actionExecutions.map((item, itemIndex) =>
    itemIndex === index ? actionExecution : item,
  );
}

function isActionExecutionProjectionValue(
  value: unknown,
): value is ActionExecutionProjectionResponse {
  if (!isRecord(value) || !isRecord(value.execution)) {
    return false;
  }
  return (
    typeof value.execution.id === "string" &&
    typeof value.execution.input_buffer_id === "string" &&
    typeof value.execution.status === "string" &&
    Array.isArray(value.events)
  );
}

function actionExecutionResultFromEvent(
  event: ChatEventResponse,
): ActionExecutionProjection | null {
  if (event.kind !== "action_execution_result" || !isRecord(event.payload)) {
    return null;
  }
  return isActionExecutionProjectionValue(event.payload.action_execution)
    ? { ...event.payload.action_execution, provenance: "durable" }
    : null;
}

function isCompletedGitWorktreeActionExecution(
  actionExecution: ActionExecutionProjection,
): boolean {
  return (
    actionExecution.execution.action_type === "create_git_worktree" &&
    actionExecution.execution.status === "completed"
  );
}

function actionExecutionResultsFromEvents(
  events: ChatEventResponse[],
): ActionExecutionProjection[] {
  return events.reduce<ActionExecutionProjection[]>((items, event) => {
    const actionExecution = actionExecutionResultFromEvent(event);
    return actionExecution === null
      ? items
      : upsertActionExecutionProjection(items, actionExecution);
  }, []);
}

function mergeActionExecutionProjections(
  durable: ActionExecutionProjection[],
  live: ActionExecutionProjection[],
): ActionExecutionProjection[] {
  return live.reduce(upsertActionExecutionProjection, durable);
}

function mapInputBufferLiveEvent(
  event: ChatEventResponse,
): PendingInputBuffer | null {
  if (!isInputBufferLiveEvent(event)) {
    return null;
  }
  if (event.kind === "action_message") {
    return {
      id: event.id,
      sessionId: event.session_id,
      content: stringField(event.payload, "message") ?? "",
      action: chatActionFromValue(event.payload.action),
      attachments: [],
      attachmentFiles: [],
      metadata: { action: "true" },
      createdAt: event.created_at,
      status: "pending",
      requestedInferenceProfile: eventRequestedInferenceProfile(event),
    };
  }
  const metadata = event.payload.metadata;
  if (!isRecord(metadata)) {
    return null;
  }
  const inputBufferId = stringField(metadata, "input_buffer_id") ?? event.id;
  return {
    id: inputBufferId,
    sessionId: event.session_id,
    content: contentText(event.payload.content),
    action: null,
    attachments: eventAttachments(event.payload).map(
      (attachment) => attachment.uri,
    ),
    attachmentFiles: [
      ...eventAttachments(event.payload),
      ...contentAttachments(event.payload.content),
    ],
    metadata: Object.fromEntries(
      Object.entries(metadata).flatMap(([key, value]) =>
        typeof value === "string" ? [[key, value]] : [],
      ),
    ),
    createdAt: event.created_at,
    status: "pending",
    requestedInferenceProfile: eventRequestedInferenceProfile(event),
  };
}

interface PartialHistoryState {
  order: string[];
  itemsByKey: Record<string, ChatEventResponse>;
}

interface ManagedLiveState {
  partialHistory: PartialHistoryState;
  pendingInputBuffers: PendingInputBuffer[];
  liveRun: ChatLiveRunState | null;
  liveRunPhase: AgentRunPhase | null;
  sessionRunState: SessionRunState;
  isResponsePending: boolean;
  isModelResponsePending: boolean;
  isCompacting: boolean;
  isStopPending: boolean;
  todo: TodoStateSnapshot;
  goal: GoalStateSnapshot;
  actionExecutions: ActionExecutionProjection[];
}

interface RestSnapshotRequest {
  epoch: number;
  liveObservationGeneration: number;
}

type ResyncReason = "initial" | "periodic" | "resume" | "latest" | "compaction";

interface ResyncOptions {
  reason: ResyncReason;
  continuing?: boolean;
}

interface LiveTaxonomySnapshot {
  partial_history: { items: ChatEventResponse[] };
  input_buffers: ChatEventResponse[];
  run?: LiveEventListResponse["run"];
  session_run_state: LiveEventListResponse["session_run_state"];
  todo?: TodoStateSnapshot | null;
  goal?: Partial<GoalStateSnapshot> | null;
  action_executions?: ActionExecutionProjectionResponse[] | null;
}

function emptyPartialHistoryState(): PartialHistoryState {
  return { order: [], itemsByKey: {} };
}

function emptyTodoState(): TodoStateSnapshot {
  return { items: [] };
}

function emptyGoalState(): GoalStateSnapshot {
  return { objective: null, status: null };
}

function normalizeGoalState(
  goal?: Partial<GoalStateSnapshot> | null,
): GoalStateSnapshot {
  return {
    objective: goal?.objective ?? null,
    status: goal?.status ?? null,
    created_at: goal?.created_at ?? null,
    updated_at: goal?.updated_at ?? null,
  };
}

function emptyManagedLiveState(): ManagedLiveState {
  return {
    partialHistory: emptyPartialHistoryState(),
    pendingInputBuffers: [],
    liveRun: null,
    liveRunPhase: null,
    sessionRunState: "idle",
    isResponsePending: false,
    isModelResponsePending: false,
    isCompacting: false,
    isStopPending: false,
    todo: emptyTodoState(),
    goal: emptyGoalState(),
    actionExecutions: [],
  };
}

function partialHistorySemanticKey(event: ChatEventResponse): string {
  return eventRenderKey(event);
}

function isPartialHistoryEvent(event: ChatEventResponse): boolean {
  if (isInputBufferLiveEvent(event)) {
    return false;
  }
  switch (event.kind) {
    case "assistant_message":
    case "reasoning":
    case "client_tool_call":
    case "provider_tool_call":
    case "provider_tool_result":
    case "agent_message":
    case "goal_continuation":
    case "interrupted":
      return true;
    default:
      return false;
  }
}

function upsertPartialHistoryEvent(
  partialHistory: PartialHistoryState,
  event: ChatEventResponse,
): PartialHistoryState {
  const key = partialHistorySemanticKey(event);
  const exists = Object.prototype.hasOwnProperty.call(
    partialHistory.itemsByKey,
    key,
  );
  return {
    order: exists ? partialHistory.order : [...partialHistory.order, key],
    itemsByKey: { ...partialHistory.itemsByKey, [key]: event },
  };
}

function removePartialHistoryById(
  partialHistory: PartialHistoryState,
  eventId: string,
): PartialHistoryState {
  const order = partialHistory.order.filter((key) => {
    const event = partialHistory.itemsByKey[key];
    return typeof event !== "undefined" && event.id !== eventId;
  });
  const itemsByKey = Object.fromEntries(
    order.flatMap((key) => {
      const event = partialHistory.itemsByKey[key];
      return typeof event === "undefined" ? [] : [[key, event]];
    }),
  );
  return { order, itemsByKey };
}

function eventExternalRoot(event: ChatEventResponse): string | null {
  return event.external_id?.split(":", 1)[0] ?? null;
}

function partialHistoryEventMatchesDurableEvent(
  partialEvent: ChatEventResponse,
  durableEvent: ChatEventResponse,
): boolean {
  const partialKey = partialHistorySemanticKey(partialEvent);
  const durableKey = partialHistorySemanticKey(durableEvent);
  if (partialKey === durableKey) {
    return true;
  }
  const durableExternalId = durableEvent.external_id ?? null;
  const durableExternalRoot = eventExternalRoot(durableEvent);
  return (
    partialEvent.id === durableEvent.id ||
    partialEvent.id === durableExternalId ||
    partialEvent.id === durableExternalRoot
  );
}

function removePartialHistoryCounterpart(
  partialHistory: PartialHistoryState,
  durableEvent: ChatEventResponse,
): PartialHistoryState {
  const order = partialHistory.order.filter((key) => {
    const event = partialHistory.itemsByKey[key];
    return (
      typeof event !== "undefined" &&
      !partialHistoryEventMatchesDurableEvent(event, durableEvent)
    );
  });
  if (order.length === partialHistory.order.length) {
    return partialHistory;
  }
  const itemsByKey = Object.fromEntries(
    order.flatMap((item) => {
      const event = partialHistory.itemsByKey[item];
      return typeof event === "undefined" ? [] : [[item, event]];
    }),
  );
  return { order, itemsByKey };
}

function orderedPartialHistoryEvents(
  partialHistory: PartialHistoryState,
): ChatEventResponse[] {
  return partialHistory.order.flatMap((key) => {
    const event = partialHistory.itemsByKey[key];
    return event ? [event] : [];
  });
}

interface InvalidLiveRunSnapshot {
  value: unknown;
}

interface MappedLiveStateSnapshot {
  state: ManagedLiveState;
  invalidLiveRun: InvalidLiveRunSnapshot | null;
}

function replaceLiveStateFromSnapshot(
  live: LiveTaxonomySnapshot,
  previous: ManagedLiveState | null,
): MappedLiveStateSnapshot {
  const partialHistory = live.partial_history.items.reduce(
    upsertPartialHistoryEvent,
    emptyPartialHistoryState(),
  );
  const goalContinuationInputEvents = live.input_buffers.filter(
    (event) => event.kind === "goal_continuation",
  );
  const partialHistoryWithGoalContinuations =
    goalContinuationInputEvents.reduce(
      upsertPartialHistoryEvent,
      partialHistory,
    );
  const pendingInputBuffers = live.input_buffers.flatMap((event) => {
    const buffer = mapInputBufferLiveEvent(event);
    return buffer === null ? [] : [buffer];
  });
  const runSnapshot = liveRunSnapshotFromResponse(live);
  const liveRun =
    runSnapshot.type === "PRESENT"
      ? runSnapshot.run
      : runSnapshot.type === "INVALID"
        ? (previous?.liveRun ?? null)
        : null;
  const currentLiveRunPhase = liveRunPhase(liveRun);
  return {
    state: {
      ...emptyManagedLiveState(),
      partialHistory: partialHistoryWithGoalContinuations,
      pendingInputBuffers,
      liveRun,
      liveRunPhase: currentLiveRunPhase,
      sessionRunState:
        liveRun?.status === "running"
          ? "running"
          : sessionRunStateFromResponse(live),
      isResponsePending:
        isUserBlockingRunPhase(currentLiveRunPhase) ||
        partialHistory.order.length > 0,
      isModelResponsePending: isModelRunPhase(currentLiveRunPhase),
      isCompacting: currentLiveRunPhase === "compacting",
      isStopPending:
        runSnapshot.type === "INVALID"
          ? (previous?.isStopPending ?? false)
          : false,
      todo: live.todo ?? emptyTodoState(),
      goal: normalizeGoalState(live.goal),
      actionExecutions: (live.action_executions ?? []).map((projection) => ({
        ...projection,
        provenance: "live",
      })),
    },
    invalidLiveRun:
      runSnapshot.type === "INVALID" ? { value: runSnapshot.value } : null,
  };
}

function messageMetadataKey(message: ChatMessage): string | null {
  return message.metadata?.event_render_key ?? null;
}

function getMessageMergeKeys(message: ChatMessage): string[] {
  const metadataKey = messageMetadataKey(message);
  return [
    `id:${message.id}`,
    ...(metadataKey === null ? [] : [`semantic:${metadataKey}`]),
    ...getToolCallKeys(message).map((key) => `tool:${key}`),
    ...getProviderToolCallKeys(message).map((key) => `provider-tool:${key}`),
  ];
}

function upsertMessageByMergeKey(
  existing: ChatMessage[],
  message: ChatMessage,
): ChatMessage[] {
  const messageKeys = new Set(getMessageMergeKeys(message));
  const index = existing.findIndex((item) =>
    getMessageMergeKeys(item).some((key) => messageKeys.has(key)),
  );
  if (index < 0) {
    return [...existing, message];
  }
  return existing.map((item, itemIndex) =>
    itemIndex === index ? message : item,
  );
}

function mapSessionEvents(
  data: {
    history: {
      items: ChatEventResponse[];
      has_more: boolean;
      has_newer?: boolean;
      next_cursor?: string | null;
      previous_cursor?: string | null;
    };
    live: LiveEventListResponse;
  },
  previousLiveState: ManagedLiveState | null,
): {
  historyEvents: ChatEventResponse[];
  liveState: ManagedLiveState;
  invalidLiveRun: InvalidLiveRunSnapshot | null;
  hasMore: boolean;
  hasNewer: boolean;
  oldestCursor: string | null;
  newestCursor: string | null;
  latestDurableInferenceIntent: DurableInferenceIntent | null;
} {
  const mappedLive = replaceLiveStateFromSnapshot(data.live, previousLiveState);
  return {
    historyEvents: data.history.items,
    liveState: mappedLive.state,
    invalidLiveRun: mappedLive.invalidLiveRun,
    hasMore: data.history.has_more,
    hasNewer: data.history.has_newer ?? false,
    oldestCursor: data.history.next_cursor ?? null,
    newestCursor: data.history.previous_cursor ?? null,
    latestDurableInferenceIntent: latestDurableInferenceIntent([
      ...data.history.items,
      ...data.live.partial_history.items,
      ...data.live.input_buffers,
    ]),
  };
}

function mapChatWriteSnapshot(
  response: ChatWriteResponse,
  previousLiveState: ManagedLiveState,
): MappedLiveStateSnapshot {
  return replaceLiveStateFromSnapshot(
    {
      partial_history: { items: response.snapshot.partial_history_events },
      input_buffers: response.snapshot.input_buffer_events,
      run: response.snapshot.run,
      session_run_state: response.snapshot.session_run_state,
      todo: response.snapshot.todo,
      goal: normalizeGoalState(response.snapshot.goal),
      action_executions: response.snapshot.action_executions,
    },
    previousLiveState,
  );
}

function getToolCallKeys(message: ChatMessage): string[] {
  return (
    message.toolCalls?.flatMap((toolCall) =>
      [toolCall.callId, toolCall.id].filter(
        (value): value is string => typeof value === "string",
      ),
    ) ?? []
  );
}

function getProviderToolCallKeys(message: ChatMessage): string[] {
  return (
    message.providerToolCalls?.flatMap((toolCall) =>
      [toolCall.callId, toolCall.id].filter(
        (value): value is string => typeof value === "string",
      ),
    ) ?? []
  );
}

function isCompactionActiveInHistory(messages: ChatMessage[]): boolean {
  for (const message of [...messages].reverse()) {
    if (message.role === "compaction") {
      return false;
    }
    if (message.role === "compaction_started") {
      return message.metadata?.status !== "failed";
    }
  }
  return false;
}

function upsertMessage(
  existing: ChatMessage[],
  message: ChatMessage,
): ChatMessage[] {
  const index = existing.findIndex((item) => item.id === message.id);
  if (index < 0) {
    return [...existing, message];
  }
  return existing.map((item, itemIndex) =>
    itemIndex === index ? message : item,
  );
}

function upsertHistoryEvent(
  events: ChatEventResponse[],
  event: ChatEventResponse,
): ChatEventResponse[] {
  const index = events.findIndex((item) => item.id === event.id);
  if (index < 0) {
    return [...events, event];
  }
  return events.map((item, itemIndex) => (itemIndex === index ? event : item));
}

function mergeHistoryEventPages(
  existing: ChatEventResponse[],
  incoming: ChatEventResponse[],
  direction: "prepend" | "append",
): ChatEventResponse[] {
  const incomingIds = new Set(incoming.map((event) => event.id));
  const retained = existing.filter((event) => !incomingIds.has(event.id));
  return direction === "prepend"
    ? [...incoming, ...retained]
    : [...retained, ...incoming];
}

function renderableTimelineMessageCount(events: ChatEventResponse[]): number {
  return mapEvents(events, { renderIncompleteToolCalls: false }).filter(
    (message) =>
      message.role !== "turn_complete" &&
      message.role !== "run_complete" &&
      message.role !== "compaction_started",
  ).length;
}

function pageAdvancesVisibleTimeline(
  existing: ChatEventResponse[],
  incoming: ChatEventResponse[],
  direction: "prepend" | "append",
): boolean {
  if (actionExecutionResultsFromEvents(incoming).length > 0) {
    return true;
  }
  const merged = mergeHistoryEventPages(existing, incoming, direction);
  return (
    renderableTimelineMessageCount(merged) >
    renderableTimelineMessageCount(existing)
  );
}

function mergeLatestHistoryEvents(
  existing: ChatEventResponse[],
  serverLatest: ChatEventResponse[],
): ChatEventResponse[] {
  const cutoff = serverLatest[0];
  if (typeof cutoff === "undefined") {
    return existing;
  }
  const serverIds = new Set(serverLatest.map((event) => event.id));
  const olderPages = existing.filter(
    (event) => event.id < cutoff.id && !serverIds.has(event.id),
  );
  return [...olderPages, ...serverLatest];
}

export function useChatSessionContainer(
  props: ChatSessionContainerProps,
): ChatSessionContainerOutput {
  const { sessionId, agent, onConnectionStatusChange } = props;
  const agentSessionQuery = trpc.chat.getAgentSession.useQuery({
    agentId: agent.id,
    sessionId,
  });
  const agentDefaultInferenceProfile = useMemo<RequestedInferenceProfile>(
    () => ({
      model_target_label: agent.main_model_label,
      reasoning_effort: agent.model_parameters?.reasoning_effort ?? null,
    }),
    [agent.main_model_label, agent.model_parameters?.reasoning_effort],
  );
  const sessionCurrentInferenceProfile =
    useMemo((): RequestedInferenceProfile | null => {
      const session = agentSessionQuery.data;
      if (session?.current_model_target_label == null) {
        return null;
      }
      return {
        model_target_label: session.current_model_target_label,
        reasoning_effort: session.current_reasoning_effort,
      };
    }, [agentSessionQuery.data]);

  const [chatViewState, setChatViewState] = useState<ChatViewState>({
    type: "LOADING_HISTORY",
  });
  const [chatTimelineState, setChatTimelineState] = useState<ChatTimelineState>(
    { type: "LATEST_FOLLOWING" },
  );
  const chatTimelineStateRef = useRef(chatTimelineState);
  chatTimelineStateRef.current = chatTimelineState;
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const loadMoreInFlightRef = useRef(false);
  const [isLoadingNewer, setIsLoadingNewer] = useState(false);
  const [authorizationRequests, setAuthorizationRequests] = useState<
    AuthorizationRequest[]
  >([]);
  const [isWritePending, setIsWritePending] = useState(false);
  const [wasRestCommandBlocked, setWasRestCommandBlocked] = useState(false);
  const [historyEvents, setHistoryEvents] = useState<ChatEventResponse[]>([]);
  const historyEventsRef = useRef(historyEvents);
  historyEventsRef.current = historyEvents;
  const [transientMessages, setTransientMessages] = useState<ChatMessage[]>([]);
  const [latestHumanInferenceProfile, setLatestHumanInferenceProfile] =
    useState<RequestedInferenceProfile | null>(null);
  const [managedLiveState, setManagedLiveState] = useState<ManagedLiveState>(
    () => emptyManagedLiveState(),
  );
  const [isSubscribeReady, setIsSubscribeReady] = useState(false);
  const historyOldestCursorRef = useRef<string | null>(null);
  const historyNewestCursorRef = useRef<string | null>(null);
  const latestHumanModelOrderRef = useRef<number | null>(null);
  const writeInFlightRef = useRef(false);
  const failedWriteRequestRef = useRef<{ key: string; id: string } | null>(
    null,
  );
  const liveObservationGenerationRef = useRef(0);
  const restSnapshotEpochRef = useRef(0);
  const hasFreshBaselineRef = useRef(false);
  const startResyncRef = useRef<(options: ResyncOptions) => boolean>(
    () => false,
  );
  const startRestSnapshotRequest = useCallback((): RestSnapshotRequest => {
    restSnapshotEpochRef.current += 1;
    return {
      epoch: restSnapshotEpochRef.current,
      liveObservationGeneration: liveObservationGenerationRef.current,
    };
  }, []);
  const captureRestSnapshotRequest = useCallback(
    (): RestSnapshotRequest => ({
      epoch: restSnapshotEpochRef.current,
      liveObservationGeneration: liveObservationGenerationRef.current,
    }),
    [],
  );
  const canApplyRestSnapshot = useCallback(
    (request: RestSnapshotRequest): boolean =>
      request.epoch === restSnapshotEpochRef.current &&
      request.liveObservationGeneration ===
        liveObservationGenerationRef.current,
    [],
  );
  const reportInvalidLiveRun = useCallback(
    (value: unknown): void => {
      Sentry.captureMessage("Invalid chat live Run projection", {
        level: "warning",
        tags: { session_id: sessionId },
        extra: { run: value },
      });
    },
    [sessionId],
  );
  const durableHistoryMessages = useMemo(
    () =>
      mapEvents(historyEvents, {
        renderIncompleteToolCalls: false,
      }),
    [historyEvents],
  );
  const messages = useMemo(() => {
    const durableAndTransient = [
      ...durableHistoryMessages,
      ...transientMessages,
    ];
    if (chatTimelineState.type === "DETACHED_HISTORY_BROWSING") {
      return durableAndTransient;
    }
    const visiblePartialEvents = orderedPartialHistoryEvents(
      managedLiveState.partialHistory,
    ).filter(
      (partialEvent) =>
        !historyEvents.some((durableEvent) =>
          partialHistoryEventMatchesDurableEvent(partialEvent, durableEvent),
        ),
    );
    return mapEvents(visiblePartialEvents, {
      initialMessages: durableAndTransient,
      renderIncompleteToolCalls: true,
      messageStatus: "partial",
    });
  }, [
    chatTimelineState.type,
    durableHistoryMessages,
    historyEvents,
    managedLiveState.partialHistory,
    transientMessages,
  ]);
  const actionExecutions = useMemo(
    () =>
      mergeActionExecutionProjections(
        actionExecutionResultsFromEvents(historyEvents),
        managedLiveState.actionExecutions,
      ),
    [historyEvents, managedLiveState.actionExecutions],
  );
  const defaultInferenceProfile =
    latestHumanInferenceProfile ??
    sessionCurrentInferenceProfile ??
    agentDefaultInferenceProfile;
  const pendingInputBuffers = managedLiveState.pendingInputBuffers;
  const liveRun = managedLiveState.liveRun;
  const isResponsePending = managedLiveState.isResponsePending;
  const isModelResponsePending = managedLiveState.isModelResponsePending;
  const sessionRunState = managedLiveState.sessionRunState;

  // WebSocket connection text (ticket + wsUrl)
  const connectionInfoQuery = trpc.chat.getConnectionInfo.useQuery();
  const inputActionsQuery = trpc.chat.listInputActions.useQuery(
    { sessionId },
    { enabled: isSubscribeReady },
  );

  const utils = trpc.useUtils();

  useEffect(() => {
    void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
  }, [agent.id, sessionRunState, utils.chat.listAgentSessions]);

  const batchReloadRef = useRef<(reason: "periodic" | "resume") => boolean>(
    () => false,
  );
  const compactionReloadRef = useRef<(continuing: boolean) => void>(() => {});

  const handleChatEvent = useCallback(
    (event: ChatEvent): void => {
      liveObservationGenerationRef.current += 1;
      if (
        chatTimelineStateRef.current.type === "DETACHED_HISTORY_BROWSING" &&
        "type" in event
      ) {
        if (event.type === "history_event_appended") {
          setChatTimelineState((prev) =>
            prev.type === "DETACHED_HISTORY_BROWSING"
              ? { ...prev, hasNewer: true }
              : prev,
          );
          return;
        }
        if (
          event.type === "live_event_upserted" ||
          event.type === "live_event_removed" ||
          event.type === "live_run_updated" ||
          event.type === "live_run_cleared" ||
          event.type === "action_execution_updated" ||
          event.type === "run_started" ||
          event.type === "run_phase_changed" ||
          event.type === "run_complete" ||
          event.type === "run_stopped" ||
          event.type === "runtime_error" ||
          event.type === "compaction_started" ||
          event.type === "compaction_complete"
        ) {
          return;
        }
      }
      const markRunActive = (phase: AgentRunPhase | null): void => {
        setManagedLiveState((prev) => ({
          ...prev,
          liveRun:
            prev.liveRun === null || phase === null
              ? prev.liveRun
              : { ...prev.liveRun, phase, status: "running" },
          liveRunPhase: phase,
          sessionRunState: "running",
          isResponsePending:
            isUserBlockingRunPhase(phase) ||
            prev.partialHistory.order.length > 0,
          isModelResponsePending: isModelRunPhase(phase),
          isCompacting: phase === "compacting",
        }));
      };
      const markModelOutputVisible = (): void => {
        setManagedLiveState((prev) => ({
          ...prev,
          isModelResponsePending: false,
        }));
      };
      const markRunInactive = (runId: string): void => {
        setManagedLiveState((prev) => {
          if (prev.liveRun?.run_id !== runId) {
            return prev;
          }
          return {
            ...prev,
            liveRun: null,
            liveRunPhase: null,
            sessionRunState: "idle",
            isResponsePending: false,
            isModelResponsePending: false,
            isCompacting: false,
            isStopPending: false,
          };
        });
      };

      if ("type" in event && event.type === "todo_state_changed") {
        setManagedLiveState((prev) => ({
          ...prev,
          todo: event.todo,
        }));
        return;
      }

      if ("type" in event && event.type === "input_actions_updated") {
        void utils.chat.listInputActions.invalidate({ sessionId });
        return;
      }

      if ("type" in event && event.type === "subagent_tree_changed") {
        void utils.chat.getSubagentTree.invalidate();
        return;
      }

      if ("type" in event && event.type === "action_execution_updated") {
        const actionExecution: ActionExecutionProjection = {
          ...event.action_execution,
          provenance: "live",
        };
        setManagedLiveState((prev) => ({
          ...prev,
          actionExecutions: upsertActionExecutionProjection(
            prev.actionExecutions,
            actionExecution,
          ),
        }));
        if (isCompletedGitWorktreeActionExecution(actionExecution)) {
          void Promise.all([
            utils.chat.listAgentProjects.invalidate({
              agentId: agent.id,
              sessionId,
            }),
            utils.chat.getSessionProjectBrowserManifest.invalidate({
              agentId: agent.id,
              sessionId,
            }),
            utils.chat.listInputActions.invalidate({ sessionId }),
          ]);
        }
        return;
      }

      if ("type" in event && event.type === "live_event_removed") {
        setManagedLiveState((prev) => ({
          ...prev,
          partialHistory: removePartialHistoryById(
            prev.partialHistory,
            event.event_id,
          ),
          pendingInputBuffers: prev.pendingInputBuffers.filter(
            (buffer) => buffer.id !== event.event_id,
          ),
        }));
        return;
      }

      if ("type" in event && event.type === "live_run_updated") {
        const nextLiveRun = chatLiveRunStateFromValue(event.run);
        if (nextLiveRun === null) {
          reportInvalidLiveRun(event.run);
          return;
        }
        const nextLiveRunPhase = liveRunPhase(nextLiveRun);
        setManagedLiveState((prev) => ({
          ...prev,
          liveRun: nextLiveRun,
          liveRunPhase: nextLiveRunPhase,
          sessionRunState:
            nextLiveRun.status === "running" ? "running" : prev.sessionRunState,
          isResponsePending:
            isUserBlockingRunPhase(nextLiveRunPhase) ||
            prev.partialHistory.order.length > 0,
          isModelResponsePending: isModelRunPhase(nextLiveRunPhase),
          isCompacting: nextLiveRunPhase === "compacting",
        }));
        return;
      }

      if ("type" in event && event.type === "live_run_cleared") {
        markRunInactive(event.run_id);
        return;
      }

      if ("type" in event && event.type === "live_event_upserted") {
        const responseEvent = event.event;
        const pending = mapInputBufferLiveEvent(responseEvent);
        if (pending !== null) {
          const pendingInferenceIntent = latestDurableInferenceIntent([
            responseEvent,
          ]);
          if (
            pendingInferenceIntent !== null &&
            (latestHumanModelOrderRef.current === null ||
              pendingInferenceIntent.modelOrder >=
                latestHumanModelOrderRef.current)
          ) {
            latestHumanModelOrderRef.current =
              pendingInferenceIntent.modelOrder;
            setLatestHumanInferenceProfile(pendingInferenceIntent.profile);
          }
          setManagedLiveState((prev) => ({
            ...prev,
            pendingInputBuffers: [
              ...prev.pendingInputBuffers.filter(
                (buffer) => buffer.id !== pending.id,
              ),
              pending,
            ],
            isResponsePending:
              prev.isResponsePending ||
              pendingInputBufferWaitsForModel(responseEvent),
          }));
          if (pending.sessionId !== sessionId) {
            void connectionInfoQuery.refetch();
          }
          return;
        }
        if (isPartialHistoryEvent(responseEvent)) {
          markModelOutputVisible();
          setManagedLiveState((prev) => ({
            ...prev,
            partialHistory: upsertPartialHistoryEvent(
              prev.partialHistory,
              responseEvent,
            ),
            isResponsePending: true,
          }));
        }
        return;
      }

      if ("type" in event && event.type === "history_event_appended") {
        const responseEvent = event.event;
        const appendedInferenceIntent = latestDurableInferenceIntent([
          responseEvent,
        ]);
        if (
          appendedInferenceIntent !== null &&
          (latestHumanModelOrderRef.current === null ||
            appendedInferenceIntent.modelOrder >=
              latestHumanModelOrderRef.current)
        ) {
          latestHumanModelOrderRef.current = appendedInferenceIntent.modelOrder;
          setLatestHumanInferenceProfile(appendedInferenceIntent.profile);
        }
        setHistoryEvents((prev) => {
          const next = upsertHistoryEvent(prev, responseEvent);
          historyEventsRef.current = next;
          return next;
        });
        setManagedLiveState((prev) => ({
          ...prev,
          partialHistory: removePartialHistoryCounterpart(
            prev.partialHistory,
            responseEvent,
          ),
          pendingInputBuffers: removePendingBuffersForEvent(
            prev.pendingInputBuffers,
            responseEvent,
          ),
        }));
        if (responseEvent.kind === "run_marker") {
          const markerRunId = stringField(responseEvent.payload, "run_id");
          if (markerRunId !== null) {
            markRunInactive(markerRunId);
          }
        } else if (
          responseEvent.kind === "assistant_message" ||
          responseEvent.kind === "reasoning" ||
          responseEvent.kind === "client_tool_call" ||
          responseEvent.kind === "provider_tool_call"
        ) {
          markModelOutputVisible();
        }
        return;
      }

      if (!("type" in event)) {
        return;
      }

      switch (event.type) {
        case "run_started":
          markRunActive(event.phase ?? null);
          void utils.chat.getSubagentTree.invalidate();
          break;
        case "run_phase_changed":
          markRunActive(event.phase);
          break;
        case "run_complete":
          if ("item" in event) {
            setTransientMessages((prev) =>
              upsertMessage(prev, {
                id: event.id,
                role: "run_complete",
                content: null,
                createdAt: new Date().toISOString(),
                status: "complete",
              }),
            );
          } else {
            markRunInactive(event.run_id);
            void utils.chat.getSubagentTree.invalidate();
          }
          break;
        case "run_stopped":
          markRunInactive(event.run_id);
          void utils.chat.getSubagentTree.invalidate();
          break;
        case "runtime_error":
          setTransientMessages((prev) => [
            ...prev,
            {
              id: `runtime-error-${Date.now()}`,
              role: "error",
              content: event.message,
              createdAt: new Date().toISOString(),
              status: "complete",
            },
          ]);
          break;
        case "authorization_request":
          setAuthorizationRequests((prev) =>
            prev.some((req) => req.toolkitId === event.toolkit_id)
              ? prev
              : [
                  ...prev,
                  {
                    toolkitId: event.toolkit_id,
                    toolkitName: event.toolkit_name,
                    authorizationUrl: "",
                  },
                ],
          );
          break;
        case "compaction_started":
          setManagedLiveState((prev) => ({ ...prev, isCompacting: true }));
          break;
        case "compaction_complete":
          setManagedLiveState((prev) => ({
            ...prev,
            isCompacting: false,
            ...(event.continuing
              ? {}
              : {
                  isResponsePending: false,
                  isModelResponsePending: false,
                  isStopPending: false,
                }),
          }));
          compactionReloadRef.current(event.continuing === true);
          break;
      }
    },
    [
      agent.id,
      connectionInfoQuery,
      reportInvalidLiveRun,
      sessionId,
      utils.chat.getSessionProjectBrowserManifest,
      utils.chat.getSubagentTree,
      utils.chat.listAgentProjects,
      utils.chat.listInputActions,
    ],
  );

  const {
    connectionStatus,
    setBufferingLiveEvents,
    replayBufferedLiveEvents,
    requestSubscriptionHealthCheck,
    requestReconnect,
  } = useChatWebSocket({
    wsUrl: connectionInfoQuery.data?.wsUrl ?? null,
    ticket: connectionInfoQuery.data?.ticket ?? null,
    sessionId,
    onEvent: handleChatEvent,
    onBatchReload: (reason) => batchReloadRef.current(reason),
    onSubscribed: () => {
      setIsSubscribeReady(true);
      const reason = hasFreshBaselineRef.current ? "resume" : "initial";
      if (reason === "initial") {
        setChatViewState({ type: "LOADING_HISTORY" });
      }
      startResyncRef.current({ reason });
    },
    onAuthError: () => void connectionInfoQuery.refetch(),
  });

  const startResync = useCallback(
    (options: ResyncOptions): boolean => {
      if (
        options.reason !== "initial" &&
        options.reason !== "latest" &&
        chatViewState.type !== "READY"
      ) {
        return false;
      }

      setBufferingLiveEvents(true);
      const request = startRestSnapshotRequest();
      void (async (): Promise<void> => {
        let healthy = false;
        try {
          healthy = await requestSubscriptionHealthCheck();
        } catch {
          healthy = false;
        }
        if (request.epoch !== restSnapshotEpochRef.current) {
          return;
        }
        if (!healthy) {
          replayBufferedLiveEvents();
          if (options.reason === "initial") {
            setChatViewState({ type: "READY" });
          }
          requestReconnect();
          return;
        }

        let result;
        try {
          result = await utils.client.chat.listSessionEvents.query({
            sessionId,
          });
        } catch {
          if (request.epoch === restSnapshotEpochRef.current) {
            replayBufferedLiveEvents();
            if (options.reason === "initial") {
              setChatViewState({ type: "READY" });
            }
          }
          return;
        }
        if (!canApplyRestSnapshot(request)) {
          if (request.epoch === restSnapshotEpochRef.current) {
            replayBufferedLiveEvents();
          }
          return;
        }

        const mapped = mapSessionEvents(result, null);
        hasFreshBaselineRef.current = true;
        const detached = chatTimelineStateRef.current;
        const preserveDetached =
          detached.type === "DETACHED_HISTORY_BROWSING" &&
          options.reason !== "initial" &&
          options.reason !== "latest";
        if (preserveDetached) {
          setChatTimelineState({
            ...detached,
            hasNewer:
              detached.hasNewer ||
              (mapped.newestCursor !== null &&
                mapped.newestCursor !== detached.newestCursor),
          });
        } else {
          historyOldestCursorRef.current = mapped.oldestCursor;
          historyNewestCursorRef.current = mapped.newestCursor;
          setHistoryEvents((prev) => {
            const next =
              options.reason === "initial"
                ? mapped.historyEvents
                : mergeLatestHistoryEvents(prev, mapped.historyEvents);
            historyEventsRef.current = next;
            return next;
          });
          latestHumanModelOrderRef.current =
            mapped.latestDurableInferenceIntent?.modelOrder ?? null;
          setLatestHumanInferenceProfile(
            mapped.latestDurableInferenceIntent?.profile ?? null,
          );
          setManagedLiveState((prev) => {
            const next = mapSessionEvents(result, prev);
            if (next.invalidLiveRun !== null) {
              reportInvalidLiveRun(next.invalidLiveRun.value);
            }
            return {
              ...next.liveState,
              isResponsePending:
                options.reason === "compaction" && options.continuing === true
                  ? next.liveState.isResponsePending || prev.isResponsePending
                  : next.liveState.isResponsePending,
            };
          });
          setHasMore(mapped.hasMore);
          setChatTimelineState({ type: "LATEST_FOLLOWING" });
        }
        setChatViewState({ type: "READY" });
        replayBufferedLiveEvents();
      })();
      return true;
    },
    [
      canApplyRestSnapshot,
      chatViewState.type,
      replayBufferedLiveEvents,
      reportInvalidLiveRun,
      requestReconnect,
      requestSubscriptionHealthCheck,
      sessionId,
      setBufferingLiveEvents,
      startRestSnapshotRequest,
      utils.client.chat.listSessionEvents,
    ],
  );
  startResyncRef.current = startResync;
  batchReloadRef.current = (reason) => startResync({ reason });

  useEffect(() => {
    if (connectionStatus !== "connected") {
      restSnapshotEpochRef.current += 1;
    }
  }, [connectionStatus]);

  const applyLatestSnapshot = useCallback(
    (targetSessionId: string): Promise<void> => {
      if (targetSessionId === sessionId) {
        startResync({ reason: "latest" });
      }
      return Promise.resolve();
    },
    [sessionId, startResync],
  );

  compactionReloadRef.current = (continuing) => {
    startResync({ reason: "compaction", continuing });
  };

  // connection status parent with push (sidebar badge so it can reflect)
  useEffect(() => {
    onConnectionStatusChange(connectionStatus);
  }, [connectionStatus, onConnectionStatusChange]);

  const onLoadMore = useCallback(
    (options?: { detachFromLatest?: boolean }): void => {
      if (loadMoreInFlightRef.current || !hasMore) {
        return;
      }

      const oldestCursor = historyOldestCursorRef.current;
      if (oldestCursor === null) {
        return;
      }

      loadMoreInFlightRef.current = true;
      setIsLoadingMore(true);
      void (async () => {
        let accumulatedEvents = historyEventsRef.current;
        let loadedEvents: ChatEventResponse[] = [];
        let cursor = oldestCursor;
        let more = true;
        let visibleTimelineAdvanced = false;

        while (more && !visibleTimelineAdvanced) {
          const result = await utils.chat.listSessionEvents.fetch({
            sessionId,
            before: cursor,
          });
          visibleTimelineAdvanced = pageAdvancesVisibleTimeline(
            accumulatedEvents,
            result.history.items,
            "prepend",
          );
          accumulatedEvents = mergeHistoryEventPages(
            accumulatedEvents,
            result.history.items,
            "prepend",
          );
          loadedEvents = mergeHistoryEventPages(
            loadedEvents,
            result.history.items,
            "prepend",
          );
          more = result.history.has_more;
          const nextCursor = result.history.next_cursor ?? null;
          if (nextCursor === null || nextCursor === cursor) {
            more = false;
            break;
          }
          cursor = nextCursor;
        }

        historyOldestCursorRef.current = cursor;
        setHistoryEvents((prev) => {
          const next = mergeHistoryEventPages(prev, loadedEvents, "prepend");
          historyEventsRef.current = next;
          return next;
        });
        setHasMore(more);
        if (
          options?.detachFromLatest !== false &&
          chatTimelineState.type === "LATEST_FOLLOWING"
        ) {
          setChatTimelineState({
            type: "DETACHED_HISTORY_BROWSING",
            hasNewer: false,
            newestCursor: historyNewestCursorRef.current,
          });
        }
      })().finally(() => {
        loadMoreInFlightRef.current = false;
        setIsLoadingMore(false);
      });
    },
    [chatTimelineState.type, sessionId, hasMore, utils.chat.listSessionEvents],
  );

  const onLoadNewer = useCallback((): void => {
    if (
      isLoadingNewer ||
      chatTimelineState.type !== "DETACHED_HISTORY_BROWSING" ||
      !chatTimelineState.hasNewer ||
      chatTimelineState.newestCursor === null
    ) {
      return;
    }

    const initialNewestCursor = chatTimelineState.newestCursor;
    setIsLoadingNewer(true);
    void (async () => {
      let accumulatedEvents = historyEventsRef.current;
      let loadedEvents: ChatEventResponse[] = [];
      let cursor = initialNewestCursor;
      let hasNewer = true;
      let hasOlder = hasMore;
      let visibleTimelineAdvanced = false;

      while (hasNewer && !visibleTimelineAdvanced) {
        const result = await utils.chat.listSessionEvents.fetch({
          sessionId,
          after: cursor,
        });
        visibleTimelineAdvanced = pageAdvancesVisibleTimeline(
          accumulatedEvents,
          result.history.items,
          "append",
        );
        accumulatedEvents = mergeHistoryEventPages(
          accumulatedEvents,
          result.history.items,
          "append",
        );
        loadedEvents = mergeHistoryEventPages(
          loadedEvents,
          result.history.items,
          "append",
        );
        hasOlder = result.history.has_more;
        hasNewer = result.history.has_newer ?? false;
        const nextCursor = result.history.previous_cursor ?? null;
        if (nextCursor === null || nextCursor === cursor) {
          break;
        }
        cursor = nextCursor;
      }

      historyNewestCursorRef.current = cursor;
      setHistoryEvents((prev) => {
        const next = mergeHistoryEventPages(prev, loadedEvents, "append");
        historyEventsRef.current = next;
        return next;
      });
      setHasMore(hasOlder);
      if (hasNewer) {
        setChatTimelineState({
          type: "DETACHED_HISTORY_BROWSING",
          hasNewer,
          newestCursor: cursor,
        });
        return;
      }
      void applyLatestSnapshot(sessionId);
    })().finally(() => {
      setIsLoadingNewer(false);
    });
  }, [
    applyLatestSnapshot,
    chatTimelineState,
    hasMore,
    isLoadingNewer,
    sessionId,
    utils.chat.listSessionEvents,
  ]);

  const onResetToLatest = useCallback((): void => {
    void applyLatestSnapshot(sessionId);
  }, [applyLatestSnapshot, sessionId]);

  const onAuthorizationComplete = useCallback((toolkitId: string) => {
    setAuthorizationRequests((prev) =>
      prev.filter((r) => r.toolkitId !== toolkitId),
    );
  }, []);

  const sendInputMutation = trpc.chat.sendInput.useMutation();
  const editMessageMutation = trpc.chat.editMessage.useMutation();
  const retryFailedRunMutation = trpc.chat.retryFailedRun.useMutation();
  const stopSessionRunMutation = trpc.chat.stopSessionRun.useMutation();
  const deleteInputBufferMutation = trpc.chat.deleteInputBuffer.useMutation();
  const updateSessionGoalMutation = trpc.chat.updateSessionGoal.useMutation();
  const updateSessionGoalStatusMutation =
    trpc.chat.updateSessionGoalStatus.useMutation();

  const applyWriteResponse = useCallback(
    (response: ChatWriteResponse, request: RestSnapshotRequest): void => {
      if (response.session_id !== sessionId) {
        throw new Error("Chat write response session mismatch");
      }
      if (canApplyRestSnapshot(request)) {
        const snapshotInferenceIntent = latestDurableInferenceIntent([
          ...response.snapshot.partial_history_events,
          ...response.snapshot.input_buffer_events,
        ]);
        if (
          snapshotInferenceIntent !== null &&
          (latestHumanModelOrderRef.current === null ||
            snapshotInferenceIntent.modelOrder >=
              latestHumanModelOrderRef.current)
        ) {
          latestHumanModelOrderRef.current = snapshotInferenceIntent.modelOrder;
          setLatestHumanInferenceProfile(snapshotInferenceIntent.profile);
        }
        setManagedLiveState((prev) => {
          const mapped = mapChatWriteSnapshot(response, prev);
          if (mapped.invalidLiveRun !== null) {
            reportInvalidLiveRun(mapped.invalidLiveRun.value);
          }
          return mapped.state;
        });
      }
      if (response.history_reload_required) {
        void utils.chat.listSessionEvents.invalidate({
          sessionId: response.session_id,
        });
      }
    },
    [
      canApplyRestSnapshot,
      reportInvalidLiveRun,
      sessionId,
      utils.chat.listSessionEvents,
    ],
  );

  const createClientRequestId = useCallback((): string => {
    return crypto.randomUUID();
  }, []);

  const clientRequestIdForWrite = useCallback(
    (key: string): string => {
      if (failedWriteRequestRef.current?.key === key) {
        return failedWriteRequestRef.current.id;
      }
      return createClientRequestId();
    },
    [createClientRequestId],
  );

  const runWriteMutation = useCallback(
    async (
      writeKey: string,
      clientRequestId: string,
      run: () => Promise<ChatWriteResponse>,
    ): Promise<boolean> => {
      if (writeInFlightRef.current) {
        return false;
      }
      writeInFlightRef.current = true;
      setIsWritePending(true);
      const writeSnapshotRequest = captureRestSnapshotRequest();
      try {
        const response = await run();
        failedWriteRequestRef.current = null;
        applyWriteResponse(response, writeSnapshotRequest);
        if (response.history_reload_required) {
          startResync({ reason: "periodic" });
        }
        return true;
      } catch {
        failedWriteRequestRef.current = { key: writeKey, id: clientRequestId };
        return false;
      } finally {
        writeInFlightRef.current = false;
        setIsWritePending(false);
      }
    },
    [applyWriteResponse, captureRestSnapshotRequest, startResync],
  );

  const onSendInput = useCallback(
    (
      message: string,
      action: ChatAction | null,
      inferenceProfile: RequestedInferenceProfile,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (agentSessionQuery.data == null) {
        return Promise.resolve(false);
      }
      setWasRestCommandBlocked(false);
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      const writableAction = writableChatAction(action);
      const requestedInferenceProfile =
        writableAction?.type === "command" ? null : inferenceProfile;
      const writeKey = JSON.stringify({
        type: "input",
        sessionId,
        message,
        action: writableAction ?? null,
        inferenceProfile: requestedInferenceProfile,
        attachments: attachmentUris ?? [],
      });
      const clientRequestId = clientRequestIdForWrite(writeKey);
      return runWriteMutation(writeKey, clientRequestId, () =>
        sendInputMutation.mutateAsync({
          sessionId,
          agentId: agent.id,
          clientRequestId,
          message,
          action: writableAction,
          inferenceProfile: requestedInferenceProfile,
          attachments: attachmentUris,
        }),
      ).then((succeeded) => {
        if (succeeded && requestedInferenceProfile !== null) {
          setLatestHumanInferenceProfile(requestedInferenceProfile);
        }
        return succeeded;
      });
    },
    [
      agent.id,
      agentSessionQuery.data,
      clientRequestIdForWrite,
      runWriteMutation,
      sendInputMutation,
      sessionId,
    ],
  );

  const onSubmitMessageEdit = useCallback(
    (
      messageId: string,
      message: string,
      inferenceProfile: RequestedInferenceProfile,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (isResponsePending || agentSessionQuery.data == null) {
        return Promise.resolve(false);
      }
      setWasRestCommandBlocked(false);
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      const writeKey = JSON.stringify({
        type: "edit",
        sessionId,
        messageId,
        message,
        inferenceProfile,
        attachments: attachmentUris ?? [],
      });
      const clientRequestId = clientRequestIdForWrite(writeKey);
      return runWriteMutation(writeKey, clientRequestId, () =>
        editMessageMutation.mutateAsync({
          sessionId,
          agentId: agent.id,
          clientRequestId,
          messageId,
          message,
          inferenceProfile,
          attachments: attachmentUris,
        }),
      ).then((succeeded) => {
        if (succeeded) {
          setLatestHumanInferenceProfile(inferenceProfile);
        }
        return succeeded;
      });
    },
    [
      agent.id,
      agentSessionQuery.data,
      clientRequestIdForWrite,
      editMessageMutation,
      isResponsePending,
      runWriteMutation,
      sessionId,
    ],
  );

  const onRetryFailedRun = useCallback(
    (failedEventId: string): Promise<boolean> => {
      const writeKey = JSON.stringify({
        type: "failed_run_retry",
        sessionId,
        failedEventId,
      });
      const clientRequestId = clientRequestIdForWrite(writeKey);
      return runWriteMutation(writeKey, clientRequestId, () =>
        retryFailedRunMutation.mutateAsync({
          sessionId,
          agentId: agent.id,
          failedEventId,
          clientRequestId,
        }),
      );
    },
    [
      agent.id,
      clientRequestIdForWrite,
      retryFailedRunMutation,
      runWriteMutation,
      sessionId,
    ],
  );

  const onStopRequest = useCallback(() => {
    if (stopSessionRunMutation.isPending) {
      return;
    }
    setManagedLiveState((prev) => ({ ...prev, isStopPending: true }));
    void stopSessionRunMutation
      .mutateAsync({ sessionId })
      .finally(() =>
        setManagedLiveState((prev) => ({ ...prev, isStopPending: false })),
      );
  }, [sessionId, stopSessionRunMutation]);

  const onDeletePendingInputBuffer = useCallback(
    (bufferId: string) => {
      setManagedLiveState((prev) => ({
        ...prev,
        pendingInputBuffers: prev.pendingInputBuffers.map((buffer) =>
          buffer.id === bufferId ? { ...buffer, status: "deleting" } : buffer,
        ),
      }));
      deleteInputBufferMutation.mutate(
        { sessionId, bufferId },
        {
          onSuccess: () => {
            setManagedLiveState((prev) => {
              const nextBuffers = prev.pendingInputBuffers.filter(
                (buffer) => buffer.id !== bufferId,
              );
              const hasVisibleRunActivity =
                prev.partialHistory.order.length > 0 ||
                prev.liveRunPhase !== null ||
                prev.liveRun !== null;
              return {
                ...prev,
                pendingInputBuffers: nextBuffers,
                isResponsePending:
                  hasModelPendingInputBuffers(nextBuffers) ||
                  hasVisibleRunActivity,
              };
            });
            startResync({ reason: "periodic" });
          },
          onError: () => {
            setManagedLiveState((prev) => ({
              ...prev,
              pendingInputBuffers: prev.pendingInputBuffers.map((buffer) =>
                buffer.id === bufferId
                  ? { ...buffer, status: "pending" }
                  : buffer,
              ),
            }));
          },
        },
      );
    },
    [deleteInputBufferMutation, sessionId, startResync],
  );

  const onUpdateGoal = useCallback(
    async (objective: string): Promise<boolean> => {
      try {
        const updated = await updateSessionGoalMutation.mutateAsync({
          sessionId,
          objective,
        });
        setManagedLiveState((prev) => ({
          ...prev,
          goal: normalizeGoalState(updated),
        }));
        void utils.chat.listSessionEvents.invalidate({ sessionId });
        return true;
      } catch {
        return false;
      }
    },
    [sessionId, updateSessionGoalMutation, utils.chat.listSessionEvents],
  );

  const onClearGoal = useCallback(async (): Promise<boolean> => {
    try {
      const updated = await updateSessionGoalMutation.mutateAsync({
        sessionId,
        objective: null,
      });
      setManagedLiveState((prev) => ({
        ...prev,
        goal: normalizeGoalState(updated),
      }));
      void utils.chat.listSessionEvents.invalidate({ sessionId });
      return true;
    } catch {
      return false;
    }
  }, [sessionId, updateSessionGoalMutation, utils.chat.listSessionEvents]);

  const updateGoalStatus = useCallback(
    async (status: "active" | "paused", hint?: string): Promise<boolean> => {
      try {
        const normalizedHint = hint?.trim();
        const updated = await updateSessionGoalStatusMutation.mutateAsync({
          sessionId,
          status,
          ...(normalizedHint ? { resumeHint: normalizedHint } : {}),
        });
        setManagedLiveState((prev) => ({
          ...prev,
          goal: normalizeGoalState(updated),
        }));
        void utils.chat.listSessionEvents.invalidate({ sessionId });
        return true;
      } catch {
        return false;
      }
    },
    [sessionId, updateSessionGoalStatusMutation, utils.chat.listSessionEvents],
  );

  const onPauseGoal = useCallback(
    (): Promise<boolean> => updateGoalStatus("paused"),
    [updateGoalStatus],
  );

  const onResumeGoal = useCallback(
    (hint?: string): Promise<boolean> => updateGoalStatus("active", hint),
    [updateGoalStatus],
  );

  const isCompactingFromHistory = useMemo(
    () => isCompactionActiveInHistory(messages),
    [messages],
  );
  const tokenUsage = useMemo(() => latestTokenUsage(messages), [messages]);
  const isCompacting = managedLiveState.isCompacting || isCompactingFromHistory;
  const isStopAvailable = isUserBlockingRunPhase(managedLiveState.liveRunPhase);
  const isStopPending =
    stopSessionRunMutation.isPending || managedLiveState.isStopPending;

  return {
    sessionId,
    chatViewState,
    chatTimelineState,
    messages,
    pendingInputBuffers,
    connectionStatus,
    isResponsePending,
    isWritePending,
    isModelResponsePending,
    liveRun,
    defaultInferenceProfile,
    hasMore,
    isLoadingMore,
    isLoadingNewer,
    onSendInput,
    onDeletePendingInputBuffer,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    onLoadMore,
    onLoadNewer,
    onResetToLatest,
    onSubmitMessageEdit,
    onRetryFailedRun,
    isCompacting,
    wasCommandBlocked: wasRestCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    inputActions: (inputActionsQuery.data?.items ?? []).flatMap((item) => {
      const action = chatActionFromValue(item.action);
      return action === null ? [] : [{ ...item, action }];
    }),
    authorizationRequests,
    onAuthorizationComplete,
    actionExecutions:
      chatTimelineState.type === "DETACHED_HISTORY_BROWSING"
        ? actionExecutions.filter(
            (projection) => projection.provenance === "durable",
          )
        : actionExecutions,
    tokenUsage,
    goal: managedLiveState.goal,
    todo: managedLiveState.todo,
  };
}
