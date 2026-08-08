import assert from "node:assert/strict";
import test from "node:test";

import { resolveWorkspaceDirectory } from "./workspaceDirectory.ts";
import type {
  WorkspaceEntry,
  WorkspaceManifest,
  WorkspacePathResult,
} from "./types.ts";

function directory(name: string, path: string): WorkspaceEntry {
  return {
    name,
    path,
    kind: "directory",
    size: null,
    mediaType: null,
    modifiedAt: null,
  };
}

const root = "/workspace/agent";
const manifestEntry = directory(
  "Session files",
  `${root}/.azents/sessions/example`,
);
const manifest: WorkspaceManifest = {
  root,
  cwd: root,
  entries: [manifestEntry],
};

void test("does not use a stale directory response for the newly selected path", () => {
  const selectedPath = `${manifestEntry.path}/worktrees`;
  const staleResult: WorkspacePathResult = {
    type: "DIRECTORY",
    path: manifestEntry.path,
    entries: [directory("worktrees", selectedPath)],
  };

  assert.deepEqual(
    resolveWorkspaceDirectory({
      activeDirectoryPath: selectedPath,
      browserManifest: manifest,
      directoryResult: staleResult,
      directoryEntriesByPath: {},
    }),
    { path: selectedPath, entries: [] },
  );
});

void test("uses cached entries while the selected directory response is loading", () => {
  const selectedPath = `${manifestEntry.path}/worktrees`;
  const cachedEntries = [directory("azents", `${selectedPath}/azents`)];

  assert.deepEqual(
    resolveWorkspaceDirectory({
      activeDirectoryPath: selectedPath,
      browserManifest: manifest,
      directoryResult: null,
      directoryEntriesByPath: { [selectedPath]: cachedEntries },
    }),
    { path: selectedPath, entries: cachedEntries },
  );
});

void test("keeps the browser manifest authoritative at its root", () => {
  assert.deepEqual(
    resolveWorkspaceDirectory({
      activeDirectoryPath: root,
      browserManifest: manifest,
      directoryResult: null,
      directoryEntriesByPath: {
        [root]: [directory("stale", `${root}/stale`)],
      },
    }),
    { path: root, entries: manifest.entries },
  );
});
