import type {
  ActiveToolCall,
  ChatMessage,
  FileAttachment,
  ProviderToolCall,
} from "./types";
import type { ChatEventResponse } from "@azents/public-client";

export interface ClientToolActivityCall {
  type: "client";
  messageId: string;
  toolCall: ActiveToolCall;
}

export interface ProviderToolActivityCall {
  type: "provider";
  messageId: string;
  toolCall: ProviderToolCall;
}

export type ToolActivityCall =
  | ClientToolActivityCall
  | ProviderToolActivityCall;

export type ActivityEventKind =
  | "reasoning"
  | "tool"
  | "skill"
  | "compaction"
  | "goal-control"
  | "other";

export interface ActivityCategory {
  key: string;
  label: string;
}

export interface ActivityEvent {
  id: string;
  kind: ActivityEventKind;
  message: ChatMessage | null;
  toolCall?: ToolActivityCall;
  category: ActivityCategory | null;
  status: "running" | "failed" | "complete";
}

export interface ToolActivityGroup {
  id: string;
  firstMessageId: string;
  startMessageIndex: number;
  endMessageIndex: number;
  events: ActivityEvent[];
  usage: Record<string, unknown> | null;
}

export interface ToolActivityPresentationItem {
  type: "activity";
  id: string;
  activity: ToolActivityGroup;
}

export interface MessagePresentationItem {
  type: "message";
  id: string;
  message: ChatMessage;
  messageIndex: number;
}

export type ChatPresentationItem =
  | ToolActivityPresentationItem
  | MessagePresentationItem;

interface TimelineEvent {
  id: string;
  event: ChatEventResponse;
  message: ChatMessage | null;
  activityEvent: ActivityEvent | null;
  boundary: boolean;
  hidden: boolean;
  usage: Record<string, unknown> | null;
}

type MutableToolActivityGroup = ToolActivityGroup;

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

function eventProjectionRoot(event: ChatEventResponse): string {
  return event.external_id?.split(":", 1)[0] ?? event.id;
}

function nativeArtifactItem(
  payload: Record<string, unknown>,
): Record<string, unknown> | null {
  const artifact = payload.native_artifact;
  if (!isRecord(artifact)) {
    return null;
  }
  const item = artifact.item;
  return isRecord(item) ? item : null;
}

function semanticKey(event: ChatEventResponse): string {
  const payload = event.payload;
  switch (event.kind) {
    case "client_tool_call":
      return `tool:${stringField(payload, "call_id") ?? event.id}`;
    case "client_tool_result":
      return `tool-result:${stringField(payload, "call_id") ?? event.id}`;
    case "provider_tool_call":
      return `provider-tool:${stringField(payload, "call_id") ?? event.id}`;
    case "reasoning": {
      const nativeId = nativeArtifactItem(payload);
      const itemId = nativeId === null ? null : stringField(nativeId, "id");
      return itemId === null
        ? `reasoning:event:${eventProjectionRoot(event)}`
        : `reasoning:native:${itemId}`;
    }
    default:
      return `event:${event.external_id ?? event.id}`;
  }
}

function messageIndex(messages: ChatMessage[], message: ChatMessage): number {
  const index = messages.indexOf(message);
  return index < 0 ? messages.length : index;
}

function messageForEvent(
  event: ChatEventResponse,
  messages: ChatMessage[],
): ChatMessage | null {
  const key = semanticKey(event);
  const direct = messages.find(
    (message) =>
      message.id === event.id || message.metadata?.event_render_key === key,
  );
  if (direct) {
    return direct;
  }

  const callId = stringField(event.payload, "call_id");
  if (callId === null) {
    return null;
  }
  return (
    messages.find(
      (message) =>
        message.toolCalls?.some(
          (toolCall) => toolCall.callId === callId || toolCall.id === callId,
        ) ||
        message.providerToolCalls?.some(
          (toolCall) => toolCall.callId === callId || toolCall.id === callId,
        ),
    ) ?? null
  );
}

function toolCallForEvent(
  event: ChatEventResponse,
  messages: ChatMessage[],
): ToolActivityCall | null {
  const callId = stringField(event.payload, "call_id");
  if (callId === null) {
    return null;
  }
  for (const message of messages) {
    const clientCall = message.toolCalls?.find(
      (toolCall) => toolCall.callId === callId || toolCall.id === callId,
    );
    if (clientCall) {
      return { type: "client", messageId: message.id, toolCall: clientCall };
    }
    const providerCall = message.providerToolCalls?.find(
      (toolCall) => toolCall.callId === callId || toolCall.id === callId,
    );
    if (providerCall) {
      return {
        type: "provider",
        messageId: message.id,
        toolCall: providerCall,
      };
    }
  }
  return null;
}

