import type {
  AgentWorkspaceDirectoryResponse,
  AgentWorkspaceEntryResponse,
  AgentWorkspaceFileResponse,
  AgentWorkspaceManifestResponse,
  AgentWorkspaceResponse,
  AgentWorkspaceStatResponse,
  ProjectBrowserEntryResponse,
  ProjectBrowserManifestResponse,
  SessionWorkspaceProjectRegistrationRequestResponse,
  SessionWorkspaceProjectResponse,
} from "@azents/public-client";

export type AgentWorkspaceServerState = AgentWorkspaceResponse;

export type WorkspaceEntryCapabilities = {
  open: boolean;
  removeProject: boolean;
  filesystemDelete: boolean;
  filesystemMove: boolean;
  filesystemRename: boolean;
};

export type WorkspaceEntryStatus = {
  value: "unchecked" | "available" | "missing" | "unavailable" | "error";
  detail: string | null;
  checkedAt: string | null;
  stale: boolean;
};

export type WorkspaceEntrySource =
  | { type: "workspace" }
  | { type: "session_project" | "preview_project"; projectId: string | null };

export type WorkspaceEntry = {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number | null;
  mediaType: string | null;
  modifiedAt: string | null;
  repositoryType?: "git" | null;
  capabilities?: WorkspaceEntryCapabilities | null;
  status?: WorkspaceEntryStatus | null;
  source?: WorkspaceEntrySource;
};

export type WorkspaceManifest = {
  root: string;
  cwd: string;
  entries: WorkspaceEntry[];
};

export type WorkspaceBrowserMode = "projects" | "all_files";

export type WorkspaceProjectBrowserManifest = {
  root: string;
  activeMode: WorkspaceBrowserMode;
  modes: {
    id: WorkspaceBrowserMode;
    label: string;
    default: boolean;
    rootPath: string | null;
  }[];
  entries: WorkspaceEntry[];
  emptyState: { title: string; description: string } | null;
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
      projectBrowserManifest?: WorkspaceProjectBrowserManifest | null;
      browserMode?: WorkspaceBrowserMode;
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
      projectEmptyState?: { title: string; description: string } | null;
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
    repositoryType: null,
    capabilities: null,
    status: null,
    source: { type: "workspace" },
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

export function mapProjectBrowserEntry(
  entry: ProjectBrowserEntryResponse,
): WorkspaceEntry {
  return {
    name: entry.name,
    path: entry.path,
    kind: entry.kind,
    size: null,
    mediaType: null,
    modifiedAt: null,
    repositoryType: entry.repository_type ?? null,
    capabilities: {
      open: entry.capabilities.open,
      removeProject: entry.capabilities.remove_project,
      filesystemDelete: entry.capabilities.filesystem_delete,
      filesystemMove: entry.capabilities.filesystem_move,
      filesystemRename: entry.capabilities.filesystem_rename,
    },
    status: {
      value: entry.status.value,
      detail: entry.status.detail ?? null,
      checkedAt: entry.status.checked_at ?? null,
      stale: entry.status.stale,
    },
    source: {
      type: entry.source.type,
      projectId: entry.source.project_id ?? null,
    },
  };
}

export function mapProjectBrowserManifest(
  manifest: ProjectBrowserManifestResponse,
): WorkspaceProjectBrowserManifest {
  return {
    root: manifest.root,
    activeMode: manifest.active_mode,
    modes: manifest.modes.map((mode) => ({
      id: mode.id,
      label: mode.label,
      default: mode.default,
      rootPath: mode.root_path ?? null,
    })),
    entries: manifest.entries.map(mapProjectBrowserEntry),
    emptyState: manifest.empty_state
      ? {
          title: manifest.empty_state.title,
          description: manifest.empty_state.description,
        }
      : null,
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
