import assert from "node:assert/strict";
import test from "node:test";

import { buildFileTree } from "./fileBrowserTree.ts";
import type { WorkspaceEntry } from "./types.ts";

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

void test("does not attach root manifest entries to an unloaded nested Project parent", () => {
  const root = "/workspace/agent";
  const sessionFolder = `${root}/.azents/sessions/example`;
  const worktreesFolder = `${sessionFolder}/worktrees`;
  const projectFolder = `${worktreesFolder}/azents`;
  const sessionEntry: WorkspaceEntry = {
    ...directory("Session files", sessionFolder),
    source: { type: "session_folder", projectId: null },
  };
  const projectEntry: WorkspaceEntry = {
    ...directory("azents", projectFolder),
    source: { type: "session_project", projectId: "project-1" },
  };

  const tree = buildFileTree(root, [sessionEntry, projectEntry], {
    [sessionFolder]: [directory("worktrees", worktreesFolder)],
  });

  const nestedWorktrees = tree[0]?.children?.[0];
  assert.equal(nestedWorktrees?.path, worktreesFolder);
  assert.equal(nestedWorktrees.children, null);
  assert.equal(tree[1]?.path, projectFolder);
});

void test("keeps a nested worktree visible under Session files and as a root Project", () => {
  const root = "/workspace/agent";
  const sessionFolder = `${root}/.azents/sessions/example`;
  const worktreesFolder = `${sessionFolder}/worktrees`;
  const projectFolder = `${worktreesFolder}/azents`;
  const sessionEntry: WorkspaceEntry = {
    ...directory("Session files", sessionFolder),
    source: { type: "session_folder", projectId: null },
  };
  const projectEntry: WorkspaceEntry = {
    ...directory("azents", projectFolder),
    source: { type: "session_project", projectId: "project-1" },
  };

  const tree = buildFileTree(root, [sessionEntry, projectEntry], {
    [sessionFolder]: [directory("worktrees", worktreesFolder)],
    [worktreesFolder]: [directory("azents", projectFolder)],
    [projectFolder]: [directory("src", `${projectFolder}/src`)],
  });

  const nestedProject = tree[0]?.children?.[0]?.children?.[0];
  assert.equal(nestedProject?.path, projectFolder);
  assert.equal(nestedProject.children?.[0]?.path, `${projectFolder}/src`);
  const rootProject = tree[1];
  assert.equal(rootProject?.path, projectFolder);
  assert.equal(rootProject.children?.[0]?.path, `${projectFolder}/src`);
});

void test("stops recursive traversal when malformed directory data contains a cycle", () => {
  const root = "/workspace/agent";
  const child = `${root}/child`;

  const tree = buildFileTree(root, [directory("child", child)], {
    [child]: [directory("root", root)],
  });

  const recursiveRoot = tree[0]?.children?.[0];
  assert.equal(recursiveRoot?.path, root);
  assert.equal(recursiveRoot.children, null);
});