function attachmentsForToolCall(call: ToolActivityCall): FileAttachment[] {
  return call.toolCall.attachments ?? [];
}

function messageHasAttachments(message: ChatMessage | null): boolean {
  return (message?.attachments?.length ?? 0) > 0;
}

function activityCategoryForTool(call: ToolActivityCall): ActivityCategory {
  if (call.type === "client" && call.toolCall.toolkitSource) {
    return {
      key: `toolkit:${call.toolCall.toolkitSource.toolkit_config_id}`,
      label: call.toolCall.toolkitSource.toolkit_name,
    };
  }

  const name = call.toolCall.name;
  if (call.type === "provider") {
    switch (name) {
      case "web_search":
      case "file_search":
        return { key: "explore", label: "explore" };
      case "image_generation":
        return { key: "image", label: "image" };
      default:
        return { key: "other", label: "other" };
    }
  }

  switch (name) {
    case "read":
    case "grep":
    case "glob":
    case "web_search":
    case "search_memories":
    case "get_memory":
      return { key: "explore", label: "explore" };
    case "exec_command":
    case "write_stdin":
      return { key: "shell", label: "shell" };
    case "write":
    case "edit":
    case "apply_patch":
    case "delete":
      return { key: "edit", label: "edit" };
    case "import_file":
    case "present_file":
    case "read_image":
      return { key: "file", label: "file" };
    case "image_generation":
      return { key: "image", label: "image" };
    case "save_memory":
    case "delete_memory":
    case "list_memories":
      return { key: "memory", label: "memory" };
    case "create_goal":
    case "get_goal":
    case "update_goal":
    case "update_todo":
      return { key: "organize", label: "organize" };
    case "spawn_agent":
    case "followup_task":
    case "send_message":
    case "wait_agent":
    case "interrupt_agent":
    case "list_agents":
      return { key: "subagent", label: "subagent" };
    default:
      return { key: "other", label: "other" };
  }
}

function activityEventStatus(call: ToolActivityCall): ActivityEvent["status"] {
  if (
    call.toolCall.status === "running" ||
    (call.type === "client" && call.toolCall.status === "preparing")
  ) {
    return "running";
  }
  return call.toolCall.status === "failed" ? "failed" : "complete";
}

