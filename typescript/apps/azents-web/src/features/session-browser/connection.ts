import {
  browserDialogInput,
  browserFrameMatchesStatus,
  browserInput,
  sameBrowserTarget,
} from "./input.ts";
import { decodeBrowserFrame, decodeBrowserText } from "./wire.ts";
import type {
  BrowserCoordinateAction,
  BrowserFrame,
  BrowserImage,
  BrowserInput,
  BrowserStatus,
  BrowserTarget,
} from "./types";

export interface BrowserLiveState {
  connection:
    "connecting" | "connected" | "stale" | "closed" | "unavailable" | "revoked";
  status: BrowserStatus | null;
  image: BrowserImage | null;
  displayed: BrowserFrame | null;
  conflict: boolean;
  outcomeUnknown: boolean;
  pendingInputs: number;
}

export const emptyBrowserLiveState: BrowserLiveState = {
  connection: "connecting",
  status: null,
  image: null,
  displayed: null,
  conflict: false,
  outcomeUnknown: false,
  pendingInputs: 0,
};

export interface BrowserImageUrls {
  create: (jpeg: Uint8Array<ArrayBuffer>) => string;
  revoke: (url: string) => void;
}

/** One attachment owns the displayed image plus at most one decoding replacement. */
export class BrowserConnection {
  private current: BrowserLiveState = { ...emptyBrowserLiveState };
  private active = true;
  private nextSequence = 1;
  private lastAcknowledged = 0;
  private lastFrame = 0;
  private displayedImageUrl: string | null = null;
  private readonly target: BrowserTarget;
  private readonly send: (message: string) => boolean;
  private readonly images: BrowserImageUrls;
  private readonly changed: (state: BrowserLiveState) => void;
  private readonly interrupted: (
    kind: "transport" | "target" | "access",
  ) => void;

  public constructor(
    target: BrowserTarget,
    send: (message: string) => boolean,
    images: BrowserImageUrls,
    changed: (state: BrowserLiveState) => void,
    interrupted: (kind: "transport" | "target" | "access") => void,
  ) {
    this.target = target;
    this.send = send;
    this.images = images;
    this.changed = changed;
    this.interrupted = interrupted;
  }

  public snapshot(): BrowserLiveState {
    return this.current;
  }

  private update(patch: Partial<BrowserLiveState>): void {
    this.current = { ...this.current, ...patch };
    this.changed(this.current);
  }

  public receiveText(raw: string): boolean {
    if (!this.active) {
      return false;
    }
    const event = decodeBrowserText(raw);
    if (event === null) {
      return false;
    }
    if (event.type === "status") {
      if (
        !sameBrowserTarget(event.target, this.target) ||
        (this.current.status !== null &&
          event.attachment_id !== this.current.status.attachment_id)
      ) {
        return false;
      }
      const changedNavigation =
        this.current.status?.navigation_id !== event.navigation_id ||
        this.current.status.viewport.width !== event.viewport.width ||
        this.current.status.viewport.height !== event.viewport.height;
      this.update({
        status: event,
        connection:
          event.state === "connected"
            ? "connected"
            : event.state === "closed"
              ? "closed"
              : "unavailable",
        displayed:
          changedNavigation || event.state !== "connected"
            ? null
            : this.current.displayed,
        conflict: event.conflict,
      });
      return true;
    }
    if (
      this.current.status === null ||
      event.attachment_id !== this.current.status.attachment_id ||
      event.sequence <= this.lastAcknowledged ||
      event.sequence >= this.nextSequence
    ) {
      return false;
    }
    this.lastAcknowledged = event.sequence;
    if (
      event.reason_code === "browser_read_only" ||
      event.reason_code === "browser_invalid_authority"
    ) {
      this.disconnect(true, "revoked");
      this.interrupted("access");
      return true;
    }
    if (
      event.reason_code === "browser_stale_target" ||
      event.reason_code === "browser_stale_generation"
    ) {
      this.disconnect(true, "closed");
      this.interrupted("target");
      return true;
    }
    if (
      event.reason_code === "browser_stale_input" ||
      event.reason_code === "browser_stale_frame"
    ) {
      this.disconnect(false);
      this.interrupted("transport");
      return true;
    }
    this.update({
      conflict: event.reason_code === "browser_input_conflict",
      pendingInputs: this.nextSequence - 1 - this.lastAcknowledged,
      outcomeUnknown:
        this.current.outcomeUnknown || event.outcome === "outcome_unknown",
    });
    return true;
  }

