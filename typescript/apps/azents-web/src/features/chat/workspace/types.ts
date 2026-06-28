import type {
  AgentWorkspaceDirectoryResponse,
  AgentWorkspaceEntryResponse,
  AgentWorkspaceFileResponse,
  AgentWorkspaceManifestResponse,
  AgentWorkspaceResponse,
  AgentWorkspaceStatResponse,
  SessionWorkspaceProjectRegistrationRequestResponse,
  SessionWorkspaceProjectResponse,
} from "@azents/public-client";

export type AgentWorkspaceServerState = AgentWorkspaceResponse;

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

export type WorkspacePathStat = {
  path: string;
  name: string;
  kind: "file" | "directory" | "symlink" | "other" | "missing";
  size: number | null;
  mediaType: string | null;
  modifiedAt: string | null;
  symlink: boolean;
  realPath: string | null;
  resolvedKind: "file" | "directory" | "symlink" | "other" | "missing" | null;
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
      workspaceView: "browser" | "preview" | "info";
      selectedFilePath: string | null;
      selectedEntry: WorkspaceEntry | null;
      selectedPaths: string[];
      inspectorState:
        | { type: "IDLE" }
        | { type: "LOADING"; path: string }
        | { type: "ERROR"; message: string }
        | { type: "LOADED"; stat: WorkspacePathStat };
      isRefreshing: boolean;
      isMutating: boolean;
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

export function mapWorkspacePathStat(
  result: AgentWorkspaceStatResponse,
): WorkspacePathStat {
  return {
    path: result.path,
    name: result.name,
    kind: result.kind,
    size: result.size ?? null,
    mediaType: result.media_type ?? null,
    modifiedAt: result.modified_at ?? null,
    symlink: result.symlink,
    realPath: result.real_path ?? null,
    resolvedKind: result.resolved_kind ?? null,
  };
}
