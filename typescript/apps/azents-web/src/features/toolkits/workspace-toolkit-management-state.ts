import { usesToolkitCreationWizard } from "../../shared/toolkits/toolkit-form-lifecycle.ts";
import type { ToolkitConfigResponse } from "@azents/public-client";

export type WorkspaceToolkitEditor =
  | { type: "CLOSED" }
  | { type: "CATALOG" }
  | { type: "DETAIL"; toolkitId: string }
  | { type: "CREATE"; toolkitType: string }
  | { type: "EDIT"; toolkitId: string };

export type WorkspaceToolkitWriteState =
  | { type: "IDLE" }
  | { type: "PENDING"; toolkitId: string }
  | { type: "ERROR"; toolkitId: string; message: string };

export function toolkitNeedsReauthorization(
  toolkit: ToolkitConfigResponse,
): boolean {
  return (
    toolkit.authorization_state?.status === "reconnect_required" ||
    toolkit.oauth_connection?.status === "reconnect_required"
  );
}

export function canToggleWorkspaceToolkit(
  toolkit: ToolkitConfigResponse,
  enabled: boolean,
): boolean {
  return !(
    enabled && toolkit.authorization_state?.status === "reconnect_required"
  );
}

export function workspaceToolkitEditorPending(
  editor: WorkspaceToolkitEditor,
  setupPending: boolean,
  publicationPending: boolean,
): boolean {
  return editor.type === "CREATE" &&
    usesToolkitCreationWizard(editor.toolkitType)
    ? publicationPending
    : setupPending;
}

/** Completion of an old, unmounted form must not close a newer editor. */
export function completedWorkspaceToolkitEditor(
  current: WorkspaceToolkitEditor,
  completed: WorkspaceToolkitEditor,
): WorkspaceToolkitEditor {
  if (current !== completed) {
    return current;
  }
  if (
    current.type === "CREATE" &&
    completed.type === "CREATE" &&
    current.toolkitType === completed.toolkitType
  ) {
    return { type: "CLOSED" };
  }
  if (
    current.type === "EDIT" &&
    completed.type === "EDIT" &&
    current.toolkitId === completed.toolkitId
  ) {
    return { type: "DETAIL", toolkitId: current.toolkitId };
  }
  return current;
}

/** Fence every completion effect, including pending flags and the abandon capability. */
export function completeWorkspaceToolkitSetup(
  current: WorkspaceToolkitEditor,
  completed: WorkspaceToolkitEditor,
  commit: (next: WorkspaceToolkitEditor) => void,
): void {
  const next = completedWorkspaceToolkitEditor(current, completed);
  if (next !== current) {
    commit(next);
  }
}