  public receiveFrame(raw: ArrayBuffer): boolean {
    if (!this.active || this.current.status === null) {
      return false;
    }
    const message = decodeBrowserFrame(raw);
    if (
      message === null ||
      message.frame.frame_sequence <= this.lastFrame ||
      !browserFrameMatchesStatus(message.frame, this.current.status)
    ) {
      return false;
    }
    this.lastFrame = message.frame.frame_sequence;
    // Keep the displayed raster available until its replacement actually loads.
    if (
      this.current.image !== null &&
      this.current.image.url !== this.displayedImageUrl
    ) {
      this.images.revoke(this.current.image.url);
    }
    const url = this.images.create(message.jpeg);
    this.update({ image: { url, frame: message.frame } });
    return true;
  }

  public displayed(image: BrowserImage): boolean {
    if (
      !this.active ||
      this.current.status === null ||
      this.current.image?.url !== image.url ||
      !browserFrameMatchesStatus(image.frame, this.current.status)
    ) {
      return false;
    }
    if (this.current.displayed?.frame_sequence === image.frame.frame_sequence) {
      return true;
    }
    if (
      !this.send(
        JSON.stringify({
          type: "frame_ack",
          attachment_id: image.frame.attachment_id,
          frame_sequence: image.frame.frame_sequence,
        }),
      )
    ) {
      return false;
    }
    if (
      this.displayedImageUrl !== null &&
      this.displayedImageUrl !== image.url
    ) {
      this.images.revoke(this.displayedImageUrl);
    }
    this.displayedImageUrl = image.url;
    this.update({ displayed: image.frame });
    return true;
  }

  private input(input: BrowserInput | null): boolean {
    if (!this.active || input === null) {
      return false;
    }
    if (this.nextSequence - this.lastAcknowledged > 128) {
      this.disconnect(false);
      this.interrupted("transport");
      return false;
    }
    const encoded = JSON.stringify(input);
    if (
      new TextEncoder().encode(encoded).length > 64 * 1024 ||
      !this.send(encoded)
    ) {
      this.update({ outcomeUnknown: true });
      this.disconnect(false);
      this.interrupted("transport");
      return false;
    }
    this.nextSequence += 1;
    this.update({
      pendingInputs: this.nextSequence - 1 - this.lastAcknowledged,
    });
    return true;
  }

  public coordinate(
    frame: BrowserFrame,
    action: BrowserCoordinateAction,
  ): boolean {
    const displayed = this.current.displayed;
    const cleanup =
      (action.kind === "pointer" && action.phase === "cancel") ||
      (action.kind === "composition" && action.phase === "cancel") ||
      (action.kind === "key" && action.phase === "up");
    if (
      (action.kind === "navigation" && this.current.pendingInputs > 0) ||
      displayed === null ||
      this.current.status === null ||
      (action.kind !== "navigation" &&
        action.kind !== "key" &&
        action.kind !== "composition" &&
        !cleanup &&
        displayed.frame_sequence !== frame.frame_sequence) ||
      displayed.attachment_id !== frame.attachment_id ||
      !sameBrowserTarget(displayed.target, frame.target) ||
      displayed.navigation_id !== frame.navigation_id ||
      displayed.width !== frame.width ||
      displayed.height !== frame.height
    ) {
      if (cleanup && this.active) {
        this.disconnect(false);
        this.interrupted("transport");
      }
      return false;
    }
    const sent = this.input(
      browserInput(displayed, this.current.status, this.nextSequence, action),
    );
    if (!sent && cleanup && this.active) {
      this.disconnect(false);
      this.interrupted("transport");
    }
    return sent;
  }

  public dialog(accept: boolean, text: string | null): boolean {
    return this.input(
      this.current.status === null
        ? null
        : browserDialogInput(
            this.current.status,
            this.nextSequence,
            accept,
            text,
          ),
    );
  }

