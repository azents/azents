import type { ChatEventResponse } from "@azents/public-client";

export function isLivePartialHistoryEvent(
  kind: ChatEventResponse["kind"],
  inputBuffer: boolean,
): boolean {
  if (inputBuffer) {
    return false;
  }
  switch (kind) {
    case "assistant_message":
    case "reasoning":
    case "client_tool_call":
    case "provider_tool_call":
    case "agent_message":
    case "goal_continuation":
      return true;
    default:
      return false;
  }
}
