"use client";

/**
 * Single-session container hook.
 *
 * WebSocket connection, message history, pagination, authorization request, compaction status etc.
 * that must be isolated per session status manages.. parent(useChatPageContainer) in
 * key based remount with when session switches  hook  of instance is completely replaced
 * previous session of WebSocket/buffer new session to ensures it does not leak.
 */

import { useQueryClient } from "@tanstack/react-query";
import { getQueryKey } from "@trpc/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { applyProviderToolCallItem } from "../hooks/providerToolCallProjection";
import {
  applyFunctionCallItem,
  applyFunctionCallOutput,
} from "../hooks/toolCallMerge";
import { useChatWebSocket } from "../hooks/useChatWebSocket";
import type { UploadedFile } from "../hooks/useFileUpload";
import type {
  AgentRunPhase,
  AuthorizationRequest,
  ChatEvent,
  ChatMessage,
  ChatTimelineState,
  ChatViewState,
  ConnectionStatus,
  FileAttachment,
  GoalStateSnapshot,
  PendingInputBuffer,
  SlashCommand,
  TodoStateSnapshot,
  TokenUsageSummary,
  ToolResultStatus,
} from "../types";
import type {
  AgentResponse,
  ChatEventResponse,
  ChatWriteResponse,
  LiveEventListResponse,
} from "@azents/public-client";

export type SessionRunState = "idle" | "running";

