import type { ChatMessage } from "../types";

export function hasLiveModelProgress(
  messages: readonly ChatMessage[],
): boolean {
  return messages.some(
    (message) => message.role === "assistant" && message.status === "partial",
  );
}
