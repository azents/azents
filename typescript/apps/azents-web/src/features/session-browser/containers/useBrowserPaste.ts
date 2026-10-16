"use client";

import { useWindowEvent } from "@mantine/hooks";
import { useCallback, useEffect, useRef, useState } from "react";
import { browserPasteAction, browserReleaseFrame } from "../input";
import type { BrowserCoordinateAction, BrowserFrame } from "../types";
import type {
  ClipboardEventHandler,
  FocusEventHandler,
  PointerEventHandler,
} from "react";

export type BrowserPasteNotice =
  | "sent"
  | "unavailable"
  | "denied"
  | "empty"
  | "tooLarge"
  | "targetChanged"
  | "notSent";

export interface BrowserPasteControls {
  enabled: boolean;
  pending: boolean;
  notice: BrowserPasteNotice | null;
  onPaste: () => void;
  onDismiss: () => void;
}
interface Options {
  enabled: boolean;
  frame: BrowserFrame | null;
  readClipboard: (() => Promise<string>) | null;
  onAction: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  cancelInput: () => void;
}
interface Selection {
  id: string;
  receiver: HTMLTextAreaElement;
  frame: BrowserFrame;
}
interface Output {
  controls: BrowserPasteControls;
  onFocus: FocusEventHandler<HTMLTextAreaElement>;
  onPointerDown: PointerEventHandler<HTMLTextAreaElement>;
  onPaste: ClipboardEventHandler<HTMLTextAreaElement>;
}

/** Clipboard values remain in event/Promise locals, never React state or telemetry. */
export function useBrowserPaste(options: Options): Output {
  const latest = useRef(options);
  latest.current = options;
  const selected = useRef<Selection | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const epoch = useRef(0);
  const [notice, setNotice] = useState<BrowserPasteNotice | null>(null);
  const clear = useCallback((): void => {
    epoch.current += 1;
    selected.current = null;
    busy.current = false;
    setSelection(null);
    setPending(false);
    setNotice(null);
  }, []);
  const valid = useCallback((value: Selection | null): boolean => {
    const current = latest.current;
    return (
      value !== null &&
      value === selected.current &&
      current.enabled &&
      current.frame !== null &&
      value.receiver.isConnected &&
      !value.receiver.readOnly &&
      browserReleaseFrame(value.frame, current.frame) === current.frame &&
      current.frame.editables.some((editable) => editable.id === value.id)
    );
  }, []);
  const eligible = valid(selection);
  const attachment = options.frame?.attachment_id;
  const navigation = options.frame?.navigation_id;
  useWindowEvent("pagehide", clear);
  useEffect(() => {
    if (!eligible) {
      clear();
    }
  }, [eligible, clear]);
  useEffect(() => {
    const outside = (event: Event): void => {
      if (
        event.target instanceof Element &&
        (event.target === selected.current?.receiver ||
          event.target.closest("[data-browser-paste]") !== null)
      ) {
        return;
      }
      clear();
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside, true);
    const visibility = (): void => {
      if (document.hidden) {
        clear();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      epoch.current += 1;
      selected.current = null;
      busy.current = false;
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside, true);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [attachment, navigation, clear]);
  const insert = useCallback(
    (destination: Selection, text: string): void => {
      if (!valid(destination)) {
        setNotice("targetChanged");
        return;
      }
      const current = latest.current;
      const frame = current.frame;
      if (frame === null) {
        return;
      }
      if (!text) {
        setNotice("empty");
        return;
      }
      const action = browserPasteAction(frame, destination.id, text);
      if (action === null) {
        setNotice("tooLarge");
        return;
      }
      current.cancelInput();
      setNotice(current.onAction(frame, action) ? "sent" : "notSent");
    },
    [valid],
  );
  const activate = (receiver: HTMLTextAreaElement): Selection | null => {
    const id = receiver.getAttribute("data-browser-native-input");
    const frame = latest.current.frame;
    if (
      id === null ||
      frame === null ||
      !latest.current.enabled ||
      receiver.readOnly ||
      !frame.editables.some((region) => region.id === id)
    ) {
      clear();
      return null;
    }
    if (selected.current?.receiver === receiver && valid(selected.current)) {
      return selected.current;
    }
    const destination = { id, receiver, frame };
    selected.current = destination;
    setSelection(destination);
    setNotice(null);
    return destination;
  };
  return {
    controls: {
      onDismiss: () => setNotice(null),
      enabled: eligible,
      pending,
      notice,
      onPaste: () => {
        const destination = selected.current;
        if (busy.current || destination === null || !valid(destination)) {
          return;
        }
        const read = latest.current.readClipboard;
        if (read === null) {
          setNotice("unavailable");
          return;
        }
        busy.current = true;
        setPending(true);
        setNotice(null);
        const operation = ++epoch.current;
        // Invoke during the click gesture; never await other work first.
        let result: Promise<string>;
        try {
          result = read();
        } catch {
          busy.current = false;
          setPending(false);
          setNotice("denied");
          return;
        }
        void result
          .then(
            (text) => {
              if (epoch.current === operation) {
                insert(destination, text);
              }
            },
            () => {
              if (epoch.current === operation) {
                setNotice("denied");
              }
            },
          )
          .finally(() => {
            if (epoch.current === operation) {
              busy.current = false;
              setPending(false);
            }
          });
      },
    },
    onFocus: (event) => {
      activate(event.currentTarget);
    },
    onPointerDown: (event) => {
      activate(event.currentTarget);
    },
    onPaste: (event) => {
      event.preventDefault();
      event.currentTarget.value = "";
      const destination =
        document.activeElement === event.currentTarget
          ? activate(event.currentTarget)
          : null;
      if (
        destination === null ||
        event.currentTarget !== destination.receiver ||
        !valid(destination)
      ) {
        return;
      }
      epoch.current += 1;
      busy.current = false;
      setPending(false);
      insert(destination, event.clipboardData.getData("text/plain"));
    },
  };
}
