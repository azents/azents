const FRAME_HEADER_BYTES = 10;
const MAX_CONTROL_BYTES = 4 * 1024;
export const TERMINAL_MAX_BINARY_PAYLOAD_BYTES = 16 * 1024;

type TerminalLifecycle =
  "opening" | "attached" | "detached" | "terminating" | "exited";

export type TerminalServerControl =
  | {
      type: "accepted";
      terminalId: string;
      lifecycle: TerminalLifecycle;
      attachmentGeneration: number;
      desiredGeneration: number;
      runnerGeneration: number;
      shellLabel: string;
      workingDirectoryDisplay: string;
      nextInputSequence: number;
      replayMinimumSequence: number;
      replayMaximumSequence: number;
      replayTruncated: boolean;
    }
  | { type: "input_ack"; sequence: number }
  | {
      type: "replay_begin";
      minimumSequence: number;
      maximumSequence: number;
    }
  | { type: "replay_truncated"; minimumSequence: number }
  | { type: "replay_end"; maximumSequence: number }
  | { type: "status"; lifecycle: TerminalLifecycle; reason: string | null }
  | { type: "exit"; reason: string; exitCode: number | null }
  | { type: "revoked"; reasonCode: string }
  | { type: "error"; code: string }
  | { type: "heartbeat_ack"; sequence: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value);
  return (
    actual.length === keys.length && actual.every((key) => keys.includes(key))
  );
}

function isSafeInteger(value: unknown, minimum: number): value is number {
  return (
    typeof value === "number" && Number.isSafeInteger(value) && value >= minimum
  );
}

function isLifecycle(value: unknown): value is TerminalLifecycle {
  return (
    value === "opening" ||
    value === "attached" ||
    value === "detached" ||
    value === "terminating" ||
    value === "exited"
  );
}

function requireControl(
  value: unknown,
): asserts value is Record<string, unknown> {
  if (!isRecord(value) || typeof value.type !== "string") {
    throw new Error("Terminal control is invalid.");
  }
}

export function encodeTerminalInputFrame(
  sequence: number,
  data: Uint8Array,
): ArrayBuffer {
  if (!isSafeInteger(sequence, 1)) {
    throw new Error("Terminal input sequence is invalid.");
  }
  if (data.byteLength > TERMINAL_MAX_BINARY_PAYLOAD_BYTES) {
    throw new Error("Terminal input frame exceeds the wire limit.");
  }
  const frame = new Uint8Array(FRAME_HEADER_BYTES + data.byteLength);
  frame[0] = 1;
  frame[1] = 1;
  new DataView(frame.buffer).setBigUint64(2, BigInt(sequence), false);
  frame.set(data, FRAME_HEADER_BYTES);
  return frame.buffer;
}

export function decodeTerminalOutputFrame(data: ArrayBuffer): {
  sequence: number;
  bytes: Uint8Array;
} {
  if (data.byteLength < FRAME_HEADER_BYTES) {
    throw new Error("Terminal output frame is truncated.");
  }
  if (data.byteLength === FRAME_HEADER_BYTES) {
    throw new Error("Terminal output frame payload is empty.");
  }
  const frame = new Uint8Array(data);
  if (frame[0] !== 1 || frame[1] !== 2) {
    throw new Error("Terminal output frame version is unsupported.");
  }
  if (
    data.byteLength - FRAME_HEADER_BYTES >
    TERMINAL_MAX_BINARY_PAYLOAD_BYTES
  ) {
    throw new Error("Terminal output frame exceeds the wire limit.");
  }
  const rawSequence = new DataView(data).getBigUint64(2, false);
  if (
    rawSequence < BigInt(1) ||
    rawSequence > BigInt(Number.MAX_SAFE_INTEGER)
  ) {
    throw new Error("Terminal output sequence exceeds browser capacity.");
  }
  return {
    sequence: Number(rawSequence),
    bytes: frame.subarray(FRAME_HEADER_BYTES),
  };
}

export function splitTerminalInput(data: Uint8Array): Uint8Array[] {
  const chunks: Uint8Array[] = [];
  for (
    let offset = 0;
    offset < data.byteLength;
    offset += TERMINAL_MAX_BINARY_PAYLOAD_BYTES
  ) {
    chunks.push(
      data.slice(
        offset,
        Math.min(offset + TERMINAL_MAX_BINARY_PAYLOAD_BYTES, data.byteLength),
      ),
    );
  }
  return chunks;
}

