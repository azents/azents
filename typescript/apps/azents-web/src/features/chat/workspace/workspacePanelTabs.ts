import type { SessionPanelView } from "../session-panel/sessionPanel";
import type { WorkspacePanelTab } from "./types";

export type WorkspacePanelInvalidationTarget =
  | "agent"
  | "metrics"
  | "projects"
  | "runtime"
  | "services"
  | "session"
  | "workspace"
  | "workspaceManifest"
  | "workspacePaths"
  | "workspacePathStats";

export function workspacePanelTabForSessionPanelView(
  view: SessionPanelView,
): WorkspacePanelTab {
  switch (view) {
    case "services":
      return "services";
    case "metrics":
      return "metrics";
    case "runtime":
      return "settings";
    default:
      return "workspace";
  }
}

export function workspacePanelTabInvalidationPlan(
  tab: WorkspacePanelTab,
): readonly WorkspacePanelInvalidationTarget[] {
  switch (tab) {
    case "workspace":
      return [
        "runtime",
        "workspace",
        "workspacePaths",
        "workspacePathStats",
        "projects",
        "workspaceManifest",
      ];
    case "services":
      return ["runtime", "services"];
    case "metrics":
      return ["runtime", "metrics"];
    case "settings":
      return ["agent", "session", "runtime", "workspace"];
  }
}
