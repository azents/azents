import assert from "node:assert/strict";
import test from "node:test";
import {
  workspacePanelTabForSessionPanelView,
  workspacePanelTabInvalidationPlan,
} from "./workspacePanelTabs.ts";

void test("session panel views select the matching workspace tab", () => {
  assert.equal(workspacePanelTabForSessionPanelView("files"), "workspace");
  assert.equal(workspacePanelTabForSessionPanelView("services"), "services");
  assert.equal(workspacePanelTabForSessionPanelView("metrics"), "metrics");
  assert.equal(workspacePanelTabForSessionPanelView("runtime"), "settings");
  assert.equal(workspacePanelTabForSessionPanelView("terminal"), "workspace");
});

void test("workspace tab refreshes every workspace projection", () => {
  assert.deepEqual(workspacePanelTabInvalidationPlan("workspace"), [
    "runtime",
    "workspace",
    "workspacePaths",
    "workspacePathStats",
    "projects",
    "workspaceManifest",
  ]);
});

void test("services tab refreshes runtime availability and service list", () => {
  assert.deepEqual(workspacePanelTabInvalidationPlan("services"), [
    "runtime",
    "services",
  ]);
});

void test("metrics tab refreshes runtime availability and metrics", () => {
  assert.deepEqual(workspacePanelTabInvalidationPlan("metrics"), [
    "runtime",
    "metrics",
  ]);
});

void test("settings tab refreshes every settings projection", () => {
  assert.deepEqual(workspacePanelTabInvalidationPlan("settings"), [
    "agent",
    "session",
    "runtime",
    "workspace",
  ]);
});
