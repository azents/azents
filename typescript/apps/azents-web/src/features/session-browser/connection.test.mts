import assert from "node:assert/strict";
import test from "node:test";
import {
  browserCloseDisposition,
  BrowserConnection,
  BrowserMessageQueue,
  browserReconnectDelay,
} from "./connection.ts";
import type { BrowserFrame, BrowserStatus } from "./types.ts";

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
  viewport: { width: 1280, height: 800 },
  navigation_id: "navigation",
  dialog: null,
  conflict: false,
  opened_target: null,
};
const frame: BrowserFrame = {
  type: "frame",
  attachment_id: "attachment",
  target,
  frame_sequence: 1,
  navigation_id: "navigation",
  width: 1280,
  height: 800,
  media_type: "image/jpeg",
  editables: [],
};
function binary(metadata: BrowserFrame): ArrayBuffer {
  const json = new TextEncoder().encode(JSON.stringify(metadata));
  const bytes = new Uint8Array(4 + json.length + 4);
  new DataView(bytes.buffer).setUint32(0, json.length);
  bytes.set(json, 4);
  bytes.set([255, 216, 255, 217], 4 + json.length);
  return bytes.buffer;
}
function fixture(): {
  connection: BrowserConnection;
  sent: string[];
  urls: Set<string>;
  revoked: string[];
} {
  const sent: string[] = [],
    urls = new Set<string>(),
    revoked: string[] = [];
  let sequence = 0;
  const connection = new BrowserConnection(
    target,
    (message) => {
      sent.push(message);
      return true;
    },
    {
      create: () => {
        const url = `blob:synthetic-${++sequence}`;
        urls.add(url);
        assert.ok(urls.size <= 2);
        return url;
      },
      revoke: (url) => {
        assert.ok(urls.delete(url));
        revoked.push(url);
      },
    },
    () => {},
    () => {},
  );
  return { connection, sent, urls, revoked };
}

void test("only actual target-bound status establishes connected; frame ACK waits for displayed image", () => {
  const { connection, sent } = fixture();
  assert.equal(connection.snapshot().connection, "connecting");
  assert.equal(
    connection.receiveText(
      JSON.stringify({ ...status, target: { ...target, page_id: "other" } }),
    ),
    false,
  );
  assert.equal(connection.receiveText(JSON.stringify(status)), true);
  assert.equal(connection.receiveFrame(binary(frame)), true);
  assert.equal(connection.snapshot().displayed, null);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    false,
  );
  const image = connection.snapshot().image;
  assert.ok(image);
  assert.equal(connection.displayed(image), true);
  assert.deepEqual(
    sent.map((message): unknown => JSON.parse(message)),
    [
      {
        type: "frame_ack",
        attachment_id: "attachment",
        frame_sequence: 1,
      },
    ],
  );
  assert.equal(connection.displayed(image), true);
  assert.equal(sent.length, 1);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    true,
  );
  assert.deepEqual(JSON.parse(sent[1] ?? ""), {
    type: "input",
    attachment_id: "attachment",
    sequence: 1,
    source: {
      frame_sequence: 1,
      navigation_id: "navigation",
      width: 1280,
      height: 800,
    },
    action: { kind: "key", phase: "down", key: "Enter" },
  });
});

void test("navigation uses current source and admits no second effect while input is outstanding", () => {
  const { connection, sent } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const image = connection.snapshot().image;
  assert.ok(image);
  connection.displayed(image);
  const action = {
    kind: "navigation" as const,
    action: "navigate" as const,
    url: "https://example.test/",
  };
  assert.equal(connection.coordinate(frame, action), true);
  assert.equal(connection.snapshot().pendingInputs, 1);
  assert.equal(connection.coordinate(frame, action), false);
  assert.equal(sent.length, 2);
  connection.receiveText(
    JSON.stringify({
      type: "input_ack",
      attachment_id: status.attachment_id,
      sequence: 1,
      accepted: true,
      reason_code: null,
      outcome: "dispatched",
    }),
  );
  assert.equal(connection.snapshot().pendingInputs, 0);
  connection.receiveText(JSON.stringify({ ...status, navigation_id: "next" }));
  assert.equal(connection.coordinate(frame, action), false);
});

