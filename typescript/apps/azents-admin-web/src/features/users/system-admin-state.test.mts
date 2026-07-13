import assert from "node:assert/strict";
import test from "node:test";
import { getSystemAdminRoleSummary } from "./system-admin-state.ts";

const firstAdmin = { user_id: "admin-1" };
const secondAdmin = { user_id: "admin-2" };

await test("ordinary users have no system administrator role", () => {
  assert.deepEqual(
    getSystemAdminRoleSummary([firstAdmin], "admin-1", "ordinary-user"),
    {
      assigned: false,
      currentUser: false,
      finalAdmin: false,
    },
  );
});

await test("the only assignment is identified as the final administrator", () => {
  assert.deepEqual(
    getSystemAdminRoleSummary([firstAdmin], "admin-1", "admin-1"),
    {
      assigned: true,
      currentUser: true,
      finalAdmin: true,
    },
  );
});

await test("current and selected administrators remain distinct", () => {
  assert.deepEqual(
    getSystemAdminRoleSummary([firstAdmin, secondAdmin], "admin-1", "admin-2"),
    {
      assigned: true,
      currentUser: false,
      finalAdmin: false,
    },
  );
});

await test("self-revocation is allowed when another administrator remains", () => {
  assert.deepEqual(
    getSystemAdminRoleSummary([firstAdmin, secondAdmin], "admin-1", "admin-1"),
    {
      assigned: true,
      currentUser: true,
      finalAdmin: false,
    },
  );
});
