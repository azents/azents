"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  browserCloseDisposition,
  BrowserConnection,
  BrowserMessageQueue,
  browserReconnectDelay,
  emptyBrowserLiveState,
} from "../connection";
import type { BrowserLiveState } from "../connection";
import type {
  BrowserCoordinateAction,
  BrowserFieldResult,
  BrowserFrame,
  BrowserImage,
  BrowserTarget,
} from "../types";

export interface BrowserConnectionInfo {
  ticket: string;
  websocketUrl: string;
}
export interface BrowserConnectionOptions {
  readOnly: boolean;
  resourceKey: string;
  target: BrowserTarget | null;
  connect: () => Promise<BrowserConnectionInfo>;
  rejected: (kind: "access" | "target") => void;
  cancelInteraction: () => void;
  fieldChanged?: (result: BrowserFieldResult) => void;
}

export function browserAccessError(error: unknown): boolean {
  if (
    typeof error !== "object" ||
    error === null ||
    !("data" in error) ||
    typeof error.data !== "object" ||
    error.data === null ||
    !("code" in error.data)
  ) {
    return false;
  }
  const code = error.data.code;
  return ["UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND"].some(
    (expected) => expected === code,
  );
}

export interface BrowserConnectionOutput {
  state: BrowserLiveState;
  openField: (frame: BrowserFrame, editableId: string) => boolean;
  finishField: (text: string | null) => boolean;
  reconnect: () => void;
  coordinate: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  dialog: (accept: boolean, text: string | null) => boolean;
  displayed: (image: BrowserImage) => void;
  frameError: (image: BrowserImage) => void;
}

