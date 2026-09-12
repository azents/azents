import assert from "node:assert/strict";
import test from "node:test";
import {
  getTabOverflow,
  parseSessionPanelView,
  sessionPanelHref,
  sessionPanelViews,
} from "./sessionPanel.ts";

void test("only existing supporting session views are recognized", () => {
  for (const view of sessionPanelViews) {
    assert.equal(parseSessionPanelView(view), view);
  }
  for (const view of [null, "chat", "projects", "unknown", "canvas"]) {
    assert.equal(parseSessionPanelView(view), null);
  }
});
void test("tab overflow cues reflect actual remaining scroll in each direction", () => {
  assert.deepEqual(getTabOverflow(0, 390, 1000), {
    previous: false,
    next: true,
  });
  assert.deepEqual(getTabOverflow(250, 390, 1000), {
    previous: true,
    next: true,
  });
  assert.deepEqual(getTabOverflow(610, 390, 1000), {
    previous: true,
    next: false,
  });
  assert.deepEqual(getTabOverflow(0, 390, 390), {
    previous: false,
    next: false,
  });
  assert.deepEqual(getTabOverflow(-10, 390, 390), {
    previous: false,
    next: false,
  });
  assert.deepEqual(getTabOverflow(609.6, 390, 1000), {
    previous: true,
    next: false,
  });
});
void test("feature transitions keep session identity and unrelated query while clearing task-specific state", () => {
  const path = "/w/team/agents/agent/sessions/session";
  assert.equal(
    sessionPanelHref(
      path,
      "page=scheduled-tasks&taskId=task&edit=1&other=value",
      "context",
    ),
    `${path}?other=value&page=context`,
  );
  assert.equal(sessionPanelHref(path, "page=context", null), path);
});
