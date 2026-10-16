import assert from "node:assert/strict";
import test from "node:test";
import { BrowserConnection } from "./connection.ts";
import { decodeBrowserText } from "./wire.ts";
import type {
  BrowserFieldAttributes,
  BrowserFieldResult,
  BrowserFrame,
  BrowserStatus,
} from "./types.ts";

const attributes: BrowserFieldAttributes = {
  input_type: "password",
  input_mode: null,
  autocomplete: "current-password",
  autocapitalize: null,
  autocorrect: null,
  spellcheck: false,
  enter_key_hint: null,
  max_length: null,
  min_length: null,
  pattern: "",
  required: false,
  multiple: false,
  placeholder: "",
  name: "password",
};

const target = {
  task_id: "task",
  page_id: "page",
  resource_incarnation: "resource",
};
const status: BrowserStatus = {
  type: "status",
  attachment_id: "attachment",
  target,
  state: "connected",
  allow_input: true,
  viewport: { width: 800, height: 600 },
  navigation_id: "document",
  dialog: null,
  conflict: false,
  opened_target: null,
};
const frame: BrowserFrame = {
  type: "frame",
  attachment_id: status.attachment_id,
  target,
  frame_sequence: 1,
  navigation_id: status.navigation_id,
  width: 800,
  height: 600,
  media_type: "image/jpeg",
  editables: [
    { id: "native", x: 10, y: 10, width: 200, height: 40, input_mode: "text" },
  ],
};
const value = {
  type: "field_value",
  attachment_id: status.attachment_id,
  sequence: 1,
  editable_id: "native",
  edit_id: "edit",
  kind: "password",
  attributes,
  value: "synthetic-private-value",
};
function ack(
  sequence: number,
  accepted = true,
  outcome = "dispatched",
): string {
  return JSON.stringify({
    type: "input_ack",
    attachment_id: status.attachment_id,
    sequence,
    accepted,
    outcome,
    reason_code: accepted ? null : "browser_field_changed",
  });
}
function fixture(): {
  connection: BrowserConnection;
  sent: string[];
  results: BrowserFieldResult[];
} {
  const sent: string[] = [],
    results: BrowserFieldResult[] = [];
  const connection = new BrowserConnection(
    target,
    (raw) => {
      sent.push(raw);
      return true;
    },
    { create: () => "blob:fixture", revoke: () => {} },
    () => {},
    () => {},
    (result) => results.push(result),
  );
  assert.ok(connection.receiveText(JSON.stringify(status)));
  const metadata = new TextEncoder().encode(JSON.stringify(frame));
  const bytes = new Uint8Array(4 + metadata.length + 4);
  new DataView(bytes.buffer).setUint32(0, metadata.length);
  bytes.set(metadata, 4);
  bytes.set([255, 216, 255, 217], 4 + metadata.length);
  assert.ok(connection.receiveFrame(bytes.buffer));
  const image = connection.snapshot().image;
  assert.ok(image);
  assert.ok(connection.displayed(image));
  return { connection, sent, results };
}
function opened(connection: BrowserConnection): void {
  assert.ok(connection.openField(frame, "native"));
  assert.ok(connection.receiveText(JSON.stringify(value)));
  assert.ok(connection.receiveText(ack(1)));
}
void test("private field value requires an explicit correlated read and successful acknowledgement", () => {
  const { connection, results } = fixture();
  assert.equal(connection.receiveText(JSON.stringify(value)), false);
  assert.equal(connection.openField(frame, "missing"), false);
  assert.ok(connection.openField(frame, "native"));
  assert.equal(connection.openField(frame, "native"), false);
  assert.equal(
    connection.receiveText(JSON.stringify({ ...value, editable_id: "other" })),
    false,
  );
  assert.ok(connection.receiveText(JSON.stringify(value)));
  assert.deepEqual(results, []);
  assert.equal(connection.finishField("replacement"), false);
  assert.ok(connection.receiveText(ack(1)));
  assert.deepEqual(results, [{ type: "opened", field: value }]);
  assert.equal(
    JSON.stringify(connection.snapshot()).includes(value.value),
    false,
  );
});
void test("empty replacement is exact, single use, and never retried after unknown outcome", () => {
  const { connection, sent, results } = fixture();
  opened(connection);
  assert.ok(connection.finishField(""));
  assert.equal(connection.finishField("retry"), false);
  const input: unknown = JSON.parse(sent.at(-1) ?? "null");
  assert.ok(typeof input === "object" && input !== null && "action" in input);
  assert.deepEqual(input.action, {
    kind: "field_replace",
    editable_id: "native",
    edit_id: "edit",
    text: "",
  });
  connection.disconnect(false);
  assert.deepEqual(results.at(-1), {
    type: "failed",
    reason: null,
    unknown: true,
  });
  assert.equal(connection.finishField("retry"), false);
});
void test("cancel sends only edit identity and permits a fresh read after acknowledgement", () => {
  const { connection, sent, results } = fixture();
  opened(connection);
  assert.ok(connection.finishField(null));
  assert.ok(!sent.at(-1)?.includes(value.value));
  assert.ok(connection.receiveText(ack(2)));
  assert.deepEqual(results.at(-1), { type: "completed" });
  assert.ok(connection.openField(frame, "native"));
});
for (const patch of [
  { navigation_id: "new-document" },
  { allow_input: false },
  { viewport: { width: 900, height: 600 } },
  { conflict: true },
  { dialog: { id: "dialog", type: "alert", message: "fixture" } },
] satisfies Partial<BrowserStatus>[]) {
  void test(`field closes without replacement on status invalidation ${JSON.stringify(patch)}`, () => {
    const { connection, sent, results } = fixture();
    opened(connection);
    const count = sent.length;
    assert.ok(connection.receiveText(JSON.stringify({ ...status, ...patch })));
    assert.equal(connection.finishField("replacement"), false);
    assert.equal(sent.length, count);
    assert.equal(results.at(-1)?.type, "failed");
  });
}
void test("rejected read discards an already delivered private response", () => {
  const { connection, results } = fixture();
  assert.ok(connection.openField(frame, "native"));
  assert.ok(connection.receiveText(JSON.stringify(value)));
  assert.ok(connection.receiveText(ack(1, false, "rejected")));
  assert.deepEqual(results, [
    { type: "failed", reason: "browser_field_changed", unknown: false },
  ]);
  assert.equal(connection.finishField("replacement"), false);
});
void test("ordinary direct actions cannot mutate a field while its one-shot editor owns it", () => {
  const { connection } = fixture();
  opened(connection);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    false,
  );
  assert.equal(
    connection.coordinate(frame, {
      kind: "field_replace",
      editable_id: "native",
      edit_id: "edit",
      text: "bypass",
    }),
    false,
  );
});
void test("private value decoder preserves empty and multiline values and rejects malformed or oversized messages", () => {
  for (const text of ["", "first\nsecond", "synthetic-password"]) {
    assert.deepEqual(
      decodeBrowserText(JSON.stringify({ ...value, value: text })),
      { ...value, value: text },
    );
  }
  for (const patch of [
    { unexpected: true },
    { value: "x".repeat(32769) },
    { value: null },
    { kind: "html" },
    { sequence: 0 },
    { edit_id: "" },
  ]) {
    assert.equal(
      decodeBrowserText(JSON.stringify({ ...value, ...patch })),
      null,
    );
  }
});

