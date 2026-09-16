import type { SessionPanelView } from "./sessionPanel";

export type SessionPanelInvalidationTarget =
  "channels" | "context" | "subagents" | "terminal";

export function sessionPanelInvalidationPlan(
  view: SessionPanelView,
): readonly SessionPanelInvalidationTarget[] {
  switch (view) {
    case "context":
    case "system-prompt":
    case "raw-events":
      return ["context"];
    case "subagents":
      return ["subagents"];
    case "channels":
      return ["channels"];
    case "scheduled-tasks":
      return [];
    case "terminal":
      return ["terminal"];
    case "files":
    case "services":
    case "runtime":
    case "metrics":
      return [];
  }
}
