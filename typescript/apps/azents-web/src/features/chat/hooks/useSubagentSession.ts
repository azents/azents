"use client";

/**
 * Subagent session data loading hook.
 *
 * sessionId when set REST API with history fetches..
 * isRunningwhen WebSocket connection real-time streams..
 * popup when closed (sessionId=null) WS release.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { applyProviderToolCallItem } from "./providerToolCallProjection";
import {
  applyFunctionCallItem,
  applyFunctionCallOutput,
} from "./toolCallMerge";
import type {
  ActiveToolCall,
  ChatEvent,
  ChatHistoryEvent,
  ChatMessage,
  EventAttachment,
  FileAttachment,
  OutputPart,
  UserContentPart,
  WireTokenUsage,
} from "../types";

type RenderablePart = OutputPart | UserContentPart;

function eventAttachmentToFileAttachment(
  attachment: EventAttachment,
): FileAttachment {
  return {
    attachmentId: attachment.attachment_id,
    uri: attachment.uri,
    mediaType: attachment.media_type,
    size: attachment.size,
    name: attachment.name,
    textPreview: attachment.text_preview ?? null,
    availability: attachment.availability ?? "available",
    previewTitle: attachment.preview_title ?? null,
    previewThumbnailUri: attachment.preview_thumbnail_uri ?? null,
    previewThumbnailMediaType: attachment.preview_thumbnail_media_type ?? null,
    previewThumbnailWidth: attachment.preview_thumbnail_width ?? null,
    previewThumbnailHeight: attachment.preview_thumbnail_height ?? null,
    previewGeneratedAt: attachment.preview_generated_at ?? null,
  };
}

function eventPartToFileAttachment(
  part: RenderablePart,
): FileAttachment | null {
  if (part.type === "attachment" || part.type === "artifact") {
    return {
      attachmentId:
        part.type === "attachment" ? (part.attachment_id ?? null) : null,
      uri: part.uri,
      mediaType: part.media_type,
      size: part.size,
      name: part.name,
      textPreview: part.type === "attachment" ? part.text_preview : null,
      availability:
        part.type === "attachment"
          ? (part.availability ?? "available")
          : (part.status ?? "available"),
      previewTitle:
        part.type === "attachment" ? (part.preview_title ?? null) : null,
      previewThumbnailUri:
        part.type === "attachment"
          ? (part.preview_thumbnail_uri ?? null)
          : null,
      previewThumbnailMediaType:
        part.type === "attachment"
          ? (part.preview_thumbnail_media_type ?? null)
          : null,
      previewThumbnailWidth:
        part.type === "attachment"
          ? (part.preview_thumbnail_width ?? null)
          : null,
      previewThumbnailHeight:
        part.type === "attachment"
          ? (part.preview_thumbnail_height ?? null)
          : null,
      previewGeneratedAt:
        part.type === "attachment" ? (part.preview_generated_at ?? null) : null,
    };
  }
  if (part.type === "file") {
    return {
      uri: `model-file:${part.model_file_id}`,
      mediaType: part.media_type,
      size: part.size ?? 0,
      name: part.name ?? part.model_file_id,
      textPreview: part.caption ?? part.alt_text ?? null,
    };
  }
  return null;
}

function eventContentText(output: string | RenderablePart[]): string {
  if (typeof output === "string") {
    return output;
  }
  return output
    .flatMap((part) => {
      if (
        part.type === "text" ||
        part.type === "output_text" ||
        part.type === "input_text"
      ) {
        return [part.text];
      }
      return [];
    })
    .join("\n");
}

function eventContentAttachments(
  output: string | RenderablePart[],
): FileAttachment[] {
  if (typeof output === "string") {
    return [];
  }
  return output.flatMap((part) => {
    const attachment = eventPartToFileAttachment(part);
    return attachment ? [attachment] : [];
  });
}

function providerToolCallStatusFromPayload(
  payload: unknown,
): "completed" | "failed" | "running" | "unknown" {
  const status = isRecord(payload) ? payload.status : null;
  switch (status) {
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isChatHistoryEvent(event: unknown): event is ChatHistoryEvent {
  return (
    isRecord(event) && typeof event.kind === "string" && isRecord(event.payload)
  );
}

function isChatEventWire(value: unknown): value is ChatEvent {
  if (!isRecord(value)) {
    return false;
  }
  if (typeof value.type === "string") {
    return true;
  }
  return typeof value.kind === "string" && isRecord(value.payload);
}

/** wire usage payload UI message usage record with convert.. */
function toUsageRecord(
  usage: WireTokenUsage | null,
): Record<string, unknown> | null {
  if (usage === null) {
    return null;
  }
  return {
    prompt_tokens: usage.prompt_tokens,
    completion_tokens: usage.completion_tokens,
    total_tokens: usage.total_tokens,
    cached_tokens: usage.cached_tokens,
    cache_creation_tokens: usage.cache_creation_tokens,
    reasoning_tokens: usage.reasoning_tokens,
  };
}