function timelineEvents(
  events: ChatEventResponse[],
  messages: ChatMessage[],
): TimelineEvent[] {
  const clientResults = new Map<string, ChatEventResponse>();
  const compactionSummaries = new Map<string, ChatEventResponse>();
  for (const event of events) {
    if (event.kind === "client_tool_result") {
      const callId = stringField(event.payload, "call_id");
      if (callId) {
        clientResults.set(callId, event);
      }
    }
    if (event.kind === "compaction_summary") {
      const compactionId = stringField(event.payload, "compaction_id");
      if (compactionId) {
        compactionSummaries.set(compactionId, event);
      }
    }
  }

  const providerKeys = new Set<string>();
  return events.flatMap((event): TimelineEvent[] => {
    const message = messageForEvent(event, messages);
    if (event.kind === "turn_marker") {
      const usage = isRecord(event.payload.usage) ? event.payload.usage : null;
      return [
        {
          id: event.id,
          event,
          message: null,
          activityEvent: null,
          boundary: false,
          hidden: true,
          usage,
        },
      ];
    }
    if (event.kind === "run_marker") {
      return [
        {
          id: event.id,
          event,
          message: null,
          activityEvent: null,
          boundary: true,
          hidden: true,
          usage: null,
        },
      ];
    }
    if (
      event.kind === "client_tool_result" ||
      event.kind === "compaction_summary"
    ) {
      return [];
    }
    if (event.kind === "provider_tool_call") {
      const key = semanticKey(event);
      if (providerKeys.has(key)) {
        return [];
      }
      providerKeys.add(key);
    }

    if (
      event.kind === "client_tool_call" ||
      event.kind === "provider_tool_call"
    ) {
      const call = toolCallForEvent(event, messages);
      const callId = stringField(event.payload, "call_id");
      const result = callId ? clientResults.get(callId) : null;
      const toolMessage = result
        ? (messageForEvent(result, messages) ?? message)
        : message;
      if (call === null) {
        return [];
      }
      const hasAttachments =
        messageHasAttachments(toolMessage) ||
        attachmentsForToolCall(call).length > 0;
      return [
        {
          id: event.id,
          event,
          message: toolMessage,
          activityEvent: {
            id: semanticKey(event),
            kind: "tool",
            message: toolMessage,
            toolCall: call,
            category: activityCategoryForTool(call),
            status: activityEventStatus(call),
          },
          boundary: hasAttachments,
          hidden: false,
          usage: null,
        },
      ];
    }

    if (event.kind === "reasoning") {
      return [
        {
          id: event.id,
          event,
          message,
          activityEvent: {
            id: semanticKey(event),
            kind: "reasoning",
            message,
            category: null,
            status: "complete",
          },
          boundary: false,
          hidden: false,
          usage: null,
        },
      ];
    }

    if (event.kind === "skill_loaded") {
      return [
        {
          id: event.id,
          event,
          message,
          activityEvent: {
            id: semanticKey(event),
            kind: "skill",
            message,
            category: { key: "skill", label: "skill" },
            status: "complete",
          },
          boundary: false,
          hidden: false,
          usage: null,
        },
      ];
    }

    if (event.kind === "compaction_marker") {
      const compactionId = stringField(event.payload, "compaction_id");
      const summary = compactionId
        ? compactionSummaries.get(compactionId)
        : null;
      const compactionMessage = summary
        ? messageForEvent(summary, messages)
        : message;
      return [
        {
          id: event.id,
          event,
          message: compactionMessage,
          activityEvent: {
            id: semanticKey(event),
            kind: "compaction",
            message: compactionMessage,
            category: null,
            status: event.payload.status === "failed" ? "failed" : "complete",
          },
          boundary: false,
          hidden: false,
          usage: null,
        },
      ];
    }

    if (event.kind === "goal_continuation" || event.kind === "goal_updated") {
      return [
        {
          id: event.id,
          event,
          message,
          activityEvent: {
            id: semanticKey(event),
            kind: "goal-control",
            message,
            category: { key: "organize", label: "organize" },
            status: "complete",
          },
          boundary: false,
          hidden: false,
          usage: null,
        },
      ];
    }

    if (
      event.kind === "system_reminder" ||
      event.kind === "unknown_adapter_output" ||
      event.kind === "action_execution_result"
    ) {
      return [
        {
          id: event.id,
          event,
          message: null,
          activityEvent: null,
          boundary: event.kind === "action_execution_result",
          hidden: true,
          usage: null,
        },
      ];
    }

    return [
      {
        id: event.id,
        event,
        message,
        activityEvent: null,
        boundary: true,
        hidden: message === null,
        usage: null,
      },
    ];
  });
}

export function projectChatPresentationItems(
  events: ChatEventResponse[],
  messages: ChatMessage[],
  actionBoundaryMessageIds: ReadonlySet<string> = new Set<string>(),
): ChatPresentationItem[] {
  const items: ChatPresentationItem[] = [];
  const representedMessageIds = new Set<string>();
  let current: MutableToolActivityGroup | null = null;

  function flushActivity(): void {
    if (current === null) {
      return;
    }
    items.push({ type: "activity", id: current.id, activity: current });
    current = null;
  }

  function appendMessage(message: ChatMessage): void {
    if (representedMessageIds.has(message.id)) {
      return;
    }
    representedMessageIds.add(message.id);
    items.push({
      type: "message",
      id: `message:${message.id}`,
      message,
      messageIndex: messageIndex(messages, message),
    });
  }

  for (const item of timelineEvents(events, messages)) {
    if (item.message && actionBoundaryMessageIds.has(item.message.id)) {
      flushActivity();
    }
    if (item.usage !== null && current !== null) {
      current.usage = item.usage;
    }
    if (item.activityEvent !== null && !item.boundary) {
      if (current === null) {
        const index = item.message ? messageIndex(messages, item.message) : 0;
        current = {
          id: `activity:${item.activityEvent.id}`,
          firstMessageId: item.message?.id ?? item.event.id,
          startMessageIndex: index,
          endMessageIndex: index,
          events: [],
          usage: null,
        };
      }
      current.events.push(item.activityEvent);
      if (item.message) {
        current.endMessageIndex = messageIndex(messages, item.message);
        representedMessageIds.add(item.message.id);
      }
      continue;
    }

    if (item.boundary) {
      flushActivity();
    }
    if (!item.hidden && item.message) {
      appendMessage(item.message);
    }
  }

  flushActivity();
  for (const message of messages) {
    if (!representedMessageIds.has(message.id)) {
      appendMessage(message);
    }
  }
  return items;
}
