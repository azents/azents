/**
 * ADT definitions for the workspaces feature
 */

// --- API response types (re-exported from the generated client) ---
export type { WorkspaceResponse } from "@azents/admin-client";

import type { WorkspaceResponse } from "@azents/admin-client";

// --- Form data types ---
export interface WorkspaceFormData {
  name: string;
  handle: string;
}

// --- Conversion functions ---

/** Convert an API response to form data */
export function workspaceToFormData(
  workspace: WorkspaceResponse,
): WorkspaceFormData {
  return {
    name: workspace.name,
    handle: workspace.handle,
  };
}

/** Convert form data to a create API request */
export function formDataToCreateRequest(data: WorkspaceFormData): {
  name: string;
  handle: string;
} {
  return {
    name: data.name,
    handle: data.handle,
  };
}

/** Convert form data to an update API request */
export function formDataToUpdateRequest(data: WorkspaceFormData): {
  name: string;
  handle: string;
} {
  return {
    name: data.name,
    handle: data.handle,
  };
}

// --- ADT state types ---

/** Workspace list state */
export type WorkspaceListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; workspaces: WorkspaceResponse[] };

/** Workspace detail state */
export type WorkspaceDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; handle: string }
  | { type: "ERROR"; handle: string; message: string }
  | { type: "EDITING"; workspace: WorkspaceResponse | null; isNew: boolean }
  | { type: "SAVING"; workspace: WorkspaceResponse | null; isNew: boolean };