/** message upsert */
function upsertMessage(prev: ChatMessage[], msg: ChatMessage): ChatMessage[] {
  const idx = prev.findIndex((m) => m.id === msg.id);
  if (idx !== -1) {
    const next = [...prev];
    next[idx] = msg;
    return next;
  }
  return [...prev, msg];
}

function applySubagentEvent(
  prev: ChatMessage[],
  event: ChatHistoryEvent,
): ChatMessage[] {
  switch (event.kind) {
    case "user_message": {
      const content = eventContentText(event.payload.content);
      const attachments = [
        ...event.payload.attachments.map(eventAttachmentToFileAttachment),
        ...eventContentAttachments(event.payload.content),
      ];
      return upsertMessage(prev, {
        id: event.id,
        role: "user",
        content,
        createdAt: event.created_at,
        status: "complete",
        ...(attachments.length > 0 ? { attachments } : {}),
      });
    }

    case "action_message": {
      return upsertMessage(prev, {
        id: event.id,
        role: "user",
        content: event.payload.message,
        createdAt: event.created_at,
        status: "complete",
      });
    }

    case "assistant_message": {
      const content = eventContentText(event.payload.content);
      const attachments = [
        ...event.payload.attachments.map(eventAttachmentToFileAttachment),
        ...eventContentAttachments(event.payload.content),
      ];
      return upsertMessage(prev, {
        id: event.id,
        role: "assistant",
        content,
        createdAt: event.created_at,
        status: "complete",
        ...(attachments.length > 0 ? { attachments } : {}),
      });
    }

    case "reasoning": {
      const reasoningSummary = event.payload.summary ?? event.payload.text;
      return upsertMessage(prev, {
        id: event.id,
        role: "assistant",
        content: null,
        createdAt: event.created_at,
        status: "complete",
        ...(reasoningSummary != null ? { reasoningSummary } : {}),
      });
    }

    case "client_tool_call": {
      const toolCall: ActiveToolCall = {
        id: event.payload.call_id,
        callId: event.payload.call_id,
        name: event.payload.name,
        arguments: event.payload.arguments,
        status: "running",
      };
      return applyFunctionCallItem(prev, toolCall, event.id, event.created_at);
    }

    case "provider_tool_call": {
      return applyProviderToolCallItem(
        prev,
        {
          id: event.payload.call_id,
          callId: event.payload.call_id,
          name: event.payload.name,
          arguments: event.payload.arguments ?? "",
          status: providerToolCallStatusFromPayload(event.payload),
        },
        event.id,
        event.created_at,
      );
    }

    case "client_tool_result": {
      return applyFunctionCallOutput(prev, {
        callId: event.payload.call_id,
        content: eventContentText(event.payload.output),
        status: event.payload.status,
        attachments: [
          ...event.payload.attachments.map(eventAttachmentToFileAttachment),
          ...eventContentAttachments(event.payload.output),
        ],
      });
    }

    case "turn_marker": {
      const turnUsage = toUsageRecord(event.payload.usage ?? null);
      return upsertMessage(prev, {
        id: event.id,
        role: "turn_complete",
        content: null,
        createdAt: event.created_at,
        status: "complete",
        usage: turnUsage,
      });
    }

    case "run_marker": {
      if (event.payload.status !== "completed") {
        return prev;
      }
      return upsertMessage(prev, {
        id: event.id,
        role: "run_complete",
        content: null,
        createdAt: event.created_at,
        status: "complete",
      });
    }

    case "system_error": {
      return [
        ...prev,
        {
          id: event.id,
          role: "error",
          content: event.payload.content,
          createdAt: event.created_at,
          status: "complete",
        },
      ];
    }

    case "compaction_summary": {
      return upsertMessage(prev, {
        id: event.id,
        role: "compaction",
        content: event.payload.content,
        createdAt: event.created_at,
        status: "complete",
      });
    }

    case "compaction_marker": {
      if (event.payload.status === "started") {
        return upsertMessage(prev, {
          id: event.id,
          role: "compaction_started",
          content: event.payload.reason ?? null,
          createdAt: event.created_at,
          status: "complete",
        });
      }
      return upsertMessage(prev, {
        id: event.id,
        role: "error",
        content: event.payload.error ?? "Compaction failed.",
        createdAt: event.created_at,
        status: "complete",
      });
    }

    case "provider_tool_result":
    case "subagent_start":
    case "subagent_end":
    case "goal_continuation":
    case "goal_updated":
    case "goal_briefing":
    case "interrupted":
    case "system_reminder":
    case "unknown_adapter_output": {
      return prev;
    }
  }
}

function mapSubagentEvents(events: readonly unknown[]): ChatMessage[] {
  return events.reduce<ChatMessage[]>(
    (messages, event) =>
      isChatHistoryEvent(event)
        ? applySubagentEvent(messages, event)
        : messages,
    [],
  );
}

interface UseSubagentSessionOptions {
  /** Subagent session ID (nullwhen inactive) */
  sessionId: string | null;
  /** Subagent run duringwhether whether */
  isRunning: boolean;
}

