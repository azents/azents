import assert from "node:assert/strict";
import test from "node:test";
import { browserPopupHintCurrent } from "./popup.ts";
import type { BrowserPopupHint } from "./popup";
import type { BrowserStatus } from "./types";

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

void test("popup preference belongs to the still-live originating page and attachment", () => {
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, true, null),
    true,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, false, null),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(
      hint,
      "another-session",
      status,
      origin,
      true,
      null,
    ),
    false,
  );
  assert.equal(
    browserPopupHintCurrent(hint, "session", null, origin, true, null),
    false,
  );
  for (const selected of [target, null, { ...origin, task_id: "other-task" }]) {
    assert.equal(
      browserPopupHintCurrent(hint, "session", status, selected, true, null),
      false,
    );
  }
  for (const changed of [
    { ...status, attachment_id: "reconnected" },
    { ...status, navigation_id: "new-document" },
    { ...status, allow_input: false },
    { ...status, opened_target: null },
    { ...status, opened_target: { ...target, page_id: "newer-popup" } },
    { ...status, target: { ...origin, page_id: "another-opener" } },
  ]) {
    assert.equal(
      browserPopupHintCurrent(hint, "session", changed, origin, true, null),
      false,
    );
  }
});

void test("explicit tab choice fences delayed hints before a router rerender", () => {
  // Even when status and selected are still from the previous React render,
  // a synchronous choice suppresses every queued/new hint from that attachment.
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, true, "attached"),
    false,
  );
  const laterTarget = { ...target, page_id: "later-popup" };
  assert.equal(
    browserPopupHintCurrent(
      { ...hint, target: laterTarget },
      "session",
      { ...status, opened_target: laterTarget },
      origin,
      true,
      "attached",
    ),
    false,
  );
  // Resuming native input can clear dismissal; another attachment's dismissal
  // does not suppress this page's newly admitted viewer.
  assert.equal(
    browserPopupHintCurrent(hint, "session", status, origin, true, null),
    true,
  );
  assert.equal(
    browserPopupHintCurrent(
      hint,
      "session",
      status,
      origin,
      true,
      "old-attachment",
    ),
    true,
  );
});
