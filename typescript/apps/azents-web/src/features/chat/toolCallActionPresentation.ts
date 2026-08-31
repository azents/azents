import type { KnownToolAction } from "./knownToolPresentation.ts";
import type { ActiveToolCall } from "./types";

export type ToolCallActionMessageKey =
  `action.${KnownToolAction}` | `actionRunning.${KnownToolAction}`;

export function toolCallActionMessageKey(
  action: KnownToolAction,
  status: ActiveToolCall["status"],
): ToolCallActionMessageKey {
  return status === "preparing" || status === "running"
    ? `actionRunning.${action}`
    : `action.${action}`;
}
