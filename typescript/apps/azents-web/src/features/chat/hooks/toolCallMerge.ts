import type {
  ActiveToolCall,
  ChatMessage,
  FileAttachment,
  ToolResultStatus,
} from "../types";

/** FCO when arrives matched complete FC  to injectto result */
export interface FunctionCallOutputUpdate {
  callId: string;
  content: string;
  attachments: FileAttachment[];
  status: ToolResultStatus;
}

/**
 * complete function_call_item  text complete tool item  with reflects..
 *
 * partial/live item and complete/durable item  different different item so with call_id  with
 * existing partial tool card  texti updatedoes not.. partial remove
 * live_event_removed event is responsible..
 */
export function applyFunctionCallItem(
  prev: ChatMessage[],
  toolCall: ActiveToolCall,
  fallbackMsgId: string,
  createdAt: string,
  messageStatus: ChatMessage["status"] = "complete",
): ChatMessage[] {
  const finalMsg: ChatMessage = {
    id: fallbackMsgId,
    role: "assistant",
    content: null,
    createdAt,
    status: messageStatus,
    toolCalls: [toolCall],
  };
  const idx = prev.findIndex((m) => m.id === fallbackMsgId);
  if (idx !== -1) {
    const next = [...prev];
    next[idx] = finalMsg;
    return next;
  }
  return [...prev, finalMsg];
}

export function applyFunctionCallOutput(
  prev: ChatMessage[],
  update: FunctionCallOutputUpdate,
): ChatMessage[] {
  for (let i = prev.length - 1; i >= 0; i--) {
    const msg = prev[i];
    if (
      !msg ||
      msg.role !== "assistant" ||
      msg.status !== "complete" ||
      !msg.toolCalls
    ) {
      continue;
    }
    const tcIdx = msg.toolCalls.findIndex(
      (tc) => tc.id === update.callId || tc.callId === update.callId,
    );
    if (tcIdx === -1) {
      continue;
    }
    const tc = msg.toolCalls[tcIdx];
    if (!tc) {
      continue;
    }
    const next = [...prev];
    const updatedToolCalls = [...msg.toolCalls];
    updatedToolCalls[tcIdx] = {
      ...tc,
      status: update.status,
      result: update.content,
      ...(update.attachments.length > 0
        ? { attachments: update.attachments }
        : {}),
    };
    next[i] = { ...msg, toolCalls: updatedToolCalls };
    return next;
  }
  return prev;
}
