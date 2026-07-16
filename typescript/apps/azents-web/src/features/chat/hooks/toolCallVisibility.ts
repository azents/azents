import type { ChatTimelineState } from "../types";

/** Keep unmatched durable tool calls visible only while following an active Run. */
export function shouldRenderIncompleteDurableToolCalls(
  timelineState: ChatTimelineState,
  sessionRunState: "idle" | "running",
): boolean {
  return (
    timelineState.type === "LATEST_FOLLOWING" && sessionRunState === "running"
  );
}
