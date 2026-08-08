import type { WorkspaceEntry } from "./types";

export type FileTreeNode = WorkspaceEntry & {
  nodeId: string;
  children: FileTreeNode[] | null;
};

function getNodeId(parentNodeId: string | null, entry: WorkspaceEntry): string {
  const projectId =
    entry.source?.type === "session_folder" ||
    entry.source?.type === "session_project" ||
    entry.source?.type === "preview_project"
      ? entry.source.projectId
      : null;
  return JSON.stringify([
    parentNodeId,
    entry.path,
    entry.source?.type ?? "workspace",
    projectId,
  ]);
}

function isSessionFolderEntry(entry: WorkspaceEntry): boolean {
  return entry.source?.type === "session_folder";
}

function sortEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((a, b) => {
    const aIsSessionFolder = isSessionFolderEntry(a);
    const bIsSessionFolder = isSessionFolderEntry(b);
    if (aIsSessionFolder !== bIsSessionFolder) {
      return aIsSessionFolder ? -1 : 1;
    }
    if (a.kind !== b.kind) {
      return a.kind === "directory" ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
}

export function buildFileTree(
  cwd: string,
  manifestEntries: WorkspaceEntry[],
  directoryEntriesByPath: Record<string, WorkspaceEntry[]>,
): FileTreeNode[] {
  const knownEntriesByPath: Record<string, WorkspaceEntry[]> = {
    ...directoryEntriesByPath,
    [cwd]: manifestEntries,
  };

  const buildChildren = (
    directoryPath: string,
    parentNodeId: string | null,
    ancestors: ReadonlySet<string>,
  ): FileTreeNode[] => {
    const nextAncestors = new Set(ancestors);
    nextAncestors.add(directoryPath);

    return sortEntries(knownEntriesByPath[directoryPath] ?? []).map((entry) => {
      const nodeId = getNodeId(parentNodeId, entry);
      return {
        ...entry,
        nodeId,
        children:
          entry.kind === "directory" &&
          knownEntriesByPath[entry.path] &&
          !nextAncestors.has(entry.path)
            ? buildChildren(entry.path, nodeId, nextAncestors)
            : null,
      };
    });
  };

  return buildChildren(cwd, null, new Set());
}
