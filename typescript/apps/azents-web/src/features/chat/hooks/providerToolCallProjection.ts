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
 * Provider-hosted tool calls render independently from Azents client-tool pairs.
 * The provider call event itself is the durable presentation unit.
 */
export function providerToolCallStatusFromPayload(
  payloadStatus: unknown,
  messageStatus: ChatMessage["status"],
): ProviderToolCall["status"] {
  switch (payloadStatus) {
    case "completed":
    case "failed":
    case "running":
      return payloadStatus;
    default:
      return messageStatus === "partial" ? "running" : "unknown";
  }
}

export function applyProviderToolCallItem(
  prev: ChatMessage[],
  providerToolCall: ProviderToolCall,
  fallbackMsgId: string,
  createdAt: string,
  messageStatus: ChatMessage["status"] = "complete",
): ChatMessage[] {
  const semanticCallId = providerToolCall.callId ?? providerToolCall.id;
  const finalMsg: ChatMessage = {
    id: fallbackMsgId,
    role: "assistant",
    content: null,
    createdAt,
    status: messageStatus,
    providerToolCalls: [providerToolCall],
  };
  const idx = prev.findIndex(
    (message) =>
      message.id === fallbackMsgId ||
      message.providerToolCalls?.some(
        (toolCall) =>
          toolCall.callId === semanticCallId || toolCall.id === semanticCallId,
      ),
  );
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
