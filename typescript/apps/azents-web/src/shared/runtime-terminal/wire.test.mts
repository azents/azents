import assert from "node:assert/strict";
import test from "node:test";
import {
  applyTerminalKeyModifiers,
  decodeTerminalOutputFrame,
  decodeTerminalServerControl,
  encodeTerminalInputFrame,
  splitTerminalInput,
  TERMINAL_MAX_BINARY_PAYLOAD_BYTES,
} from "./wire.ts";

void test("encodes opaque input with version, type, and sequence", () => {
  const payload = new Uint8Array([0xff, 0x00, 0x41]);
  const frame = new Uint8Array(encodeTerminalInputFrame(9, payload));

  assert.deepEqual([...frame.slice(0, 2)], [1, 1]);
  assert.equal(new DataView(frame.buffer).getBigUint64(2, false), BigInt(9));
  assert.deepEqual([...frame.slice(10)], [...payload]);
});

void test("decodes opaque output without text conversion", () => {
  const frame = new Uint8Array(13);
  frame[0] = 1;
  frame[1] = 2;
  new DataView(frame.buffer).setBigUint64(2, BigInt(7), false);
  frame.set([0xff, 0x00, 0x41], 10);

  const decoded = decodeTerminalOutputFrame(frame.buffer);

  assert.equal(decoded.sequence, 7);
  assert.deepEqual([...decoded.bytes], [0xff, 0x00, 0x41]);
});

void test("rejects malformed output headers", () => {
  assert.throws(() => decodeTerminalOutputFrame(new ArrayBuffer(9)));
  const frame = new Uint8Array(10);
  frame[0] = 2;
  frame[1] = 2;
  assert.throws(() => decodeTerminalOutputFrame(frame.buffer));
  frame[0] = 1;
  assert.throws(() => decodeTerminalOutputFrame(frame.buffer));
});

void test("splits oversized input at the binary wire bound", () => {
  const input = new Uint8Array(TERMINAL_MAX_BINARY_PAYLOAD_BYTES + 3);
  const chunks = splitTerminalInput(input);
  assert.deepEqual(
    chunks.map((chunk) => chunk.byteLength),
    [TERMINAL_MAX_BINARY_PAYLOAD_BYTES, 3],
  );
  assert.throws(() => encodeTerminalInputFrame(1, input));
});

void test("decodes only closed typed server controls", () => {
  assert.deepEqual(
    decodeTerminalServerControl(
      JSON.stringify({
        type: "replay_end",
        maximum_sequence: 12,
      }),
    ),
    { type: "replay_end", maximumSequence: 12 },
  );
  assert.throws(() =>
    decodeTerminalServerControl(
      JSON.stringify({
        type: "replay_end",
        maximum_sequence: 12,
        extra: true,
      }),
    ),
  );
  assert.throws(() =>
    decodeTerminalServerControl(JSON.stringify({ type: "unknown" })),
  );
});

void test("preserves signed-BIGINT runner generations as decimal strings", () => {
  const accepted = {
    type: "accepted",
    terminal_id: "terminal-1",
    lifecycle: "attached",
    attachment_generation: 1,
    desired_generation: 1,
    runner_generation: "9223372036854775807",
    shell_label: "bash",
    working_directory_display: "~/session",
    next_input_sequence: 1,
    replay_min_sequence: 0,
    replay_max_sequence: 0,
    replay_truncated: false,
  };

  const decoded = decodeTerminalServerControl(JSON.stringify(accepted));

  assert.equal(decoded.type, "accepted");
  assert.equal(decoded.runnerGeneration, "9223372036854775807");
});

void test("rejects noncanonical runner generation representations", () => {
  const accepted = {
    type: "accepted",
    terminal_id: "terminal-1",
    lifecycle: "attached",
    attachment_generation: 1,
    desired_generation: 1,
    runner_generation: "1",
    shell_label: "bash",
    working_directory_display: "~/session",
    next_input_sequence: 1,
    replay_min_sequence: 0,
    replay_max_sequence: 0,
    replay_truncated: false,
  };

  for (const runnerGeneration of [1, "0", "01", "9223372036854775808"]) {
    assert.throws(() =>
      decodeTerminalServerControl(
        JSON.stringify({
          ...accepted,
          runner_generation: runnerGeneration,
        }),
      ),
    );
  }
});

void test("applies sticky Ctrl and Alt to one software key", () => {
  assert.equal(applyTerminalKeyModifiers("c", true, false), "\u0003");
  assert.equal(applyTerminalKeyModifiers("x", false, true), "\u001bx");
  assert.equal(applyTerminalKeyModifiers("c", true, true), "\u001b\u0003");
});
