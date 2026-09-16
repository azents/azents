import assert from "node:assert/strict";
import test from "node:test";
import {
  canDirectlyMutateWorkspaceMember,
  getAvailableWorkspaceMemberRoles,
  getDefaultWorkspaceMemberRole,
  getWorkspaceMemberMutationLocation,
} from "./workspace-member-role-state.ts";

await test("a Workspace without an Owner offers Owner during creation", () => {
  assert.deepEqual(
    getAvailableWorkspaceMemberRoles({
      createMode: true,
      ownerExists: false,
      currentRole: null,
    }),
    ["owner", "manager", "member"],
  );
  assert.equal(getDefaultWorkspaceMemberRole(false), "owner");
});

await test("a Workspace with an Owner prevents second Owner creation", () => {
  assert.deepEqual(
    getAvailableWorkspaceMemberRoles({
      createMode: true,
      ownerExists: true,
      currentRole: null,
    }),
    ["manager", "member"],
  );
  assert.equal(getDefaultWorkspaceMemberRole(true), "member");
});

await test("the current Owner cannot be directly demoted or deleted", () => {
  assert.deepEqual(
    getAvailableWorkspaceMemberRoles({
      createMode: false,
      ownerExists: true,
      currentRole: "owner",
    }),
    ["owner"],
  );
  assert.equal(canDirectlyMutateWorkspaceMember("owner"), false);
});

await test("non-Owners can change between Manager and Member", () => {
  assert.deepEqual(
    getAvailableWorkspaceMemberRoles({
      createMode: false,
      ownerExists: true,
      currentRole: "manager",
    }),
    ["manager", "member"],
  );
  assert.equal(canDirectlyMutateWorkspaceMember("manager"), true);
  assert.equal(canDirectlyMutateWorkspaceMember("member"), true);
});

await test("late mutation completion restores its originating Workspace", () => {
  assert.deepEqual(
    getWorkspaceMemberMutationLocation("workspace-a", "member-a"),
    {
      workspace: "workspace-a",
      memberId: "member-a",
      mode: "view",
    },
  );
  assert.deepEqual(getWorkspaceMemberMutationLocation("workspace-a", null), {
    workspace: "workspace-a",
    memberId: null,
    mode: "view",
  });
});
