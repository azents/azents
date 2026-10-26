import assert from "node:assert/strict";
import test from "node:test";
import {
  browserAddress,
  browserDialogInput,
  browserFrameMatchesStatus,
  browserImageMatchesFrame,
  browserInput,
  browserKey,
  browserPasteAction,
  browserPoint,
  browserReleaseFrame,
  browserRemoteModifiers,
  browserTextareaModifier,
  browserTextareaTextKey,
  sameBrowserTarget,
} from "./input.ts";

const target = {
  task_id: "task",
  page_id: "page",
  resource_incarnation: "generation",
};
const frame = {
  type: "frame" as const,
  attachment_id: "attach",
  target,
  frame_sequence: 5,
  navigation_id: "nav",
  width: 1280,
  height: 800,
  media_type: "image/jpeg" as const,
  editables: [],
};
const status = {
  type: "status" as const,
  attachment_id: "attach",
  target,
  state: "connected" as const,
  allow_input: true,
  viewport: { width: 1280, height: 800 },
  navigation_id: "nav",
  dialog: null,
  conflict: false,
  opened_target: null,
};

void test("image pixel density preserves the CSS input plane within a decoded bound", () => {
  const css = { width: 400, height: 560 };
  assert.equal(browserImageMatchesFrame(css, css), true);
  assert.equal(
    browserImageMatchesFrame({ width: 800, height: 1120 }, css),
    true,
  );
  for (const pixels of [
    { width: 1200, height: 1680 },
    { width: 800, height: 560 },
    { width: 600, height: 840 },
    { width: 0, height: 0 },
    { width: NaN, height: 1120 },
    { width: 800.5, height: 1120 },
  ]) {
    assert.equal(browserImageMatchesFrame(pixels, css), false);
  }
  assert.equal(
    browserImageMatchesFrame(
      { width: 8192, height: 8192 },
      { width: 4096, height: 4096 },
    ),
    false,
  );
});

void test("address entry supports web destinations without embedded credentials", () => {
  assert.equal(
    browserAddress("example.test/path"),
    "https://example.test/path",
  );
  assert.equal(
    browserAddress(" http://127.0.0.1:8766/next "),
    "http://127.0.0.1:8766/next",
  );
  for (const value of [
    "",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https://user:secret@example.test/",
    "https://[bad/",
  ]) {
    assert.equal(browserAddress(value), null);
  }
});

void test("paste preserves plaintext and rejects oversized or unknown destinations", () => {
  const source = {
    ...frame,
    editables: [
      {
        id: "doc-1",
        x: 1,
        y: 1,
        width: 100,
        height: 40,
        input_mode: "text" as const,
      },
    ],
  };
  const text = ' Synthetic 한글 🔑\n"\\ ';
  assert.deepEqual(browserPasteAction(source, "doc-1", text), {
    kind: "paste",
    editable_id: "doc-1",
    text,
  });
  for (const value of [
    "",
    "x".repeat(32769),
    "界".repeat(24000),
    "\u0000".repeat(20000),
  ]) {
    assert.equal(browserPasteAction(source, "doc-1", value), null);
  }
  assert.equal(browserPasteAction(source, "old", text), null);
});

void test("textarea uppercase text uses local Shift while actual chords retain typed modifiers", () => {
  const plain = {
    control: false,
    meta: false,
    alt: false,
    shift: false,
    altGraph: false,
  };
  assert.equal(browserTextareaModifier("Shift"), true);
  assert.equal(browserTextareaModifier("Control"), true);
  assert.equal(browserTextareaModifier("ArrowLeft"), false);
  assert.equal(browserTextareaTextKey("S", { ...plain, shift: true }), true);
  assert.equal(browserTextareaTextKey("a", { ...plain, control: true }), false);
  assert.equal(browserTextareaTextKey("a", { ...plain, meta: true }), false);
  assert.equal(browserTextareaTextKey("a", { ...plain, alt: true }), false);
  assert.equal(
    browserTextareaTextKey("€", {
      ...plain,
      control: true,
      alt: true,
      altGraph: true,
    }),
    true,
  );
  assert.deepEqual(browserRemoteModifiers({ ...plain, shift: true }), [
    "Shift",
  ]);
  assert.deepEqual(
    browserRemoteModifiers({ ...plain, control: true, shift: true }),
    ["Control", "Shift"],
  );
});