interface ChatSessionContainerProps {
  /** mount time of session ID. new chat when null. */
  initialSessionId: string | null;
  /** this session agent */
  agent: AgentResponse;
  /** server new session createtext when parent to notice (URL/sidebar syncfor) */
  onSessionCreated: (sessionId: string) => void;
  /** WebSocket connection status parent to push (for sidebar badge) */
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export interface ChatSessionContainerOutput {
  /** current session ID (server-assigned after update) */
  sessionId: string | null;
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
  /** whether older messages exist */
  hasMore: boolean;
  /** older messages loading */
  isLoadingMore: boolean;
  /** newer messages loading */
  isLoadingNewer: boolean;
  /** message send */
  onSendMessage: (
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
  /** send command selected from slash autocomplete */
  onSendCommand: (command: string) => Promise<boolean>;
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
  /** older messages  withtext */
  onLoadMore: () => void;
  /** newer messages  withtext */
  onLoadNewer: () => void;
  /** latest reset */
  onResetToLatest: () => void;
  /** submit user message edit */
  onSubmitMessageEdit: (
    messageId: string,
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
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
  /** server-managed textwhen text list */
  slashCommands: SlashCommand[];
  /** pending OAuth authorization request list */
  authorizationRequests: AuthorizationRequest[];
  /** auth complete when remove corresponding request */
  onAuthorizationComplete: (toolkitId: string) => void;
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

function liveRunPhaseFromResponse(live: unknown): AgentRunPhase | null {
  if (!isRecord(live)) {
    return null;
  }
  const run = live.run;
  if (!isRecord(run) || stringField(run, "status") !== "running") {
    return null;
  }
  return agentRunPhaseFromValue(run.phase);
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

function eventRenderKey(event: ChatEventResponse): string {
  switch (event.kind) {
    case "assistant_message": {
      const item = nativeArtifactItem(event);
      if (item !== null) {
        const contentIndex = item.content_index;
        if (typeof contentIndex === "number") {
          return `assistant:content:${contentIndex}`;
        }
        const outputIndex = item.output_index;
        if (typeof outputIndex === "number") {
          return `assistant:output:${outputIndex}`;
        }
        const nativeId = stringField(item, "id");
        if (nativeId !== null) {
          return `assistant:native:${nativeId}`;
        }
      }
      return `assistant:event:${event.external_id ?? event.id}`;
    }
    case "reasoning":
      return "reasoning";
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
    case "client_tool_result":
    case "provider_tool_result": {
      const callId = stringField(event.payload, "call_id");
      return callId === null
        ? `tool-result:event:${event.external_id ?? event.id}`
        : `tool-result:${callId}`;
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
            ...(attachments.length > 0 ? { attachments } : {}),
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
            status: providerToolCallStatusFromPayload(payload),
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
        return messages;
      }
      case "turn_marker": {
        const usage = isRecord(payload.usage) ? payload.usage : null;
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
      case "subagent_start": {
        return [
          ...messages,
          {
            id: event.id,
            role: "subagent_start",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              subagent_run_id: stringField(payload, "subagent_run_id") ?? "",
              subagent_id: stringField(payload, "subagent_id") ?? "",
              subagent_name: stringField(payload, "subagent_name") ?? "",
              subagent_session_id:
                stringField(payload, "subagent_session_id") ?? "",
            },
          },
        ];
      }
      case "subagent_end": {
        return [
          ...messages,
          {
            id: event.id,
            role: "subagent_end",
            content:
              stringField(payload, "result") ?? stringField(payload, "error"),
            createdAt: event.created_at,
            status: "complete",
            metadata: {
              ...eventMetadata(event),
              subagent_run_id: stringField(payload, "subagent_run_id") ?? "",
              subagent_id: stringField(payload, "subagent_id") ?? "",
              subagent_session_id:
                stringField(payload, "subagent_session_id") ?? "",
              status: stringField(payload, "status") ?? "",
            },
          },
        ];
      }
      case "system_error": {
        return [
          ...messages,
          {
            id: event.id,
            role: "error",
            content: stringField(payload, "content"),
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
      }
      case "goal_continuation": {
        return [
          ...messages,
          {
            id: event.id,
            role: "goal_continuation",
            content: null,
            createdAt: event.created_at,
            status: "complete",
            metadata: eventMetadata(event),
          },
        ];
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
      case "system_reminder":
      case "unknown_adapter_output": {
        return messages;
      }
    }
    return messages;
  }, options.initialMessages ?? []);
}

function isInputBufferLiveEvent(event: ChatEventResponse): boolean {
  if (event.kind !== "user_message") {
    return false;
  }
  const metadata = event.payload.metadata;
  return isRecord(metadata) && metadata.live_projection === "input_buffer";
}

function mapInputBufferLiveEvent(
  event: ChatEventResponse,
): PendingInputBuffer | null {
  if (!isInputBufferLiveEvent(event)) {
    return null;
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
  };
}

interface PartialHistoryState {
  order: string[];
  itemsByKey: Record<string, ChatEventResponse>;
}

interface ManagedLiveState {
  partialHistory: PartialHistoryState;
  pendingInputBuffers: PendingInputBuffer[];
  liveRunPhase: AgentRunPhase | null;
  sessionRunState: SessionRunState;
  isResponsePending: boolean;
  isModelResponsePending: boolean;
  isCompacting: boolean;
  isStopPending: boolean;
  todo: TodoStateSnapshot;
  goal: GoalStateSnapshot;
}

interface LiveTaxonomySnapshot {
  partial_history: { items: ChatEventResponse[] };
  input_buffers: ChatEventResponse[];
  run?: LiveEventListResponse["run"];
  session_run_state: LiveEventListResponse["session_run_state"];
  todo?: TodoStateSnapshot | null;
  goal?: Partial<GoalStateSnapshot> | null;
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
    liveRunPhase: null,
    sessionRunState: "idle",
    isResponsePending: false,
    isModelResponsePending: false,
    isCompacting: false,
    isStopPending: false,
    todo: emptyTodoState(),
    goal: emptyGoalState(),
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

function removePartialHistoryCounterpart(
  partialHistory: PartialHistoryState,
  durableEvent: ChatEventResponse,
): PartialHistoryState {
  const key = partialHistorySemanticKey(durableEvent);
  if (!Object.prototype.hasOwnProperty.call(partialHistory.itemsByKey, key)) {
    return partialHistory;
  }
  const order = partialHistory.order.filter((item) => item !== key);
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

function replaceLiveStateFromSnapshot(
  live: LiveTaxonomySnapshot,
): ManagedLiveState {
  const partialHistory = live.partial_history.items
    .filter((event) => event.kind !== "provider_tool_call")
    .reduce(upsertPartialHistoryEvent, emptyPartialHistoryState());
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
  const liveRunPhase = liveRunPhaseFromResponse(live);
  return {
    ...emptyManagedLiveState(),
    partialHistory: partialHistoryWithGoalContinuations,
    pendingInputBuffers,
    liveRunPhase,
    sessionRunState: sessionRunStateFromResponse(live),
    isResponsePending: liveRunPhase !== null || partialHistory.order.length > 0,
    isModelResponsePending: isModelRunPhase(liveRunPhase),
    isCompacting: liveRunPhase === "compacting",
    todo: live.todo ?? emptyTodoState(),
    goal: normalizeGoalState(live.goal),
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

function hasMergeKey(seen: Set<string>, message: ChatMessage): boolean {
  return getMessageMergeKeys(message).some((key) => seen.has(key));
}

function rememberMergeKeys(seen: Set<string>, message: ChatMessage): void {
  for (const key of getMessageMergeKeys(message)) {
    seen.add(key);
  }
}

function mergeMessagePages(
  existing: ChatMessage[],
  incoming: ChatMessage[],
  placement: "append" | "prepend",
): ChatMessage[] {
  const ordered =
    placement === "append" ? [existing, incoming] : [incoming, existing];
  const seen = new Set<string>();
  const merged: ChatMessage[] = [];
  for (const page of ordered) {
    for (const message of page) {
      if (hasMergeKey(seen, message)) {
        continue;
      }
      rememberMergeKeys(seen, message);
      merged.push(message);
    }
  }
  return merged;
}

function mergeHistoryAndPartialHistory(
  historyMessages: ChatMessage[],
  partialHistoryMessages: ChatMessage[],
): ChatMessage[] {
  const historyKeys = new Set<string>();
  for (const message of historyMessages) {
    rememberMergeKeys(historyKeys, message);
  }
  return [
    ...historyMessages,
    ...partialHistoryMessages.filter(
      (message) => !hasMergeKey(historyKeys, message),
    ),
  ];
}

function mapSessionEvents(data: {
  history: {
    items: ChatEventResponse[];
    has_more: boolean;
    has_newer?: boolean;
  };
  live: LiveEventListResponse;
}): {
  historyMessages: ChatMessage[];
  liveState: ManagedLiveState;
  hasMore: boolean;
  hasNewer: boolean;
  newestCursor: string | null;
} {
  return {
    historyMessages: mapEvents(data.history.items, {
      renderIncompleteToolCalls: false,
    }),
    liveState: replaceLiveStateFromSnapshot(data.live),
    hasMore: data.history.has_more,
    hasNewer: data.history.has_newer ?? false,
    newestCursor: data.history.items.at(-1)?.id ?? null,
  };
}

function mapChatWriteSnapshot(response: ChatWriteResponse): ManagedLiveState {
  return replaceLiveStateFromSnapshot({
    partial_history: { items: response.snapshot.partial_history_events },
    input_buffers: response.snapshot.input_buffer_events,
    run: response.snapshot.run,
    session_run_state: response.snapshot.session_run_state,
    todo: response.snapshot.todo,
    goal: normalizeGoalState(response.snapshot.goal),
  });
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

function mergeWithOlderPages(
  existing: ChatMessage[],
  serverLatest: ChatMessage[],
): ChatMessage[] {
  if (serverLatest.length === 0) {
    return existing;
  }
  const cutoff = serverLatest[0];
  if (!cutoff) {
    return existing;
  }
  const serverIds = new Set(serverLatest.flatMap(getMessageMergeKeys));
  const olderPages = existing.filter(
    (m) =>
      m.id < cutoff.id &&
      getMessageMergeKeys(m).every((key) => !serverIds.has(key)),
  );
  return [...olderPages, ...serverLatest];
}

export function useChatSessionContainer(
  props: ChatSessionContainerProps,
): ChatSessionContainerOutput {
  const {
    initialSessionId,
    agent,
    onSessionCreated,
    onConnectionStatusChange,
  } = props;

  // internal sessionId status: mount time of initialSessionId  with start.
  // The canonical session route provides the server-assigned session id.
  // useChatWebSocket  sessionIdRef  with latest value textso with reconnect triggertext text.
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);

  const [chatViewState, setChatViewState] = useState<ChatViewState>(() =>
    initialSessionId ? { type: "LOADING_HISTORY" } : { type: "READY" },
  );
  const [chatTimelineState, setChatTimelineState] = useState<ChatTimelineState>(
    { type: "LATEST_FOLLOWING" },
  );
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isLoadingNewer, setIsLoadingNewer] = useState(false);
  const [authorizationRequests, setAuthorizationRequests] = useState<
    AuthorizationRequest[]
  >([]);
  const [isWritePending, setIsWritePending] = useState(false);
  const [wasRestCommandBlocked, setWasRestCommandBlocked] = useState(false);
  const [historyMessages, setHistoryMessages] = useState<ChatMessage[]>([]);
  const [managedLiveState, setManagedLiveState] = useState<ManagedLiveState>(
    () => emptyManagedLiveState(),
  );
  const [isSubscribeReady, setIsSubscribeReady] = useState(
    initialSessionId === null,
  );
  const historyNewestCursorRef = useRef<string | null>(null);
  const writeInFlightRef = useRef(false);
  const failedWriteRequestRef = useRef<{ key: string; id: string } | null>(
    null,
  );
  const partialHistoryMessages = useMemo(
    () =>
      chatTimelineState.type === "LATEST_FOLLOWING"
        ? mapEvents(
            orderedPartialHistoryEvents(managedLiveState.partialHistory),
            {
              renderIncompleteToolCalls: true,
              messageStatus: "partial",
            },
          )
        : [],
    [chatTimelineState.type, managedLiveState.partialHistory],
  );
  const messages = useMemo(
    () =>
      mergeHistoryAndPartialHistory(historyMessages, partialHistoryMessages),
    [historyMessages, partialHistoryMessages],
  );
  const pendingInputBuffers = managedLiveState.pendingInputBuffers;
  const isResponsePending = managedLiveState.isResponsePending;
  const isModelResponsePending = managedLiveState.isModelResponsePending;
  const sessionRunState = managedLiveState.sessionRunState;

  // WebSocket connection text (ticket + wsUrl)
  const connectionInfoQuery = trpc.chat.getConnectionInfo.useQuery();
  const slashCommandsQuery = trpc.chat.listSlashCommands.useQuery();

  const queryClient = useQueryClient();
  const utils = trpc.useUtils();

  // Durable historyand current live projection text fetches..
  const eventsQuery = trpc.chat.listSessionEvents.useQuery(
    { sessionId: sessionId ?? "" },
    {
      enabled:
        sessionId !== null &&
        isSubscribeReady &&
        chatViewState.type === "LOADING_HISTORY",
      gcTime: 0,
      staleTime: 0,
    },
  );

  useEffect(() => {
    const sessionEventsQueryKey = getQueryKey(trpc.chat.listSessionEvents);
    return () => {
      void queryClient.invalidateQueries({ queryKey: sessionEventsQueryKey });
      queryClient.removeQueries({ queryKey: sessionEventsQueryKey });
    };
  }, [queryClient]);

  useEffect(() => {
    if (sessionId === null) {
      return;
    }
    void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
  }, [agent.id, sessionId, sessionRunState, utils.chat.listAgentSessions]);

  const batchReloadRef = useRef<() => boolean>(() => false);
  const compactionReloadRef = useRef<(continuing: boolean) => void>(() => {});

  // parent with to pass callback ref (callback identity to avoid WS reconnect by identity change)
  const onSessionCreatedRef = useRef(onSessionCreated);
  onSessionCreatedRef.current = onSessionCreated;

  const handleChatEvent = useCallback(
    (event: ChatEvent): void => {
      const markRunActive = (phase: AgentRunPhase | null): void => {
        setManagedLiveState((prev) => ({
          ...prev,
          liveRunPhase: phase,
          sessionRunState: "running",
          isResponsePending: true,
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
      const markRunInactive = (): void => {
        setManagedLiveState((prev) => ({
          ...prev,
          liveRunPhase: null,
          sessionRunState: "idle",
          isResponsePending: false,
          isModelResponsePending: false,
          isCompacting: false,
          isStopPending: false,
        }));
      };

      if ("type" in event && event.type === "todo_state_changed") {
        setManagedLiveState((prev) => ({
          ...prev,
          todo: event.todo,
        }));
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

      if ("type" in event && event.type === "live_event_upserted") {
        const responseEvent = event.event;
        const pending = mapInputBufferLiveEvent(responseEvent);
        if (pending !== null) {
          setManagedLiveState((prev) => ({
            ...prev,
            pendingInputBuffers: [
              ...prev.pendingInputBuffers.filter(
                (buffer) => buffer.id !== pending.id,
              ),
              pending,
            ],
            isResponsePending: true,
          }));
          if (sessionId !== null && pending.sessionId !== sessionId) {
            void connectionInfoQuery.refetch();
          }
          return;
        }
        if (responseEvent.kind === "provider_tool_call") {
          markModelOutputVisible();
          setHistoryMessages((prev) =>
            mapEvents([responseEvent], {
              initialMessages: prev,
              renderIncompleteToolCalls: true,
            }),
          );
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
        setHistoryMessages((prev) =>
          mapEvents([responseEvent], {
            initialMessages: prev,
            renderIncompleteToolCalls: true,
          }),
        );
        setManagedLiveState((prev) => ({
          ...prev,
          partialHistory: removePartialHistoryCounterpart(
            prev.partialHistory,
            responseEvent,
          ),
          pendingInputBuffers:
            responseEvent.kind === "user_message" ||
            responseEvent.kind === "goal_continuation"
              ? prev.pendingInputBuffers.filter(
                  (buffer) =>
                    buffer.id !== responseEvent.external_id &&
                    buffer.id !== responseEvent.id,
                )
              : prev.pendingInputBuffers,
        }));
        if (responseEvent.kind === "run_marker") {
          markRunInactive();
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
          break;
        case "run_phase_changed":
          markRunActive(event.phase);
          break;
        case "run_complete":
          if ("item" in event) {
            setHistoryMessages((prev) =>
              upsertMessage(prev, {
                id: event.id,
                role: "run_complete",
                content: null,
                createdAt: new Date().toISOString(),
                status: "complete",
              }),
            );
          }
          markRunInactive();
          break;
        case "run_stopped":
          markRunInactive();
          break;
        case "runtime_error":
          setHistoryMessages((prev) => [
            ...prev,
            {
              id: `runtime-error-${Date.now()}`,
              role: "error",
              content: event.message,
              createdAt: new Date().toISOString(),
              status: "complete",
            },
          ]);
          markRunInactive();
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
    [connectionInfoQuery, sessionId],
  );

  const {
    connectionStatus,
    setBufferingLiveEvents,
    replayBufferedLiveEvents,
    requestSubscriptionHealthCheck,
  } = useChatWebSocket({
    wsUrl: connectionInfoQuery.data?.wsUrl ?? null,
    ticket: connectionInfoQuery.data?.ticket ?? null,
    sessionId,
    onEvent: handleChatEvent,
    onBatchReload: () => batchReloadRef.current(),
    onSubscribed: () => {
      setIsSubscribeReady(true);
      setBufferingLiveEvents(true);
      if (sessionId !== null) {
        setChatViewState({ type: "LOADING_HISTORY" });
      }
    },
    onAuthError: () => void connectionInfoQuery.refetch(),
    onBufferedLiveEvent: () => {
      setChatTimelineState((prev) =>
        prev.type === "DETACHED_HISTORY_BROWSING"
          ? { ...prev, hasNewer: true }
          : prev,
      );
    },
  });

  const messagesRefetch = useCallback((): boolean => {
    if (!sessionId || chatViewState.type !== "READY") {
      return false;
    }
    void requestSubscriptionHealthCheck().then((ok) => {
      if (!ok) {
        replayBufferedLiveEvents();
        void connectionInfoQuery.refetch();
        return;
      }
      setBufferingLiveEvents(true);
      void eventsQuery.refetch().catch(() => replayBufferedLiveEvents());
    });
    return true;
  }, [
    chatViewState.type,
    connectionInfoQuery,
    eventsQuery,
    replayBufferedLiveEvents,
    requestSubscriptionHealthCheck,
    sessionId,
    setBufferingLiveEvents,
  ]);
  batchReloadRef.current = messagesRefetch;

  const applyLatestSnapshot = useCallback(
    async (targetSessionId: string, followBottom: boolean): Promise<void> => {
      setBufferingLiveEvents(true);
      const result = await utils.chat.listSessionEvents.fetch({
        sessionId: targetSessionId,
      });
      const mapped = mapSessionEvents(result);
      historyNewestCursorRef.current = mapped.newestCursor;
      setHistoryMessages(mapped.historyMessages);
      setManagedLiveState(mapped.liveState);
      setHasMore(mapped.hasMore);
      setChatTimelineState({ type: "LATEST_FOLLOWING" });
      replayBufferedLiveEvents();
      if (followBottom) {
        setChatViewState({ type: "READY" });
      }
    },
    [
      replayBufferedLiveEvents,
      setBufferingLiveEvents,
      utils.chat.listSessionEvents,
    ],
  );

  compactionReloadRef.current = (continuing) => {
    if (!sessionId) {
      return;
    }
    void utils.chat.listSessionEvents.fetch({ sessionId }).then((result) => {
      const mapped = mapSessionEvents(result);
      historyNewestCursorRef.current = mapped.newestCursor;
      setHistoryMessages(mapped.historyMessages);
      setManagedLiveState((prev) => ({
        ...mapped.liveState,
        isResponsePending: continuing
          ? mapped.liveState.isResponsePending || prev.isResponsePending
          : mapped.liveState.isResponsePending,
      }));
      setHasMore(mapped.hasMore);
    });
  };

  // connection status parent with push (sidebar badge so it can reflect)
  useEffect(() => {
    onConnectionStatusChange(connectionStatus);
  }, [connectionStatus, onConnectionStatusChange]);

  // message history  withtext complete when message settings
  useEffect(() => {
    if (chatViewState.type === "LOADING_HISTORY" && eventsQuery.data) {
      const mapped = mapSessionEvents(eventsQuery.data);
      historyNewestCursorRef.current = mapped.newestCursor;
      setHistoryMessages(mapped.historyMessages);
      setManagedLiveState(mapped.liveState);
      setHasMore(mapped.hasMore);
      setChatTimelineState({ type: "LATEST_FOLLOWING" });
      setChatViewState({ type: "READY" });
      replayBufferedLiveEvents();
    }
  }, [chatViewState.type, eventsQuery.data, replayBufferedLiveEvents]);

  // batch text withtext data text. Detached  in live state  textdoes not..
  useEffect(() => {
    if (chatViewState.type !== "READY" || !eventsQuery.data) {
      return;
    }
    const mapped = mapSessionEvents(eventsQuery.data);
    setManagedLiveState(mapped.liveState);
    if (chatTimelineState.type === "DETACHED_HISTORY_BROWSING") {
      setChatTimelineState({
        type: "DETACHED_HISTORY_BROWSING",
        hasNewer: mapped.hasNewer || chatTimelineState.hasNewer,
        newestCursor: chatTimelineState.newestCursor,
      });
      replayBufferedLiveEvents();
      return;
    }
    historyNewestCursorRef.current = mapped.newestCursor;
    setHistoryMessages((prev) =>
      mergeWithOlderPages(prev, mapped.historyMessages),
    );
    replayBufferedLiveEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- eventsQuery.dataUpdatedAt change when toonly run
  }, [eventsQuery.dataUpdatedAt]);

  const onLoadMore = useCallback(() => {
    if (!sessionId || isLoadingMore || !hasMore) {
      return;
    }

    const oldestMessage = historyMessages[0];
    if (!oldestMessage) {
      return;
    }

    setIsLoadingMore(true);
    void utils.chat.listSessionEvents
      .fetch({
        sessionId,
        before: oldestMessage.id,
      })
      .then((result) => {
        const olderMessages = mapEvents(result.history.items, {
          renderIncompleteToolCalls: false,
        });
        setHistoryMessages((prev) =>
          mergeMessagePages(prev, olderMessages, "prepend"),
        );
        setHasMore(result.history.has_more);
        if (chatTimelineState.type === "LATEST_FOLLOWING") {
          setChatTimelineState({
            type: "DETACHED_HISTORY_BROWSING",
            hasNewer: false,
            newestCursor:
              historyNewestCursorRef.current ??
              historyMessages.at(-1)?.id ??
              null,
          });
        }
      })
      .finally(() => {
        setIsLoadingMore(false);
      });
  }, [
    chatTimelineState.type,
    sessionId,
    isLoadingMore,
    hasMore,
    historyMessages,
    utils.chat.listSessionEvents,
  ]);

  const onLoadNewer = useCallback((): void => {
    if (
      sessionId === null ||
      isLoadingNewer ||
      chatTimelineState.type !== "DETACHED_HISTORY_BROWSING" ||
      !chatTimelineState.hasNewer ||
      chatTimelineState.newestCursor === null
    ) {
      return;
    }

    setIsLoadingNewer(true);
    void utils.chat.listSessionEvents
      .fetch({
        sessionId,
        after: chatTimelineState.newestCursor,
      })
      .then((result) => {
        const newerMessages = mapEvents(result.history.items, {
          renderIncompleteToolCalls: false,
        });
        setHistoryMessages((prev) =>
          mergeMessagePages(prev, newerMessages, "append"),
        );
        const newestCursor = result.history.items.at(-1)?.id ?? null;
        const hasNewer = result.history.has_newer ?? false;
        if (hasNewer) {
          setChatTimelineState({
            type: "DETACHED_HISTORY_BROWSING",
            hasNewer,
            newestCursor: newestCursor ?? chatTimelineState.newestCursor,
          });
          return;
        }
        void applyLatestSnapshot(sessionId, false);
      })
      .finally(() => {
        setIsLoadingNewer(false);
      });
  }, [
    applyLatestSnapshot,
    chatTimelineState,
    isLoadingNewer,
    sessionId,
    utils.chat.listSessionEvents,
  ]);

  const onResetToLatest = useCallback((): void => {
    if (sessionId === null) {
      return;
    }
    void applyLatestSnapshot(sessionId, true);
  }, [applyLatestSnapshot, sessionId]);

  const onAuthorizationComplete = useCallback((toolkitId: string) => {
    setAuthorizationRequests((prev) =>
      prev.filter((r) => r.toolkitId !== toolkitId),
    );
  }, []);

  const sendMessageMutation = trpc.chat.sendMessage.useMutation();
  const editMessageMutation = trpc.chat.editMessage.useMutation();
  const sendCommandMutation = trpc.chat.sendCommand.useMutation();
  const stopSessionRunMutation = trpc.chat.stopSessionRun.useMutation();
  const deleteInputBufferMutation = trpc.chat.deleteInputBuffer.useMutation();
  const updateSessionGoalMutation = trpc.chat.updateSessionGoal.useMutation();
  const updateSessionGoalStatusMutation =
    trpc.chat.updateSessionGoalStatus.useMutation();

  const applyWriteResponse = useCallback(
    (response: ChatWriteResponse): void => {
      if (response.session_id !== sessionId) {
        setSessionId(response.session_id);
        onSessionCreatedRef.current(response.session_id);
      }
      setManagedLiveState(mapChatWriteSnapshot(response));
      if (response.history_reload_required) {
        void utils.chat.listSessionEvents.invalidate({
          sessionId: response.session_id,
        });
      }
    },
    [sessionId, utils.chat.listSessionEvents],
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
      try {
        const response = await run();
        failedWriteRequestRef.current = null;
        applyWriteResponse(response);
        if (response.history_reload_required) {
          const result = await utils.chat.listSessionEvents.fetch({
            sessionId: response.session_id,
          });
          const mapped = mapSessionEvents(result);
          historyNewestCursorRef.current = mapped.newestCursor;
          setHistoryMessages(mapped.historyMessages);
          setManagedLiveState(mapped.liveState);
          setHasMore(mapped.hasMore);
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
    [applyWriteResponse, utils.chat.listSessionEvents],
  );

  const onSendMessage = useCallback(
    (message: string, attachments?: UploadedFile[]): Promise<boolean> => {
      setWasRestCommandBlocked(false);
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      const writeKey = JSON.stringify({
        type: "message",
        sessionId,
        message,
        attachments: attachmentUris ?? [],
      });
      const clientRequestId = clientRequestIdForWrite(writeKey);
      return runWriteMutation(writeKey, clientRequestId, () =>
        sendMessageMutation.mutateAsync({
          sessionId,
          agentId: agent.id,
          clientRequestId,
          message,
          attachments: attachmentUris,
        }),
      );
    },
    [
      agent.id,
      clientRequestIdForWrite,
      runWriteMutation,
      sendMessageMutation,
      sessionId,
    ],
  );

  const onSendCommand = useCallback(
    (command: string): Promise<boolean> => {
      if (sessionId === null) {
        return Promise.resolve(false);
      }
      if (isResponsePending) {
        setWasRestCommandBlocked(true);
        return Promise.resolve(false);
      }
      setWasRestCommandBlocked(false);
      const normalizedCommand = command.toLowerCase();
      const writeKey = JSON.stringify({
        type: "command",
        sessionId,
        command: normalizedCommand,
      });
      const clientRequestId = clientRequestIdForWrite(writeKey);
      return runWriteMutation(writeKey, clientRequestId, () =>
        sendCommandMutation.mutateAsync({
          sessionId,
          agentId: agent.id,
          clientRequestId,
          command: normalizedCommand,
        }),
      );
    },
    [
      agent.id,
      clientRequestIdForWrite,
      isResponsePending,
      runWriteMutation,
      sendCommandMutation,
      sessionId,
    ],
  );

  const onSubmitMessageEdit = useCallback(
    (
      messageId: string,
      message: string,
      attachments?: UploadedFile[],
    ): Promise<boolean> => {
      if (sessionId === null) {
        return Promise.resolve(false);
      }
      if (isResponsePending) {
        return Promise.resolve(false);
      }
      setWasRestCommandBlocked(false);
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      const writeKey = JSON.stringify({
        type: "edit",
        sessionId,
        messageId,
        message,
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
          attachments: attachmentUris,
        }),
      );
    },
    [
      agent.id,
      clientRequestIdForWrite,
      editMessageMutation,
      isResponsePending,
      runWriteMutation,
      sessionId,
    ],
  );

  const onStopRequest = useCallback(() => {
    if (sessionId === null || stopSessionRunMutation.isPending) {
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
      if (!sessionId) {
        return;
      }
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
                prev.liveRunPhase !== null;
              return {
                ...prev,
                pendingInputBuffers: nextBuffers,
                isResponsePending:
                  nextBuffers.length > 0 || hasVisibleRunActivity,
              };
            });
            void utils.chat.listSessionEvents.invalidate({ sessionId });
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
    [deleteInputBufferMutation, sessionId, utils.chat.listSessionEvents],
  );

  const onUpdateGoal = useCallback(
    async (objective: string): Promise<boolean> => {
      if (!sessionId) {
        return false;
      }
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
    if (!sessionId) {
      return false;
    }
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
      if (!sessionId) {
        return false;
      }
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
  const isStopAvailable = sessionRunState === "running";
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
    hasMore,
    isLoadingMore,
    isLoadingNewer,
    onSendMessage,
    onSendCommand,
    onDeletePendingInputBuffer,
    onClearGoal,
    onUpdateGoal,
    onPauseGoal,
    onResumeGoal,
    onLoadMore,
    onLoadNewer,
    onResetToLatest,
    onSubmitMessageEdit,
    isCompacting,
    wasCommandBlocked: wasRestCommandBlocked,
    isStopAvailable,
    isStopPending,
    onStopRequest,
    slashCommands: slashCommandsQuery.data?.items ?? [],
    authorizationRequests,
    onAuthorizationComplete,
    tokenUsage,
    goal: managedLiveState.goal,
    todo: managedLiveState.todo,
  };
}
