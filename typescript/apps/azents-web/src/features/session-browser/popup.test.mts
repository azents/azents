import assert from "node:assert/strict";
import test from "node:test";
import { browserPopupHintCurrent } from "./popup.ts";
import type { BrowserPopupHint } from "./popup";
import type { BrowserStatus } from "./types";

void test("popup preference belongs to its still-live originating attachment and explicit hint", () => {
  const origin = {
    task_id: "task",
    page_id: "origin",
    resource_incarnation: "native",
  };
  const target = { ...origin, page_id: "popup" };
  const hint: BrowserPopupHint = {
    resourceKey: "session",
    attachment: "attached",
    navigation: "nav",
    origin,
    target,
  };
  const status: BrowserStatus = {
    type: "status",
    attachment_id: "attached",
    target: origin,
    state: "connected",
    allow_input: true,
    viewport: { width: 800, height: 900 },
    navigation_id: "nav",
    dialog: null,
    conflict: false,
    opened_target: target,
  };
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, true),
    true,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, false),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "another-session", status, origin, true),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", null, origin, true),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, target, true),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, null, true),
    false,
  );
  for (const changed of [
    { ...status, attachment_id: "reconnected" },
    { ...status, navigation_id: "new-document" },
    { ...status, allow_input: false },
    { ...status, opened_target: null },
    { ...status, opened_target: { ...target, page_id: "newer-popup" } },
  ]) {
    assert.equal(
      browserPopupHintCurrent(hint, "session", changed, origin, true),
      false,
    );
  }
});