void test("key release advances only to an acknowledged frame in the same actual interaction scope", () => {
  const current = { ...frame, frame_sequence: 6 };
  assert.equal(browserReleaseFrame(frame, current), current);
  assert.equal(browserReleaseFrame(frame, { ...current, width: 640 }), frame);
  assert.equal(browserReleaseFrame(frame, { ...current, height: 480 }), frame);
  assert.equal(
    browserReleaseFrame(frame, { ...current, attachment_id: "other" }),
    frame,
  );
  assert.equal(
    browserReleaseFrame(frame, { ...current, navigation_id: "other" }),
    frame,
  );
  assert.equal(
    browserReleaseFrame(frame, {
      ...current,
      target: { ...target, page_id: "other" },
    }),
    frame,
  );
});

void test("contained viewport mapping excludes letterbox and out-of-bounds input", () => {
  const rect = { left: 20, top: 10, width: 400, height: 400 };
  const source = { width: 1280, height: 800 };
  assert.deepEqual(browserPoint(220, 210, rect, source), { x: 640, y: 400 });
  assert.equal(browserPoint(220, 20, rect, source), null);
  assert.equal(browserPoint(420, 210, rect, source), null);
  assert.equal(browserPoint(NaN, 0, rect, source), null);
  assert.equal(browserPoint(0, 0, { ...rect, width: 0 }, source), null);
});

void test("coordinate input binds to acknowledged metadata and current navigation", () => {
  const action = { kind: "key" as const, phase: "down" as const, key: "Enter" };
  const result = browserInput(frame, status, 9, action);
  assert.ok(result !== null && result.source !== null);
  assert.equal(result.sequence, 9);
  assert.equal(result.source.frame_sequence, 5);
  assert.equal(result.source.navigation_id, "nav");
  assert.equal(
    sameBrowserTarget(target, { ...target, page_id: "other" }),
    false,
  );
  assert.equal(browserKey(" "), "Space");
  assert.equal(browserKey("ArrowLeft"), "ArrowLeft");
  assert.equal(browserKey("😀"), "😀");
  assert.equal(browserKey("Unidentified"), null);
  assert.equal(browserKey("Dead"), null);
  assert.equal(browserKey("Process"), null);
  assert.equal(browserKey("\u0000"), null);
  assert.equal(browserKey("F24"), "F24");
  assert.equal(browserKey("F25"), null);
  assert.equal(browserFrameMatchesStatus(frame, status), true);
  assert.equal(
    browserFrameMatchesStatus(frame, { ...status, navigation_id: "new" }),
    false,
  );
  assert.equal(
    browserFrameMatchesStatus(frame, {
      ...status,
      attachment_id: "reconnected",
    }),
    false,
  );
  assert.equal(
    browserFrameMatchesStatus(frame, {
      ...status,
      viewport: { width: 800, height: 1280 },
    }),
    false,
  );
  assert.equal(
    browserInput(frame, { ...status, navigation_id: "new" }, 10, action),
    null,
  );
  assert.equal(
    browserInput(frame, { ...status, allow_input: false }, 10, action),
    null,
  );
});

void test("current dialog input has required null source without a captured frame", () => {
  const dialogStatus = {
    ...status,
    navigation_id: "new-navigation",
    dialog: {
      id: "initial-dialog",
      type: "alert",
      message: "Initial navigation question",
    },
  };
  const input = browserDialogInput(dialogStatus, 1, true, null);
  assert.ok(input !== null);
  assert.equal(input.source, null);
  assert.equal(Object.hasOwn(input, "source"), true);
  assert.equal(input.attachment_id, "attach");
  assert.deepEqual(input.action, {
    kind: "dialog",
    dialog_id: "initial-dialog",
    accept: true,
    text: null,
  });
  assert.equal(
    browserDialogInput({ ...dialogStatus, allow_input: false }, 2, true, null),
    null,
  );
  assert.equal(
    browserDialogInput({ ...dialogStatus, state: "closed" }, 2, true, null),
    null,
  );
  assert.equal(
    browserDialogInput({ ...dialogStatus, dialog: null }, 2, true, null),
    null,
  );
  assert.equal(
    browserInput(frame, dialogStatus, 2, {
      kind: "key",
      phase: "down",
      key: "Enter",
    }),
    null,
  );
});
