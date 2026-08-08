import type { WorkspaceEntry } from "./types";

export type FileTreeNode = WorkspaceEntry & {
  children: FileTreeNode[] | null;
};

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
    ancestors: ReadonlySet<string>,
  ): FileTreeNode[] => {
    const nextAncestors = new Set(ancestors);
    nextAncestors.add(directoryPath);

    return sortEntries(knownEntriesByPath[directoryPath] ?? []).map(
      (entry) => ({
        ...entry,
        children:
          entry.kind === "directory" &&
          knownEntriesByPath[entry.path] &&
          !nextAncestors.has(entry.path)
            ? buildChildren(entry.path, nextAncestors)
            : null,
      }),
    );
  };

  return buildChildren(cwd, new Set());
}
