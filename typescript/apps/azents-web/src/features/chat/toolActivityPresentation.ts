import type { ActiveToolCall, ChatMessage, ProviderToolCall } from "./types";

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

export interface ToolActivityGroup {
  id: string;
  firstMessageId: string;
  startMessageIndex: number;
  endMessageIndex: number;
  calls: ToolActivityCall[];
  turnCount: number;
  reasoningSummaries: string[];
  compactionCount: number;
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

interface MutableToolActivityGroup extends ToolActivityGroup {
  pendingNextTurn: boolean;
}

function messageToolCalls(message: ChatMessage): ToolActivityCall[] {
  const clientCalls = (message.toolCalls ?? []).map(
    (toolCall): ClientToolActivityCall => ({
      type: "client",
      messageId: message.id,
      toolCall,
    }),
  );
  const providerCalls = (message.providerToolCalls ?? []).map(
    (toolCall): ProviderToolActivityCall => ({
      type: "provider",
      messageId: message.id,
      toolCall,
    }),
  );
  return [...clientCalls, ...providerCalls];
}

function activityId(call: ToolActivityCall): string {
  const callId = call.toolCall.callId ?? call.toolCall.id;
  return `tool-activity:${callId}`;
}

function hasVisibleDelivery(message: ChatMessage): boolean {
  return (
    (message.content?.trim().length ?? 0) > 0 ||
    (message.attachments?.length ?? 0) > 0
  );
}

function withoutToolActivity(message: ChatMessage): ChatMessage {
  const { toolCalls, providerToolCalls, reasoningSummary, ...delivery } =
    message;
  void toolCalls;
  void providerToolCalls;
  void reasoningSummary;
  return delivery;
}

function isHiddenMarker(message: ChatMessage): boolean {
  return (
    message.role === "system" ||
    message.role === "tool" ||
    message.role === "turn_complete" ||
    message.role === "run_complete" ||
    message.role === "compaction_started"
  );
}

export function projectChatPresentationItems(
  messages: ChatMessage[],
  actionBoundaryMessageIds: ReadonlySet<string> = new Set<string>(),
): ChatPresentationItem[] {
  const items: ChatPresentationItem[] = [];
  let current: MutableToolActivityGroup | null = null;

  function flushActivity(): void {
    if (current === null) {
      return;
    }
    const activity: ToolActivityGroup = {
      id: current.id,
      firstMessageId: current.firstMessageId,
      startMessageIndex: current.startMessageIndex,
      endMessageIndex: current.endMessageIndex,
      calls: current.calls,
      turnCount: current.turnCount,
      reasoningSummaries: current.reasoningSummaries,
      compactionCount: current.compactionCount,
      usage: current.usage,
    };
    items.push({
      type: "activity",
      id: activity.id,
      activity,
    });
    current = null;
  }

  function appendCalls(
    calls: ToolActivityCall[],
    message: ChatMessage,
    messageIndex: number,
  ): void {
    const firstCall = calls[0];
    if (!firstCall) {
      return;
    }
    if (current === null) {
      current = {
        id: activityId(firstCall),
        firstMessageId: message.id,
        startMessageIndex: messageIndex,
        endMessageIndex: messageIndex,
        calls: [],
        turnCount: 1,
        reasoningSummaries: [],
        compactionCount: 0,
        usage: null,
        pendingNextTurn: false,
      };
    } else if (current.pendingNextTurn) {
      current.turnCount += 1;
      current.pendingNextTurn = false;
    }
    current.calls.push(...calls);
    current.endMessageIndex = messageIndex;
    if (message.reasoningSummary?.trim()) {
      current.reasoningSummaries.push(message.reasoningSummary);
    }
  }

  function appendMessage(message: ChatMessage, messageIndex: number): void {
    items.push({
      type: "message",
      id: `message:${message.id}`,
      message,
      messageIndex,
    });
  }

  messages.forEach((message, messageIndex) => {
    if (actionBoundaryMessageIds.has(message.id)) {
      flushActivity();
    }

    if (message.role === "turn_complete") {
      if (current !== null) {
        current.pendingNextTurn = true;
        current.usage = message.usage ?? null;
      }
      return;
    }

    if (message.role === "run_complete") {
      flushActivity();
      return;
    }

    if (message.role === "compaction_started") {
      return;
    }

    if (message.role === "compaction") {
      if (current !== null) {
        current.compactionCount += 1;
        current.endMessageIndex = messageIndex;
        return;
      }
      appendMessage(message, messageIndex);
      return;
    }

    const calls = messageToolCalls(message);
    if (calls.length > 0) {
      appendCalls(calls, message, messageIndex);
      if (hasVisibleDelivery(message)) {
        flushActivity();
        appendMessage(withoutToolActivity(message), messageIndex);
      }
      return;
    }

    if (
      current !== null &&
      message.role === "assistant" &&
      !hasVisibleDelivery(message)
    ) {
      if (message.reasoningSummary?.trim()) {
        current.reasoningSummaries.push(message.reasoningSummary);
        current.endMessageIndex = messageIndex;
      }
      return;
    }

    flushActivity();
    if (!isHiddenMarker(message)) {
      appendMessage(message, messageIndex);
    }
  });

  flushActivity();
  return items;
}
