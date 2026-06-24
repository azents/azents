import type { ChatMessage, ProviderToolCall } from "../types";

/**
 * Provider-native tool call  Azents client tool result and pair does not..
 * call event itself rendering unittext.
 */
export function applyProviderToolCallItem(
  prev: ChatMessage[],
  providerToolCall: ProviderToolCall,
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
    providerToolCalls: [providerToolCall],
  };
  const idx = prev.findIndex((m) => m.id === fallbackMsgId);
  if (idx !== -1) {
    const next = [...prev];
    next[idx] = finalMsg;
    return next;
  }
  return [...prev, finalMsg];
}