export function decodeTerminalServerControl(
  text: string,
): TerminalServerControl {
  if (new TextEncoder().encode(text).byteLength > MAX_CONTROL_BYTES) {
    throw new Error("Terminal control exceeds the wire limit.");
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("Terminal control is invalid.");
  }
  requireControl(value);

  switch (value.type) {
    case "accepted":
      if (
        !hasExactKeys(value, [
          "type",
          "terminal_id",
          "lifecycle",
          "attachment_generation",
          "desired_generation",
          "runner_generation",
          "shell_label",
          "working_directory_display",
          "next_input_sequence",
          "replay_min_sequence",
          "replay_max_sequence",
          "replay_truncated",
        ]) ||
        typeof value.terminal_id !== "string" ||
        !isLifecycle(value.lifecycle) ||
        !isSafeInteger(value.attachment_generation, 1) ||
        !isSafeInteger(value.desired_generation, 1) ||
        !isSafeInteger(value.runner_generation, 1) ||
        typeof value.shell_label !== "string" ||
        typeof value.working_directory_display !== "string" ||
        !isSafeInteger(value.next_input_sequence, 1) ||
        !isSafeInteger(value.replay_min_sequence, 0) ||
        !isSafeInteger(value.replay_max_sequence, 0) ||
        typeof value.replay_truncated !== "boolean"
      ) {
        throw new Error("Terminal accepted control is invalid.");
      }
      return {
        type: "accepted",
        terminalId: value.terminal_id,
        lifecycle: value.lifecycle,
        attachmentGeneration: value.attachment_generation,
        desiredGeneration: value.desired_generation,
        runnerGeneration: value.runner_generation,
        shellLabel: value.shell_label,
        workingDirectoryDisplay: value.working_directory_display,
        nextInputSequence: value.next_input_sequence,
        replayMinimumSequence: value.replay_min_sequence,
        replayMaximumSequence: value.replay_max_sequence,
        replayTruncated: value.replay_truncated,
      };
    case "input_ack":
      if (
        !hasExactKeys(value, ["type", "sequence"]) ||
        !isSafeInteger(value.sequence, 1)
      ) {
        throw new Error("Terminal input acknowledgement is invalid.");
      }
      return { type: "input_ack", sequence: value.sequence };
    case "replay_begin":
      if (
        !hasExactKeys(value, [
          "type",
          "minimum_sequence",
          "maximum_sequence",
        ]) ||
        !isSafeInteger(value.minimum_sequence, 0) ||
        !isSafeInteger(value.maximum_sequence, 0)
      ) {
        throw new Error("Terminal replay begin control is invalid.");
      }
      return {
        type: "replay_begin",
        minimumSequence: value.minimum_sequence,
        maximumSequence: value.maximum_sequence,
      };
    case "replay_truncated":
      if (
        !hasExactKeys(value, ["type", "minimum_sequence"]) ||
        !isSafeInteger(value.minimum_sequence, 0)
      ) {
        throw new Error("Terminal replay truncation control is invalid.");
      }
      return {
        type: "replay_truncated",
        minimumSequence: value.minimum_sequence,
      };
    case "replay_end":
      if (
        !hasExactKeys(value, ["type", "maximum_sequence"]) ||
        !isSafeInteger(value.maximum_sequence, 0)
      ) {
        throw new Error("Terminal replay end control is invalid.");
      }
      return {
        type: "replay_end",
        maximumSequence: value.maximum_sequence,
      };
    case "status":
      if (
        !hasExactKeys(value, ["type", "lifecycle", "reason"]) ||
        !isLifecycle(value.lifecycle) ||
        (value.reason !== null && typeof value.reason !== "string")
      ) {
        throw new Error("Terminal status control is invalid.");
      }
      return {
        type: "status",
        lifecycle: value.lifecycle,
        reason: value.reason,
      };
    case "exit":
      if (
        !hasExactKeys(value, ["type", "reason", "exit_code"]) ||
        typeof value.reason !== "string" ||
        (value.exit_code !== null &&
          (typeof value.exit_code !== "number" ||
            !Number.isSafeInteger(value.exit_code)))
      ) {
        throw new Error("Terminal exit control is invalid.");
      }
      return {
        type: "exit",
        reason: value.reason,
        exitCode: value.exit_code,
      };
    case "revoked":
      if (
        !hasExactKeys(value, ["type", "reason_code"]) ||
        typeof value.reason_code !== "string"
      ) {
        throw new Error("Terminal revocation control is invalid.");
      }
      return { type: "revoked", reasonCode: value.reason_code };
    case "error":
      if (
        !hasExactKeys(value, ["type", "code"]) ||
        typeof value.code !== "string"
      ) {
        throw new Error("Terminal error control is invalid.");
      }
      return { type: "error", code: value.code };
    case "heartbeat_ack":
      if (
        !hasExactKeys(value, ["type", "sequence"]) ||
        !isSafeInteger(value.sequence, 1)
      ) {
        throw new Error("Terminal heartbeat acknowledgement is invalid.");
      }
      return { type: "heartbeat_ack", sequence: value.sequence };
    default:
      throw new Error("Terminal control type is unsupported.");
  }
}

export function applyTerminalKeyModifiers(
  key: string,
  ctrl: boolean,
  alt: boolean,
): string {
  let value = key;
  if (ctrl && key.length === 1) {
    const code = key.toUpperCase().charCodeAt(0);
    if (code >= 64 && code <= 95) {
      value = String.fromCharCode(code - 64);
    }
  }
  return alt ? `\u001b${value}` : value;
}
