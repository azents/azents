import type { AppRouter } from "../../../trpc/routers/_app";
import type {
  AgentWorkspaceDirectoryResponse,
  AgentWorkspaceEntryResponse,
  AgentWorkspaceFileResponse,
  AgentWorkspaceManifestResponse,
  SessionWorkspaceProjectRegistrationRequestResponse,
  SessionWorkspaceProjectResponse,
} from "@azents/public-client";
import type { inferRouterOutputs } from "@trpc/server";

export type AgentWorkspaceServerState =
  inferRouterOutputs<AppRouter>["chat"]["getAgentWorkspace"];

export type WorkspaceEntry = {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number | null;
  mediaType: string | null;
  modifiedAt: string | null;
};

export type WorkspaceManifest = {
  root: string;
  cwd: string;
  entries: WorkspaceEntry[];
};

export type WorkspaceFile = {
  path: string;
  mediaType: string;
  size: number;
  text: string | null;
  truncated: boolean;
};

export type WorkspacePathResult =
  | { type: "DIRECTORY"; path: string; entries: WorkspaceEntry[] }
  | { type: "FILE"; file: WorkspaceFile };

export type WorkspaceFileState =
  | { type: "IDLE" }
  | { type: "LOADING"; path: string }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; file: WorkspaceFile };

export type WorkspaceProjectPanelState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      projects: SessionWorkspaceProjectResponse[];
      registrationRequests: SessionWorkspaceProjectRegistrationRequestResponse[];
      registerProjectPath: string;
      isRegisteringProject: boolean;
      registerProjectError: string | null;
      pendingApproveRequestId: string | null;
      pendingRejectRequestId: string | null;
      pendingDeleteProjectId: string | null;
    };

export type WorkspacePanelState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "SERVER";
      server: AgentWorkspaceServerState;
      manifest: WorkspaceManifest | null;
      directory: { path: string; entries: WorkspaceEntry[] };
      directoryEntriesByPath: Record<string, WorkspaceEntry[]>;
      fileState: WorkspaceFileState;
      selectedFilePath: string | null;
      isRefreshing: boolean;
      isStarting: boolean;
      isStopping: boolean;
      isResetting: boolean;
    };

export function mapWorkspaceEntry(
  entry: AgentWorkspaceEntryResponse,
): WorkspaceEntry {
  return {
    name: entry.name,
    path: entry.path,
    kind: entry.kind,
    size: entry.size ?? null,
    mediaType: entry.media_type ?? null,
    modifiedAt: entry.modified_at ?? null,
  };
}

export function mapWorkspaceManifest(
  manifest: AgentWorkspaceManifestResponse,
): WorkspaceManifest {
  return {
    root: manifest.root,
    cwd: manifest.cwd,
    entries: manifest.entries.map(mapWorkspaceEntry),
  };
}

export function mapWorkspacePathResult(
  result: AgentWorkspaceDirectoryResponse | AgentWorkspaceFileResponse,
): WorkspacePathResult {
  switch (result.type) {
    case "DIRECTORY":
      return {
        type: "DIRECTORY",
        path: result.path,
        entries: result.entries.map(mapWorkspaceEntry),
      };
    case "FILE":
      return {
        type: "FILE",
        file: {
          path: result.path,
          mediaType: result.media_type,
          size: result.size,
          text: result.text ?? null,
          truncated: result.truncated,
        },
      };
  }
}