void test("non-spatial navigation resolves the freshest ACK without crossing page or navigation scope", () => {
  const { connection, sent } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const first = connection.snapshot().image;
  assert.ok(first);
  connection.displayed(first);
  connection.receiveFrame(binary({ ...frame, frame_sequence: 2 }));
  const second = connection.snapshot().image;
  assert.ok(second);
  connection.displayed(second);
  assert.equal(
    connection.coordinate(frame, {
      kind: "navigation",
      action: "reload",
      url: null,
    }),
    true,
  );
  assert.deepEqual(JSON.parse(sent[2] ?? ""), {
    type: "input",
    attachment_id: frame.attachment_id,
    sequence: 1,
    source: {
      frame_sequence: 2,
      navigation_id: frame.navigation_id,
      width: frame.width,
      height: frame.height,
    },
    action: { kind: "navigation", action: "reload", url: null },
  });
  connection.receiveText(
    JSON.stringify({
      type: "input_ack",
      attachment_id: frame.attachment_id,
      sequence: 1,
      accepted: true,
      reason_code: null,
      outcome: "dispatched",
    }),
  );
  connection.receiveText(
    JSON.stringify({ ...status, navigation_id: "different" }),
  );
  assert.equal(
    connection.coordinate(frame, {
      kind: "navigation",
      action: "reload",
      url: null,
    }),
    false,
  );
});

void test("readonly may acknowledge images but cannot send coordinate or dialog input", () => {
  const { connection, sent } = fixture();
  connection.receiveText(
    JSON.stringify({
      ...status,
      allow_input: false,
      dialog: { id: "dialog", type: "alert", message: "Question" },
    }),
  );
  assert.equal(connection.dialog(true, null), false);
  connection.receiveText(JSON.stringify({ ...status, allow_input: false }));
  connection.receiveFrame(binary(frame));
  const image = connection.snapshot().image;
  assert.ok(image);
  connection.displayed(image);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    false,
  );
  assert.equal(sent.length, 1);
});

void test("new navigation dialog accepts null source before image and rejects old coordinate source", () => {
  const { connection, sent } = fixture();
  connection.receiveText(
    JSON.stringify({
      ...status,
      navigation_id: "initial",
      dialog: { id: "dialog", type: "alert", message: "Before image" },
    }),
  );
  assert.equal(connection.dialog(true, null), true);
  assert.deepEqual(JSON.parse(sent[0] ?? ""), {
    type: "input",
    attachment_id: "attachment",
    sequence: 1,
    source: null,
    action: { kind: "dialog", dialog_id: "dialog", accept: true, text: null },
  });
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const image = connection.snapshot().image;
  assert.ok(image);
  connection.displayed(image);
  connection.receiveText(
    JSON.stringify({
      ...status,
      navigation_id: "next",
      dialog: { id: "next-dialog", type: "confirm", message: "New navigation" },
    }),
  );
  assert.equal(connection.snapshot().displayed, null);
  assert.equal(connection.displayed(image), false);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    false,
  );
  assert.equal(connection.dialog(false, null), true);
});

void test("displayed URL survives decoding its replacement without changing input authority", () => {
  const { connection, urls, revoked } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const first = connection.snapshot().image;
  assert.ok(first);
  connection.displayed(first);
  connection.receiveFrame(binary({ ...frame, frame_sequence: 2 }));
  assert.equal(urls.size, 2);
  assert.deepEqual(revoked, []);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    true,
  );
  assert.equal(connection.displayed(first), false);
  const second = connection.snapshot().image;
  assert.ok(second);
  connection.displayed(second);
  assert.equal(urls.size, 1);
  assert.deepEqual(revoked, [first.url]);
  assert.equal(
    connection.coordinate(frame, {
      kind: "pointer",
      phase: "down",
      x: 10,
      y: 10,
      button: "left",
    }),
    false,
  );
  assert.equal(
    connection.receiveFrame(binary({ ...frame, frame_sequence: 2 })),
    false,
  );
  connection.dispose();
  assert.equal(urls.size, 0);
});

void test("only displayed and newest decoding URLs survive replacement and both clear on denial", () => {
  const { connection, urls, revoked } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const displayed = connection.snapshot().image;
  assert.ok(displayed);
  connection.displayed(displayed);
  connection.receiveFrame(binary({ ...frame, frame_sequence: 2 }));
  const superseded = connection.snapshot().image;
  assert.ok(superseded);
  connection.receiveFrame(binary({ ...frame, frame_sequence: 3 }));
  assert.equal(urls.size, 2);
  assert.deepEqual(revoked, [superseded.url]);
  assert.equal(connection.displayed(superseded), false);
  assert.ok(urls.has(displayed.url));
  connection.disconnect(true, "revoked");
  assert.equal(urls.size, 0);
  assert.equal(connection.snapshot().image, null);
});