void test("a new validated frame without the original editable immediately discards private editing", () => {
  const { connection, results } = fixture();
  opened(connection);
  const metadata = new TextEncoder().encode(
    JSON.stringify({ ...frame, frame_sequence: 2, editables: [] }),
  );
  const bytes = new Uint8Array(4 + metadata.length + 4);
  new DataView(bytes.buffer).setUint32(0, metadata.length);
  bytes.set(metadata, 4);
  bytes.set([255, 216, 255, 217], 4 + metadata.length);
  assert.ok(connection.receiveFrame(bytes.buffer));
  assert.deepEqual(results.at(-1), {
    type: "failed",
    reason: null,
    unknown: false,
  });
  assert.equal(connection.finishField("Must not overwrite"), false);
  assert.equal(connection.snapshot().connection, "stale");
});

void test("native field attributes are exact, bounded and cannot carry page execution", () => {
  const email = {
    ...attributes,
    input_type: "email",
    input_mode: "email",
    autocomplete: "email",
  };
  const reply = { ...value, kind: "text", attributes: email };
  assert.deepEqual(decodeBrowserText(JSON.stringify(reply)), reply);
  for (const patch of [
    { input_type: "file" },
    { input_mode: "arbitrary" },
    { autocomplete: "x".repeat(257) },
    { max_length: -1 },
    { min_length: true },
    { spellcheck: "true" },
    { enter_key_hint: "invalid" },
    { autocapitalize: "invalid" },
    { autocorrect: "invalid" },
    { pattern: "x".repeat(2049) },
    { form: "not allowed" },
    { oninput: "not allowed" },
  ]) {
    assert.equal(
      decodeBrowserText(
        JSON.stringify({ ...reply, attributes: { ...email, ...patch } }),
      ),
      null,
    );
  }
  assert.equal(
    decodeBrowserText(JSON.stringify({ ...reply, kind: "password" })),
    null,
  );
});

void test("oversized encoded replacement is rejected before send without an uncertain outcome", () => {
  const { connection, sent } = fixture();
  opened(connection);
  const count = sent.length;
  assert.equal(connection.finishField("界".repeat(24000)), false);
  assert.equal(sent.length, count);
  assert.equal(connection.snapshot().outcomeUnknown, false);
  assert.equal(connection.snapshot().connection, "connected");
  assert.equal(connection.finishField("Smaller value"), true);
});
