import assert from "node:assert/strict";
import test from "node:test";
import { decodeBrowserFrame, decodeBrowserText } from "./wire.ts";

const target = {
  task_id: "task",
  page_id: "page",
  resource_incarnation: "generation",
};
const status = {
  type: "status",
  attachment_id: "attach",
  target,
  state: "connected",
  allow_input: true,
  viewport: { width: 1280, height: 800 },
  navigation_id: "nav",
  dialog: null,
  conflict: false,
};
const frame = {
  type: "frame",
  attachment_id: "attach",
  target,
  frame_sequence: 1,
  navigation_id: "nav",
  width: 1280,
  height: 800,
  media_type: "image/jpeg",
};

function binary(
  metadata: object,
  jpeg = new Uint8Array([255, 216, 255, 217]),
): ArrayBuffer {
  const text = new TextEncoder().encode(JSON.stringify(metadata));
  const buffer = new ArrayBuffer(4 + text.length + jpeg.length);
  new DataView(buffer).setUint32(0, text.length);
  const bytes = new Uint8Array(buffer);
  bytes.set(text, 4);
  bytes.set(jpeg, 4 + text.length);
  return buffer;
}
void test("exact typed status and ACK decode; unknown and malformed fields fail closed", () => {
  assert.deepEqual(decodeBrowserText(JSON.stringify(status)), status);
  const initialDialog = {
    ...status,
    navigation_id: "initial-navigation",
    dialog: {
      id: "initial-dialog",
      type: "alert",
      message: "Before the first image",
    },
  };
  assert.deepEqual(
    decodeBrowserText(JSON.stringify(initialDialog)),
    initialDialog,
  );
  const unicodeDialog = {
    ...initialDialog,
    dialog: { id: "dialog", type: "alert", message: "😀".repeat(4096) },
  };
  assert.deepEqual(
    decodeBrowserText(JSON.stringify(unicodeDialog)),
    unicodeDialog,
  );
  for (const invalid of [
    { ...status, extra: true },
    { ...status, allow_input: 1 },
    { ...status, viewport: { width: -1, height: 1 } },
    { ...status, target: { ...target, frame_id: "unexpected" } },
  ]) {
    assert.equal(decodeBrowserText(JSON.stringify(invalid)), null);
  }
  const ack = {
    type: "input_ack",
    attachment_id: "attach",
    sequence: 1,
    accepted: true,
    reason_code: null,
    outcome: "dispatched",
  };
  assert.deepEqual(decodeBrowserText(JSON.stringify(ack)), ack);
  assert.equal(
    decodeBrowserText(
      JSON.stringify({
        ...ack,
        reason_code: "SDK exception containing page content",
      }),
    ),
    null,
  );
  const conflict = {
    ...ack,
    accepted: false,
    reason_code: "browser_input_conflict",
    outcome: "rejected",
  };
  assert.deepEqual(decodeBrowserText(JSON.stringify(conflict)), conflict);
  assert.equal(decodeBrowserText("invalid"), null);
  assert.equal(decodeBrowserText(" ".repeat(65537)), null);
});
void test("binary frame metadata, bounds and JPEG header are validated before display", () => {
  assert.deepEqual(decodeBrowserFrame(binary(frame))?.frame, frame);
  assert.equal(
    decodeBrowserFrame(binary({ ...frame, frame_sequence: 0 })),
    null,
  );
  assert.equal(
    decodeBrowserFrame(binary({ ...frame, width: 32768, height: 32768 })),
    null,
  );
  assert.equal(decodeBrowserFrame(binary({ ...frame, extra: true })), null);
  assert.equal(
    decodeBrowserFrame(binary(frame, new Uint8Array([1, 2, 3]))),
    null,
  );
  assert.equal(decodeBrowserFrame(new ArrayBuffer(1024 * 1024 + 1)), null);
});
