import type { KnownToolAction } from "./knownToolPresentation.ts";
import type { RoutineToolAction } from "./routineToolPresentation.ts";
import type { ActiveToolCall } from "@azents/session-core/types";

export type ToolCallActionMessageKey =
  | `action.${KnownToolAction}`
  | `actionRunning.${KnownToolAction}`
  | `actionFailed.${RoutineToolAction}`
  | `actionCancelled.${RoutineToolAction}`;

export function toolCallActionMessageKey(
  action: KnownToolAction,
  status: ActiveToolCall["status"],
): ToolCallActionMessageKey {
  switch (action) {
    case "createRoutine":
    case "listRoutines":
    case "inspectRoutine":
    case "updateRoutine":
    case "deleteRoutine":
    case "readRoutineContext":
    case "recordRoutineResult":
      if (status === "failed") {
        return `actionFailed.${action}`;
      }
      if (status === "cancelled" || status === "interrupted") {
        return `actionCancelled.${action}`;
      }
  }
  return status === "preparing" || status === "running"
    ? `actionRunning.${action}`
    : `action.${action}`;
}