  public disconnect(
    clear: boolean,
    connection: "stale" | "closed" | "revoked" = "stale",
  ): void {
    if (!this.active) {
      return;
    }
    this.active = false;
    const unknown =
      this.current.outcomeUnknown ||
      this.nextSequence - 1 > this.lastAcknowledged;
    if (clear && this.current.image !== null) {
      this.images.revoke(this.current.image.url);
    }
    if (
      clear &&
      this.displayedImageUrl !== null &&
      this.displayedImageUrl !== this.current.image?.url
    ) {
      this.images.revoke(this.displayedImageUrl);
    }
    if (clear) {
      this.displayedImageUrl = null;
    }
    this.update({
      connection,
      status: null,
      displayed: null,
      conflict: false,
      image: clear ? null : this.current.image,
      outcomeUnknown: unknown,
      pendingInputs: 0,
    });
  }

  public dispose(): void {
    this.active = false;
    if (this.current.image !== null) {
      this.images.revoke(this.current.image.url);
    }
    if (
      this.displayedImageUrl !== null &&
      this.displayedImageUrl !== this.current.image?.url
    ) {
      this.images.revoke(this.displayedImageUrl);
    }
    this.displayedImageUrl = null;
    this.current = { ...emptyBrowserLiveState };
  }
}

/** No asynchronous binary conversion may finish into a newer socket epoch. */
export class BrowserMessageQueue {
  private active = true;
  private pending: Array<string | ArrayBuffer | Blob> = [];
  private bytes = 0;
  private busy = false;
  private running: Promise<void> | null = null;
  private readonly receive: (message: string | ArrayBuffer) => boolean;
  private readonly failure: () => void;

  private available(): boolean {
    return this.active;
  }

  public constructor(
    receive: (message: string | ArrayBuffer) => boolean,
    failure: () => void,
  ) {
    this.receive = receive;
    this.failure = failure;
  }

  public push(message: unknown): void {
    if (!this.active) {
      return;
    }
    if (!(
      typeof message === "string" ||
      message instanceof ArrayBuffer ||
      message instanceof Blob
    )) {
      this.fail();
      return;
    }
    const size =
      typeof message === "string"
        ? new TextEncoder().encode(message).length
        : message instanceof Blob
          ? message.size
          : message.byteLength;
    if (
      size > 1024 * 1024 ||
      this.pending.length >= 8 ||
      this.bytes + size > 2 * 1024 * 1024
    ) {
      this.fail();
      return;
    }
    this.pending.push(message);
    this.bytes += size;
    if (!this.busy) {
      this.running = this.drain();
    }
  }

  private fail(): void {
    this.dispose();
    this.failure();
  }

  private async drain(): Promise<void> {
    this.busy = true;
    while (this.active && this.pending.length > 0) {
      const message = this.pending.shift() ?? null;
      if (message === null) {
        break;
      }
      const size =
        typeof message === "string"
          ? new TextEncoder().encode(message).length
          : message instanceof Blob
            ? message.size
            : message.byteLength;
      let decoded: string | ArrayBuffer;
      try {
        decoded =
          message instanceof Blob ? await message.arrayBuffer() : message;
      } catch {
        this.fail();
        return;
      }
      if (!this.available()) {
        return;
      }
      this.bytes -= size;
      if (!this.receive(decoded)) {
        this.fail();
        return;
      }
    }
    this.busy = false;
  }

  public dispose(): void {
    this.active = false;
    this.pending = [];
    this.bytes = 0;
  }

  public settled(): Promise<void> {
    return this.running ?? Promise.resolve();
  }
}

export interface BrowserCloseDisposition {
  clearImage: boolean;
  clearProjection: boolean;
  connection: "stale" | "closed" | "revoked";
}

export function browserCloseDisposition(code: number): BrowserCloseDisposition {
  const revoked = [4401, 4403, 4408].includes(code);
  return {
    clearImage: revoked || [1000, 4400, 4409].includes(code),
    clearProjection: revoked || code === 4409,
    connection: revoked
      ? "revoked"
      : [1000, 4409].includes(code)
        ? "closed"
        : "stale",
  };
}

/** Reattachment retries observation transport, never a submitted browser action. */
export function browserReconnectDelay(
  code: number,
  failures: number,
): number | null {
  return [1006, 1011, 4500].includes(code) &&
    Number.isInteger(failures) &&
    failures >= 0 &&
    failures < 3
    ? 500 * 2 ** failures
    : null;
}
