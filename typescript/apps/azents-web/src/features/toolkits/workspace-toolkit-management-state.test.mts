import assert from "node:assert/strict";
import test from "node:test";
import { previewToolkits } from "./components/workspace-toolkit-preview-fixtures.ts";
import {
  canToggleWorkspaceToolkit,
  completedWorkspaceToolkitEditor,
  completeWorkspaceToolkitSetup,
  toolkitNeedsReauthorization,
  workspaceToolkitEditorPending,
} from "./workspace-toolkit-management-state.ts";
import type { WorkspaceToolkitEditor } from "./workspace-toolkit-management-state.ts";
import type { ToolkitConfigResponse } from "@azents/public-client";

function fixture(): ToolkitConfigResponse {
  const value = previewToolkits[0];
  if (value == null) {
    throw new Error("Toolkit fixture missing");
  }
  return value;
}

void test("Workspace status reports explicit reconnect evidence, never credentials or enabled as health", () => {
  const toolkit = fixture();
  assert.equal(toolkitNeedsReauthorization(toolkit), false);
  assert.equal(
    toolkitNeedsReauthorization({
      ...toolkit,
      has_credentials: true,
      enabled: true,
    }),
    false,
  );
  assert.equal(
    toolkitNeedsReauthorization({
      ...toolkit,
      oauth_connection: { status: "reconnect_required" },
    }),
    true,
  );
  assert.equal(
    toolkitNeedsReauthorization({
      ...toolkit,
      authorization_state: {
        type: "github_platform_app",
        status: "reconnect_required",
        reason: "app_identity_changed",
      },
    }),
    true,
  );
});

void test("existing Platform reconnect fence permits disable but prohibits re-enable", () => {
  const toolkit: ToolkitConfigResponse = {
    ...fixture(),
    authorization_state: {
      type: "github_platform_app",
      status: "reconnect_required",
      reason: "app_identity_changed",
    },
  };
  assert.equal(canToggleWorkspaceToolkit(toolkit, false), true);
  assert.equal(canToggleWorkspaceToolkit(toolkit, true), false);
  assert.equal(canToggleWorkspaceToolkit(fixture(), true), true);
});

void test("new GitHub and Google host close gates only publication, other and saved forms keep setup gate", () => {
  for (const toolkitType of ["github", "google"]) {
    assert.equal(
      workspaceToolkitEditorPending(
        { type: "CREATE", toolkitType },
        true,
        false,
      ),
      false,
    );
    assert.equal(
      workspaceToolkitEditorPending(
        { type: "CREATE", toolkitType },
        false,
        true,
      ),
      true,
    );
  }
  assert.equal(
    workspaceToolkitEditorPending(
      { type: "CREATE", toolkitType: "mcp" },
      true,
      false,
    ),
    true,
  );
  assert.equal(
    workspaceToolkitEditorPending(
      { type: "EDIT", toolkitId: "saved" },
      true,
      false,
    ),
    true,
  );
});

void test("same-provider or same-id reopen is a distinct immutable editor attempt", () => {
  for (const editor of [
    { type: "CREATE", toolkitType: "github" },
    { type: "EDIT", toolkitId: "saved" },
  ] satisfies WorkspaceToolkitEditor[]) {
    const reopened = { ...editor };
    assert.strictEqual(
      completedWorkspaceToolkitEditor(reopened, editor),
      reopened,
    );
  }
});

void test("late completion leaves a newer pending gate and abandon capability intact", () => {
  const abandoned: WorkspaceToolkitEditor = {
    type: "CREATE",
    toolkitType: "github",
  };
  let active: WorkspaceToolkitEditor = {
    type: "CREATE",
    toolkitType: "github",
  };
  let setupPending = true;
  let publicationPending = true;
  const capability = (): void => {};
  let abandon: (() => void) | null = capability;
  let refreshes = 0;
  const finish = (next: WorkspaceToolkitEditor): void => {
    active = next;
    setupPending = false;
    publicationPending = false;
    abandon = null;
    refreshes += 1;
  };
  const current = active;
  completeWorkspaceToolkitSetup(active, abandoned, finish);
  assert.strictEqual(active, current);
  assert.equal(setupPending, true);
  assert.equal(publicationPending, true);
  assert.strictEqual(abandon, capability);
  assert.equal(refreshes, 0);
  completeWorkspaceToolkitSetup(active, current, finish);
  assert.deepEqual(active, { type: "CLOSED" });
  assert.equal(setupPending, false);
  assert.equal(publicationPending, false);
  assert.equal(abandon, null);
  assert.equal(refreshes, 1);
});

void test("successful edit returns to its own detail, unrelated completions do not navigate", () => {
  const edit: WorkspaceToolkitEditor = { type: "EDIT", toolkitId: "saved" };
  assert.deepEqual(completedWorkspaceToolkitEditor(edit, edit), {
    type: "DETAIL",
    toolkitId: "saved",
  });
  const other: WorkspaceToolkitEditor = { type: "DETAIL", toolkitId: "other" };
  assert.strictEqual(completedWorkspaceToolkitEditor(other, edit), other);
});