interface UseSubagentSessionReturn {
  /** message list */
  messages: ChatMessage[];
  /** history loading */
  isLoading: boolean;
  /** older messages more existstext */
  hasMore: boolean;
  /** older messages loading */
  isLoadingMore: boolean;
  /** older messages  withtext callback */
  onLoadMore: () => void;
}

export function useSubagentSession({
  sessionId,
  isRunning,
}: UseSubagentSessionOptions): UseSubagentSessionReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const utils = trpc.useUtils();

  // modal closed when (sessionId → null) invalidate cache
  const prevSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevSessionIdRef.current;
    prevSessionIdRef.current = sessionId;
    if (prev && !sessionId) {
      void utils.chat.listSessionEvents.invalidate({ sessionId: prev });
    }
  }, [sessionId, utils.chat.listSessionEvents]);

  // session change when history fetch
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setHasMore(false);
      return;
    }

    setIsLoading(true);
    void utils.chat.listSessionEvents
      .fetch({ sessionId, limit: 100 })
      .then((data) => {
        setMessages(
          mapSubagentEvents([
            ...data.history.items,
            ...data.live.partial_history.items.filter(
              (item) => item.kind !== "provider_tool_call",
            ),
          ]),
        );
        setHasMore(data.history.has_more);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [sessionId, utils.chat.listSessionEvents]);

  // older messages  withtext (cursor based pagination)
  const onLoadMore = useCallback(() => {
    if (!sessionId || isLoadingMore || !hasMore) {
      return;
    }

    setIsLoadingMore(true);
    const firstMessage = messages[0];
    if (!firstMessage) {
      setIsLoadingMore(false);
      return;
    }

    // "msgId:tcId" text in original message ID extract
    const rawId = firstMessage.id;
    const colonIdx = rawId.indexOf(":");
    const before = colonIdx !== -1 ? rawId.slice(0, colonIdx) : rawId;

    void utils.chat.listSessionEvents
      .fetch({ sessionId, limit: 100, before })
      .then((data) => {
        const older = mapSubagentEvents(data.history.items);
        setMessages((prev) => [...older, ...prev]);
        setHasMore(data.history.has_more);
      })
      .finally(() => {
        setIsLoadingMore(false);
      });
  }, [
    sessionId,
    isLoadingMore,
    hasMore,
    messages,
    utils.chat.listSessionEvents,
  ]);

  // when running WebSocket connection
  const handleEvent = useCallback((event: ChatEvent) => {
    if (
      "type" in event &&
      event.type === "live_event_upserted" &&
      event.event.kind === "provider_tool_call"
    ) {
      return;
    }

    const eventCandidate =
      "type" in event &&
      (event.type === "history_event_appended" ||
        event.type === "live_event_upserted")
        ? event.event
        : event;

    if (isChatHistoryEvent(eventCandidate)) {
      setMessages((prev) => applySubagentEvent(prev, eventCandidate));
      return;
    }

    if (!("type" in event)) {
      return;
    }

    switch (event.type) {
      case "error": {
        const errorMsg: ChatMessage = {
          id: event.id,
          role: "error",
          content: event.item.content,
          createdAt: new Date().toISOString(),
          status: "complete",
        };
        setMessages((prev) => [...prev, errorMsg]);
        break;
      }

      case "turn_complete": {
        const turnUsage = toUsageRecord(event.item.usage);
        setMessages((prev) =>
          upsertMessage(prev, {
            id: event.id,
            role: "turn_complete",
            content: null,
            createdAt: new Date().toISOString(),
            status: "complete",
            usage: turnUsage,
          }),
        );
        break;
      }

      case "run_complete": {
        if ("item" in event) {
          setMessages((prev) =>
            upsertMessage(prev, {
              id: event.id,
              role: "run_complete",
              content: null,
              createdAt: new Date().toISOString(),
              status: "complete",
            }),
          );
        }
        break;
      }

      case "run_stopped": {
        break;
      }

      default:
        break;
    }
  }, []);

  useEffect(() => {
    if (!sessionId || !isRunning) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      return;
    }

    let cancelled = false;

    // always fresh ticket requiredso with textwhen invalidate after fetch
    void utils.chat.getConnectionInfo
      .invalidate()
      .then(() => utils.chat.getConnectionInfo.fetch())
      .then((info) => {
        if (cancelled || !info.wsUrl || !info.ticket) {
          return;
        }

        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const url = `${info.wsUrl}/chat/v1/sessions/${encodeURIComponent(sessionId)}?ticket=${encodeURIComponent(info.ticket)}&timezone=${encodeURIComponent(tz)}`;
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onmessage = (e: MessageEvent) => {
          if (typeof e.data !== "string") {
            return;
          }
          try {
            const raw: unknown = JSON.parse(e.data);
            if (!isChatEventWire(raw)) {
              return;
            }
            handleEvent(raw);
          } catch {
            console.error("Subagent WebSocket message parsing failed:", e.data);
          }
        };

        ws.onclose = () => {
          wsRef.current = null;
        };
      });

    return () => {
      cancelled = true;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [sessionId, isRunning, handleEvent, utils.chat.getConnectionInfo]);

  return { messages, isLoading, hasMore, isLoadingMore, onLoadMore };
}