void test("unknown outstanding input is never replayed across loss or a fresh attachment", () => {
  const { connection, sent, urls } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const image = connection.snapshot().image;
  assert.ok(image);
  connection.displayed(image);
  connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" });
  connection.disconnect(false);
  assert.equal(connection.snapshot().connection, "stale");
  assert.equal(connection.snapshot().outcomeUnknown, true);
  assert.equal(connection.snapshot().status, null);
  assert.equal(connection.snapshot().displayed, null);
  assert.equal(urls.size, 1);
  assert.equal(
    connection.coordinate(frame, { kind: "key", phase: "down", key: "Enter" }),
    false,
  );
  assert.equal(connection.receiveText(JSON.stringify(status)), false);
  assert.equal(sent.length, 2);
  connection.dispose();
  assert.equal(urls.size, 0);
  const fresh = fixture();
  fresh.connection.receiveText(
    JSON.stringify({ ...status, attachment_id: "new" }),
  );
  assert.equal(fresh.sent.length, 0);
  assert.equal(fresh.connection.dialog(true, null), false);
});

void test("ACK bounds/order are strict; dispatched ACK is not a verified site outcome", () => {
  const { connection } = fixture();
  connection.receiveText(
    JSON.stringify({
      ...status,
      dialog: { id: "dialog", type: "alert", message: "Question" },
    }),
  );
  connection.dialog(true, null);
  const ack = {
    type: "input_ack",
    attachment_id: "attachment",
    sequence: 1,
    accepted: true,
    reason_code: null,
    outcome: "dispatched",
  };
  assert.equal(
    connection.receiveText(JSON.stringify({ ...ack, sequence: 2 })),
    false,
  );
  assert.equal(connection.receiveText(JSON.stringify(ack)), true);
  assert.equal(connection.receiveText(JSON.stringify(ack)), false);
  connection.disconnect(false);
  assert.equal(connection.snapshot().outcomeUnknown, false);
  assert.equal("workflowSuccess" in connection.snapshot(), false);
});

void test("revocation/scope/expiry/closed-target erase volatile authority and image", () => {
  for (const code of [4401, 4403, 4408, 4409]) {
    const { connection, urls } = fixture();
    connection.receiveText(JSON.stringify(status));
    connection.receiveFrame(binary(frame));
    const disposition = browserCloseDisposition(code);
    assert.equal(disposition.clearProjection, true);
    connection.disconnect(disposition.clearImage, disposition.connection);
    assert.equal(connection.snapshot().image, null);
    assert.equal(connection.snapshot().status, null);
    assert.equal(urls.size, 0);
  }
  assert.equal(browserCloseDisposition(1006).clearImage, false);
  assert.equal(browserCloseDisposition(4500).clearProjection, false);
});

void test("Blob processing preserves message order and drops conversion after disposal/epoch replacement", async () => {
  const gate = Promise.withResolvers<ArrayBuffer>();
  class ControlledBlob extends Blob {
    public override arrayBuffer(): Promise<ArrayBuffer> {
      return gate.promise;
    }
  }
  const received: Array<string | ArrayBuffer> = [];
  const queue = new BrowserMessageQueue(
    (message) => {
      received.push(message);
      return true;
    },
    () => {
      throw new Error("Unexpected queue failure");
    },
  );
  queue.push(new ControlledBlob(["image"]));
  queue.push("later-status");
  assert.equal(received.length, 0);
  queue.dispose();
  gate.resolve(new ArrayBuffer(5));
  await queue.settled();
  assert.equal(received.length, 0);
});

void test("async frame inbox is bounded and cannot queue an unbounded image history", async () => {
  let failures = 0;
  const queue = new BrowserMessageQueue(
    () => true,
    () => {
      failures += 1;
    },
  );
  queue.push(new ArrayBuffer(1024 * 1024 + 1));
  await queue.settled();
  assert.equal(failures, 1);
  const wrong = new BrowserMessageQueue(
    () => true,
    () => {
      failures += 1;
    },
  );
  wrong.push({ unsupported: true });
  await wrong.settled();
  assert.equal(failures, 2);
});

void test("asynchronous Blob conversion preserves wire order without a parallel frame decoder", async () => {
  const gate = Promise.withResolvers<ArrayBuffer>();
  class ControlledBlob extends Blob {
    public override arrayBuffer(): Promise<ArrayBuffer> {
      return gate.promise;
    }
  }
  const received: Array<string | ArrayBuffer> = [];
  const queue = new BrowserMessageQueue(
    (message) => {
      received.push(message);
      return true;
    },
    () => {
      throw new Error("Unexpected failure");
    },
  );
  queue.push(new ControlledBlob(["image"]));
  queue.push("status-after-frame");
  const buffer = new ArrayBuffer(4);
  gate.resolve(buffer);
  await queue.settled();
  assert.deepEqual(received, [buffer, "status-after-frame"]);
});

