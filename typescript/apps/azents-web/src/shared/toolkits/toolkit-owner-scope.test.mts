import assert from "node:assert/strict";
import { test } from "node:test";
import {
  sameToolkitOwnerScope,
  toolkitManagementPath,
  toolkitOwnerScopeSchema,
} from "./toolkit-owner-scope.ts";

void test("Personal ownership requires a Workspace and excludes caller-selected owner or Agent", () => {
  assert.deepEqual(
    toolkitOwnerScopeSchema.parse({ owner: "user", handle: "workspace" }),
    {
      owner: "user",
      handle: "workspace",
    },
  );
  for (const injected of [
    { agentId: "workload-agent" },
    { userId: "foreign" },
    { workspaceId: "workload" },
  ]) {
    assert.equal(
      toolkitOwnerScopeSchema.safeParse({
        owner: "user",
        handle: "workspace",
        ...injected,
      }).success,
      false,
    );
  }
  assert.equal(
    toolkitOwnerScopeSchema.safeParse({ owner: "user" }).success,
    false,
  );
  assert.ok(
    !sameToolkitOwnerScope(
      { owner: "user", handle: "workspace-a" },
      { owner: "user", handle: "workspace-b" },
    ),
  );
  assert.equal(
    toolkitOwnerScopeSchema.safeParse({ owner: "workspace" }).success,
    false,
  );
  assert.equal(
    toolkitOwnerScopeSchema.safeParse({ agentId: "agent" }).success,
    false,
  );
});
void test("Management paths retain actual ownership and encode route segments", () => {
  assert.equal(
    toolkitManagementPath({ owner: "user", handle: "workspace" }, null),
    "/w/workspace/personal-tools/new",
  );
  assert.equal(
    toolkitManagementPath({ owner: "user", handle: "workspace" }, "same/name"),
    "/w/workspace/personal-tools/same%2Fname/edit",
  );
  assert.equal(
    toolkitManagementPath({ handle: "team" }, "saved"),
    "/w/team/toolkits/saved/edit",
  );
  assert.equal(
    toolkitManagementPath({ handle: "team", agentId: "agent" }, null),
    "/w/team/agents/agent/settings/capabilities#agent-toolkits",
  );
  assert.ok(
    !sameToolkitOwnerScope(
      { owner: "user", handle: "workspace" },
      { handle: "team" },
    ),
  );
  assert.ok(
    sameToolkitOwnerScope(
      { owner: "user", handle: "workspace" },
      { owner: "user", handle: "workspace" },
    ),
  );
  assert.ok(
    !sameToolkitOwnerScope(
      { handle: "team", agentId: "one" },
      { handle: "team", agentId: "two" },
    ),
  );
});
