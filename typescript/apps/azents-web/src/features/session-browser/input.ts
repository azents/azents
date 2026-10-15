import type {
  BrowserCoordinateAction,
  BrowserFrame,
  BrowserInput,
  BrowserStatus,
  BrowserTarget,
} from "./types";

export interface BrowserPoint {
  x: number;
  y: number;
}

export interface BrowserDisplayRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface BrowserKeyModifiers {
  control: boolean;
  meta: boolean;
  alt: boolean;
  shift: boolean;
  altGraph: boolean;
}

/** Address entry reuses the supported HTTP(S) destination policy without retaining a history. */
export function browserAddress(value: string): string | null {
  const address = value.trim();
  if (!address || address.length > 32768) {
    return null;
  }
  try {
    const url = new URL(
      /^[a-z][a-z\d+.-]*:/iu.test(address) ? address : `https://${address}`,
    );
    return ["http:", "https:"].includes(url.protocol) &&
      url.hostname.length > 0 &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function browserTextareaModifier(key: string): boolean {
  return ["Shift", "Control", "Meta", "Alt", "AltGraph"].includes(key);
}

export function browserTextareaTextKey(
  key: string,
  modifiers: BrowserKeyModifiers,
): boolean {
  return (
    [...key].length === 1 &&
    (modifiers.altGraph ||
      (!modifiers.control && !modifiers.meta && !modifiers.alt))
  );
}

export function browserRemoteModifiers(
  modifiers: BrowserKeyModifiers,
): string[] {
  const result: string[] = [];
  if (modifiers.altGraph) {
    result.push("AltGraph");
  } else {
    if (modifiers.control) {
      result.push("Control");
    }
    if (modifiers.meta) {
      result.push("Meta");
    }
    if (modifiers.alt) {
      result.push("Alt");
    }
  }
  if (modifiers.shift) {
    result.push("Shift");
  }
  return result;
}

/** Key release uses a newer acknowledged frame only inside the same live interaction scope. */
export function browserReleaseFrame(
  original: BrowserFrame,
  current: BrowserFrame | null,
): BrowserFrame {
  return current !== null &&
    current.attachment_id === original.attachment_id &&
    current.navigation_id === original.navigation_id &&
    current.width === original.width &&
    current.height === original.height &&
    sameBrowserTarget(current.target, original.target)
    ? current
    : original;
}

/** Map only the contained image, excluding unused letterbox space. */
export function browserPoint(
  clientX: number,
  clientY: number,
  rect: BrowserDisplayRect,
  source: { width: number; height: number },
): BrowserPoint | null {
  if (
    ![
      clientX,
      clientY,
      rect.left,
      rect.top,
      rect.width,
      rect.height,
      source.width,
      source.height,
    ].every(Number.isFinite) ||
    rect.width <= 0 ||
    rect.height <= 0 ||
    source.width <= 0 ||
    source.height <= 0
  ) {
    return null;
  }
  const scale = Math.min(
    rect.width / source.width,
    rect.height / source.height,
  );
  const x =
    (clientX - rect.left - (rect.width - source.width * scale) / 2) / scale;
  const y =
    (clientY - rect.top - (rect.height - source.height * scale) / 2) / scale;
  return x >= 0 && y >= 0 && x < source.width && y < source.height
    ? { x, y }
    : null;
}

export function sameBrowserTarget(a: BrowserTarget, b: BrowserTarget): boolean {
  return (
    a.task_id === b.task_id &&
    a.page_id === b.page_id &&
    a.resource_incarnation === b.resource_incarnation
  );
}

export function browserFrameMatchesStatus(
  frame: BrowserFrame,
  status: BrowserStatus,
): boolean {
  return (
    status.state === "connected" &&
    frame.attachment_id === status.attachment_id &&
    sameBrowserTarget(frame.target, status.target) &&
    frame.navigation_id === status.navigation_id &&
    frame.width === status.viewport.width &&
    frame.height === status.viewport.height
  );
}

export function browserInput(
  frame: BrowserFrame,
  status: BrowserStatus,
  sequence: number,
  action: BrowserCoordinateAction,
): BrowserInput | null {
  if (
    !status.allow_input ||
    status.dialog !== null ||
    !browserFrameMatchesStatus(frame, status) ||
    !Number.isSafeInteger(sequence) ||
    sequence < 1
  ) {
    return null;
  }
  return {
    type: "input",
    attachment_id: frame.attachment_id,
    sequence,
    source: {
      frame_sequence: frame.frame_sequence,
      navigation_id: frame.navigation_id,
      width: frame.width,
      height: frame.height,
    },
    action,
  };
}

/** Current page dialog authority does not depend on an image existing. */
export function browserDialogInput(
  status: BrowserStatus,
  sequence: number,
  accept: boolean,
  text: string | null,
): BrowserInput | null {
  if (
    status.state !== "connected" ||
    !status.allow_input ||
    status.dialog === null ||
    !Number.isSafeInteger(sequence) ||
    sequence < 1
  ) {
    return null;
  }
  return {
    type: "input",
    attachment_id: status.attachment_id,
    sequence,
    source: null,
    action: { kind: "dialog", dialog_id: status.dialog.id, accept, text },
  };
}

export function browserPointerButton(
  button: number,
): "left" | "middle" | "right" | null {
  switch (button) {
    case 0:
      return "left";
    case 1:
      return "middle";
    case 2:
      return "right";
    default:
      return null;
  }
}

/** DOM key names differ from the SDK only for a literal space. */
export function browserKey(key: string): string | null {
  if (key === " ") {
    return "Space";
  }
  if ([...key].length === 1 && !/[\p{C}\p{Z}]/u.test(key)) {
    return key;
  }
  return [
    "Alt",
    "AltGraph",
    "Backspace",
    "CapsLock",
    "Control",
    "Delete",
    "End",
    "Enter",
    "Escape",
    "Home",
    "Insert",
    "Meta",
    "NumLock",
    "PageDown",
    "PageUp",
    "Pause",
    "PrintScreen",
    "ScrollLock",
    "Shift",
    "Space",
    "Tab",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
  ].includes(key) || /^F(?:[1-9]|1\d|2[0-4])$/.test(key)
    ? key
    : null;
}