void test("input backpressure closes rather than losing a gesture end or queueing later replay", () => {
  const { connection, sent } = fixture();
  connection.receiveText(
    JSON.stringify({
      ...status,
      dialog: { id: "dialog", type: "alert", message: "Question" },
    }),
  );
  for (let index = 0; index < 128; index += 1) {
    assert.equal(connection.dialog(true, null), true);
  }
  assert.equal(connection.dialog(true, null), false);
  assert.equal(connection.snapshot().connection, "stale");
  assert.equal(connection.snapshot().status, null);
  assert.equal(connection.snapshot().outcomeUnknown, true);
  assert.equal(sent.length, 128);
});

void test("held-input cleanup follows a fresh ACK without admitting stale spatial effects", () => {
  const { connection, sent } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const first = connection.snapshot().image;
  assert.ok(first);
  connection.displayed(first);
  assert.equal(
    connection.coordinate(frame, {
      kind: "pointer",
      phase: "down",
      x: 20,
      y: 30,
      button: "left",
    }),
    true,
  );
  const newer = { ...frame, frame_sequence: 2 };
  connection.receiveFrame(binary(newer));
  const image = connection.snapshot().image;
  assert.ok(image);
  connection.displayed(image);
  assert.equal(
    connection.coordinate(frame, {
      kind: "pointer",
      phase: "up",
      x: 20,
      y: 30,
      button: "left",
    }),
    false,
  );
  for (const action of [
    { kind: "pointer", phase: "cancel", x: 20, y: 30, button: null },
    { kind: "composition", phase: "cancel", text: null },
    { kind: "key", phase: "up", key: "Shift" },
  ] as const) {
    assert.equal(connection.coordinate(frame, action), true);
    assert.match(sent.at(-1) ?? "", /"frame_sequence":2/u);
  }
  assert.equal(connection.snapshot().connection, "connected");
});

void test("cleanup that cannot use the same live scope closes the attachment", () => {
  for (const stale of [
    { ...frame, navigation_id: "previous" },
    { ...frame, width: 640 },
    { ...frame, attachment_id: "previous" },
    { ...frame, target: { ...target, page_id: "previous" } },
  ]) {
    const { connection, sent } = fixture();
    connection.receiveText(JSON.stringify(status));
    connection.receiveFrame(binary(frame));
    const image = connection.snapshot().image;
    assert.ok(image);
    connection.displayed(image);
    assert.equal(
      connection.coordinate(stale, {
        kind: "composition",
        phase: "cancel",
        text: null,
      }),
      false,
    );
    assert.equal(connection.snapshot().connection, "stale");
    assert.equal(sent.length, 1);
  }
});

void test("native text and keys use the latest displayed ACK across a React render boundary", () => {
  const { connection, sent } = fixture();
  connection.receiveText(JSON.stringify(status));
  connection.receiveFrame(binary(frame));
  const initial = connection.snapshot().image;
  assert.ok(initial);
  connection.displayed(initial);
  connection.receiveFrame(binary({ ...frame, frame_sequence: 2 }));
  const next = connection.snapshot().image;
  assert.ok(next);
  connection.displayed(next);
  for (const action of [
    { kind: "composition", phase: "start", text: null },
    { kind: "composition", phase: "commit", text: "S" },
    { kind: "key", phase: "down", key: "ArrowLeft" },
    { kind: "key", phase: "up", key: "ArrowLeft" },
  ] as const) {
    assert.equal(connection.coordinate(frame, action), true);
    assert.match(sent.at(-1) ?? "", /"frame_sequence":2/u);
  }
  assert.equal(
    connection.coordinate(
      { ...frame, navigation_id: "previous" },
      { kind: "composition", phase: "commit", text: "unexpected" },
    ),
    false,
  );
  assert.equal(
    connection.coordinate(frame, {
      kind: "pointer",
      phase: "down",
      x: 10,
      y: 20,
      button: "left",
    }),
    false,
  );
});

void test("only bounded ordinary observation reconnects; denial and closure never auto-retry", () => {
  assert.equal(browserReconnectDelay(4500, 0), 500);
  assert.equal(browserReconnectDelay(1006, 1), 1000);
  assert.equal(browserReconnectDelay(1011, 2), 2000);
  assert.equal(browserReconnectDelay(4500, 3), null);
  for (const code of [1000, 4400, 4401, 4403, 4408, 4409, 4429]) {
    assert.equal(browserReconnectDelay(code, 0), null);
  }
});
