import type { ChatMessage, FileAttachment, ProviderToolCall } from "../types";

interface ProviderToolCallOutput {
  callId: string;
  name: string;
  output: string;
  status: ProviderToolCall["status"];
  attachments: FileAttachment[];
  fallbackMessageId: string;
  createdAt: string;
  messageStatus: ChatMessage["status"];
}

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

export function applyProviderToolCallOutput(
  prev: ChatMessage[],
  result: ProviderToolCallOutput,
): ChatMessage[] {
  const messageIndex = prev.findIndex((message) =>
    message.providerToolCalls?.some(
      (toolCall) =>
        toolCall.callId === result.callId || toolCall.id === result.callId,
    ),
  );
  if (messageIndex < 0) {
    return applyProviderToolCallItem(
      prev,
      {
        id: result.callId,
        callId: result.callId,
        name: result.name,
        arguments: "",
        status: result.status,
        output: result.output,
        attachments: result.attachments,
      },
      result.fallbackMessageId,
      result.createdAt,
      result.messageStatus,
    );
  }
  return prev.map((message, index) =>
    index === messageIndex
      ? {
          ...message,
          providerToolCalls: message.providerToolCalls?.map((toolCall) =>
            toolCall.callId === result.callId || toolCall.id === result.callId
              ? {
                  ...toolCall,
                  status: result.status,
                  output: result.output,
                  attachments: result.attachments,
                }
              : toolCall,
          ),
        }
      : message,
  );
}
