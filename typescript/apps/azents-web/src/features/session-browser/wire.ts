import type {
  BrowserFrame,
  BrowserInputAck,
  BrowserInputReason,
  BrowserStatus,
  BrowserTarget,
} from "./types";

const MAX_MESSAGE = 1024 * 1024;
const MAX_METADATA = 4096;
const MAX_TEXT = 64 * 1024;

function reasonCode(value: unknown): value is BrowserInputReason | null {
  return (
    value === null ||
    [
      "browser_read_only",
      "browser_stale_input",
      "browser_stale_frame",
      "browser_stale_target",
      "browser_stale_generation",
      "browser_invalid_authority",
      "browser_invalid_url",
      "browser_input_conflict",
      "browser_dialog_pending",
      "browser_stale_dialog",
      "browser_resource_exhausted",
      "browser_unavailable",
      "browser_deadline",
      "browser_outcome_unknown",
    ].some((reason) => reason === value)
  );
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function keys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  return (
    Object.keys(value).length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key))
  );
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 128;
}

function integer(value: unknown, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value > 0 &&
    value <= maximum
  );
}

function target(value: unknown): value is BrowserTarget {
  return (
    object(value) &&
    keys(value, ["task_id", "page_id", "resource_incarnation"]) &&
    text(value.task_id) &&
    text(value.page_id) &&
    text(value.resource_incarnation)
  );
}

function viewport(value: unknown): value is { width: number; height: number } {
  return (
    object(value) &&
    keys(value, ["width", "height"]) &&
    integer(value.width, 32768) &&
    integer(value.height, 32768) &&
    value.width * value.height <= 16000000
  );
}

function parse(textValue: string): unknown {
  try {
    return JSON.parse(textValue);
  } catch {
    return null;
  }
}

export function decodeBrowserText(
  raw: string,
): BrowserStatus | BrowserInputAck | null {
  if (new TextEncoder().encode(raw).length > MAX_TEXT) {
    return null;
  }
  const value = parse(raw);
  if (!object(value) || !text(value.attachment_id)) {
    return null;
  }
  if (value.type === "input_ack") {
    if (
      !keys(value, [
        "type",
        "attachment_id",
        "sequence",
        "accepted",
        "reason_code",
        "outcome",
      ]) ||
      !integer(value.sequence, Number.MAX_SAFE_INTEGER) ||
      typeof value.accepted !== "boolean" ||
      !reasonCode(value.reason_code) ||
      !(
        value.outcome === "dispatched" ||
        value.outcome === "rejected" ||
        value.outcome === "outcome_unknown"
      )
    ) {
      return null;
    }
    return {
      type: "input_ack",
      attachment_id: value.attachment_id,
      sequence: value.sequence,
      accepted: value.accepted,
      reason_code: value.reason_code,
      outcome: value.outcome,
    };
  }
  if (
    value.type !== "status" ||
    !keys(value, [
      "type",
      "attachment_id",
      "target",
      "state",
      "allow_input",
      "viewport",
      "navigation_id",
      "dialog",
      "conflict",
    ]) ||
    !target(value.target) ||
    !viewport(value.viewport) ||
    !text(value.navigation_id) ||
    !(
      value.state === "connected" ||
      value.state === "closed" ||
      value.state === "unavailable"
    ) ||
    typeof value.allow_input !== "boolean" ||
    typeof value.conflict !== "boolean"
  ) {
    return null;
  }
  let dialog = null;
  if (value.dialog !== null) {
    if (
      !object(value.dialog) ||
      !keys(value.dialog, ["id", "type", "message"]) ||
      !text(value.dialog.id) ||
      !text(value.dialog.type) ||
      typeof value.dialog.message !== "string" ||
      [...value.dialog.message].length > 4096
    ) {
      return null;
    }
    dialog = {
      id: value.dialog.id,
      type: value.dialog.type,
      message: value.dialog.message,
    };
  }
  return {
    type: "status",
    attachment_id: value.attachment_id,
    target: value.target,
    state: value.state,
    allow_input: value.allow_input,
    viewport: value.viewport,
    navigation_id: value.navigation_id,
    dialog,
    conflict: value.conflict,
  };
}

export interface BrowserFrameMessage {
  frame: BrowserFrame;
  jpeg: Uint8Array<ArrayBuffer>;
}

export function decodeBrowserFrame(
  raw: ArrayBuffer,
): BrowserFrameMessage | null {
  if (raw.byteLength < 8 || raw.byteLength > MAX_MESSAGE) {
    return null;
  }
  const length = new DataView(raw).getUint32(0);
  if (
    length === 0 ||
    length > MAX_METADATA ||
    4 + length + 3 > raw.byteLength
  ) {
    return null;
  }
  let value: unknown;
  try {
    value = parse(
      new TextDecoder("utf-8", { fatal: true }).decode(
        new Uint8Array(raw, 4, length),
      ),
    );
  } catch {
    return null;
  }
  if (
    !object(value) ||
    !keys(value, [
      "type",
      "attachment_id",
      "target",
      "frame_sequence",
      "navigation_id",
      "width",
      "height",
      "media_type",
    ]) ||
    value.type !== "frame" ||
    !text(value.attachment_id) ||
    !target(value.target) ||
    !integer(value.frame_sequence, Number.MAX_SAFE_INTEGER) ||
    !text(value.navigation_id) ||
    !integer(value.width, 32768) ||
    !integer(value.height, 32768) ||
    value.width * value.height > 16000000 ||
    value.media_type !== "image/jpeg"
  ) {
    return null;
  }
  const jpeg = new Uint8Array(raw.slice(4 + length));
  if (jpeg[0] !== 255 || jpeg[1] !== 216 || jpeg[2] !== 255) {
    return null;
  }
  return {
    frame: {
      type: "frame",
      attachment_id: value.attachment_id,
      target: value.target,
      frame_sequence: value.frame_sequence,
      navigation_id: value.navigation_id,
      width: value.width,
      height: value.height,
      media_type: "image/jpeg",
    },
    jpeg,
  };
}