export function useBrowserConnection(
  options: BrowserConnectionOptions,
): BrowserConnectionOutput {
  const latest = useRef(options);
  latest.current = options;
  const client = useRef<BrowserConnection | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const [attempt, setAttempt] = useState(0);
  const targetKey =
    options.target === null ? "" : JSON.stringify(options.target);
  const baseKey = `${options.resourceKey}\u0000${targetKey}`;
  const retryState = useRef({ key: baseKey, failures: 0, uncertain: false });
  if (retryState.current.key !== baseKey) {
    retryState.current = { key: baseKey, failures: 0, uncertain: false };
  }
  const key = `${baseKey}\u0000${attempt}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  const [snapshot, setSnapshot] = useState({
    key,
    state: { ...emptyBrowserLiveState },
  });
  const epoch = useRef(0);

  useEffect(() => {
    const target = latest.current.target;
    const generation = ++epoch.current;
    if (target === null) {
      setSnapshot({ key, state: { ...emptyBrowserLiveState } });
      return;
    }
    let active = true;
    let stopped = false;
    let native: WebSocket | null = null;
    let deadline: number | null = null;
    let reconnectDeadline: number | null = null;
    const current = (): boolean =>
      active &&
      !stopped &&
      epoch.current === generation &&
      currentKey.current === key;
    const clearDeadline = (): void => {
      if (deadline !== null) {
        window.clearTimeout(deadline);
        deadline = null;
      }
    };
    const retryObservation = (code: number): void => {
      if (latest.current.readOnly) {
        return;
      }
      const delay = browserReconnectDelay(code, retryState.current.failures);
      if (delay === null) {
        return;
      }
      retryState.current.failures += 1;
      reconnectDeadline = window.setTimeout(() => {
        if (
          active &&
          !latest.current.readOnly &&
          epoch.current === generation &&
          currentKey.current === key
        ) {
          setAttempt((value) => value + 1);
        }
      }, delay);
    };
    const session = new BrowserConnection(
      target,
      (message) => {
        if (
          !current() ||
          native?.readyState !== WebSocket.OPEN ||
          native.bufferedAmount > 128 * 1024
        ) {
          return false;
        }
        try {
          native.send(message);
          return true;
        } catch (error) {
          if (!(error instanceof DOMException)) {
            throw error;
          }
          latest.current.cancelInteraction();
          session.disconnect(false);
          native.close(4500, "Browser transport failed.");
          return false;
        }
      },
      {
        create: (jpeg) =>
          URL.createObjectURL(new Blob([jpeg], { type: "image/jpeg" })),
        revoke: (url) => URL.revokeObjectURL(url),
      },
      (state) => {
        if (!current()) {
          return;
        }
        if (state.connection !== "connecting") {
          clearDeadline();
        }
        if (state.displayed !== null) {
          retryState.current.failures = 0;
        }
        if (state.outcomeUnknown) {
          retryState.current.uncertain = true;
        }
        setSnapshot({
          key,
          state: {
            ...state,
            outcomeUnknown:
              state.outcomeUnknown || retryState.current.uncertain,
          },
        });
      },
      (kind) => {
        latest.current.cancelInteraction();
        native?.close(
          kind === "access" ? 4403 : kind === "target" ? 4409 : 4500,
          "Browser attachment requires fresh admission.",
        );
      },
      (result) => latest.current.fieldChanged?.(result),
    );
    client.current = session;
    setSnapshot({
      key,
      state: {
        ...emptyBrowserLiveState,
        outcomeUnknown: retryState.current.uncertain,
      },
    });
    const invalid = (): void => {
      if (!current()) {
        return;
      }
      latest.current.cancelInteraction();
      session.disconnect(true);
      stopped = true;
      native?.close(4400, "Invalid Browser message.");
    };
    const queue = new BrowserMessageQueue(
      (message) =>
        typeof message === "string"
          ? session.receiveText(message)
          : session.receiveFrame(message),
      invalid,
    );
    deadline = window.setTimeout(() => {
      if (!current()) {
        return;
      }
      latest.current.cancelInteraction();
      session.disconnect(true);
      stopped = true;
      native?.close(4408, "Browser attachment deadline reached.");
    }, 20000);
    const open = async (): Promise<void> => {
      const canMutate = (): boolean => !latest.current.readOnly;
      if (!canMutate()) {
        return;
      }
      try {
        const info = await latest.current.connect();
        if (!canMutate() || !current()) {
          return;
        }
        native = new WebSocket(info.websocketUrl, ["azents.browser.v1"]);
        socket.current = native;
        native.binaryType = "arraybuffer";
        native.addEventListener(
          "open",
          () => {
            if (
              latest.current.readOnly ||
              !current() ||
              native?.readyState !== WebSocket.OPEN
            ) {
              return;
            }
            if (native.protocol !== "azents.browser.v1") {
              invalid();
              return;
            }
            native.send(
              JSON.stringify({ type: "attach", ticket: info.ticket, target }),
            );
          },
          { once: true },
        );
        native.addEventListener("message", (event: MessageEvent<unknown>) => {
          if (current()) {
            queue.push(event.data);
          }
        });
        native.addEventListener("error", () => {
          if (current()) {
            native?.close();
          }
        });
        native.addEventListener("close", (event) => {
          if (!current()) {
            return;
          }
          clearDeadline();
          queue.dispose();
          latest.current.cancelInteraction();
          const disposition = browserCloseDisposition(event.code);
          session.disconnect(disposition.clearImage, disposition.connection);
          stopped = true;
          if (disposition.clearProjection) {
            latest.current.rejected(event.code === 4409 ? "target" : "access");
          }
          retryObservation(event.code);
        });
      } catch (error) {
        if (!current()) {
          return;
        }
        clearDeadline();
        const denied = browserAccessError(error);
        session.disconnect(denied, denied ? "revoked" : "stale");
        stopped = true;
        if (denied) {
          latest.current.rejected("access");
        } else {
          retryObservation(4500);
        }
      }
    };
    void open();
    return () => {
      latest.current.cancelInteraction();
      active = false;
      clearDeadline();
      if (reconnectDeadline !== null) {
        window.clearTimeout(reconnectDeadline);
      }
      queue.dispose();
      session.dispose();
      if (client.current === session) {
        client.current = null;
      }
      if (socket.current === native) {
        socket.current = null;
      }
      native?.close(1000, "Browser attachment closed.");
    };
  }, [key]);

  const coordinate = useCallback(
    (frame: BrowserFrame, action: BrowserCoordinateAction): boolean =>
      !latest.current.readOnly &&
      (client.current?.coordinate(frame, action) ?? false),
    [],
  );
  const openField = useCallback(
    (frame: BrowserFrame, editableId: string): boolean =>
      !latest.current.readOnly &&
      (client.current?.openField(frame, editableId) ?? false),
    [],
  );
  const finishField = useCallback(
    (text: string | null): boolean =>
      !latest.current.readOnly && (client.current?.finishField(text) ?? false),
    [],
  );
  const dialog = useCallback(
    (accept: boolean, text: string | null): boolean =>
      !latest.current.readOnly &&
      (client.current?.dialog(accept, text) ?? false),
    [],
  );
  const displayed = useCallback((image: BrowserImage): void => {
    const session = client.current;
    if (session === null || session.snapshot().image?.url !== image.url) {
      return;
    }
    if (
      !session.displayed(image) &&
      session.snapshot().connection === "connected"
    ) {
      latest.current.cancelInteraction();
      session.disconnect(false);
      socket.current?.close(4500, "Browser frame acknowledgement failed.");
    }
  }, []);
  const frameError = useCallback((image: BrowserImage): void => {
    if (client.current?.snapshot().image?.url !== image.url) {
      return;
    }
    latest.current.cancelInteraction();
    client.current.disconnect(true);
    socket.current?.close(4400, "Browser image could not be decoded.");
  }, []);
  const reconnect = useCallback((): void => {
    if (latest.current.readOnly) {
      return;
    }
    retryState.current.failures = 0;
    setAttempt((value) => value + 1);
  }, []);
  return {
    state:
      snapshot.key === key
        ? snapshot.state
        : {
            ...emptyBrowserLiveState,
            outcomeUnknown: retryState.current.uncertain,
          },
    reconnect,
    coordinate,
    openField,
    finishField,
    dialog,
    displayed,
    frameError,
  };
}
