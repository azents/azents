import assert from "node:assert/strict";
import test from "node:test";
import { sessionPanelInvalidationPlan } from "./sessionPanelRefresh.ts";

void test("context views refresh the shared session context projection", () => {
  assert.deepEqual(sessionPanelInvalidationPlan("context"), ["context"]);
  assert.deepEqual(sessionPanelInvalidationPlan("system-prompt"), ["context"]);
  assert.deepEqual(sessionPanelInvalidationPlan("raw-events"), ["context"]);
});

void test("standalone session views refresh their own projections", () => {
  assert.deepEqual(sessionPanelInvalidationPlan("subagents"), ["subagents"]);
  assert.deepEqual(sessionPanelInvalidationPlan("channels"), ["channels"]);
  assert.deepEqual(sessionPanelInvalidationPlan("terminal"), ["terminal"]);
});

void test("container-owned views delegate refresh to their owning container", () => {
  assert.deepEqual(sessionPanelInvalidationPlan("files"), []);
  assert.deepEqual(sessionPanelInvalidationPlan("services"), []);
  assert.deepEqual(sessionPanelInvalidationPlan("scheduled-tasks"), []);
  assert.deepEqual(sessionPanelInvalidationPlan("runtime"), []);
  assert.deepEqual(sessionPanelInvalidationPlan("metrics"), []);
});
