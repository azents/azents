import type {
  WorkspaceEntry,
  WorkspaceManifest,
  WorkspacePathResult,
} from "./types";

interface ResolveWorkspaceDirectoryInput {
  activeDirectoryPath: string;
  browserManifest: WorkspaceManifest | null;
  directoryResult: WorkspacePathResult | null;
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>;
}

export interface WorkspaceDirectory {
  path: string;
  entries: WorkspaceEntry[];
}

export function resolveWorkspaceDirectory({
  activeDirectoryPath,
  browserManifest,
  directoryResult,
  directoryEntriesByPath,
}: ResolveWorkspaceDirectoryInput): WorkspaceDirectory {
  const path = activeDirectoryPath || browserManifest?.cwd || "";

  if (directoryResult?.type === "DIRECTORY" && directoryResult.path === path) {
    return { path, entries: directoryResult.entries };
  }
  if (browserManifest && path === browserManifest.cwd) {
    return { path, entries: browserManifest.entries };
  }
  return {
    path,
    entries: directoryEntriesByPath[path] ?? [],
  };
}
