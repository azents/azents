import { useCallback, useLayoutEffect, useRef } from "react";
import { useBrowserToolbarTouch } from "./useBrowserToolbarTouch";
import type { RefCallback, RefObject } from "react";

export interface BrowserManualKeyboardControls {
  enabled: boolean;
  receiverRef: RefObject<HTMLTextAreaElement | null>;
  buttonRef: RefCallback<HTMLButtonElement>;
  onOpen: () => void;
  onBlur: () => void;
}

/** Explicit local keyboard activation; remote focus and input authority stay unchanged. */
export function useBrowserManualKeyboard(options: {
  enabled: boolean;
  scope: string;
  cancelInput: () => void;
}): BrowserManualKeyboardControls {
  const latest = useRef(options);
  latest.current = options;
  const receiverRef = useRef<HTMLTextAreaElement>(null);
  const reset = useCallback((): void => {
    const receiver = receiverRef.current;
    if (receiver === null) {
      return;
    }
    receiver.inputMode = "none";
    receiver.value = "";
    if (document.activeElement === receiver) {
      latest.current.cancelInput();
      receiver.blur();
    }
  }, []);
  useLayoutEffect(() => {
    reset();
    const hidden = (): void => {
      if (document.hidden) {
        reset();
      }
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", reset);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", reset);
      reset();
    };
  }, [options.enabled, options.scope, reset]);
  const onOpen = useCallback((): void => {
    const receiver = receiverRef.current;
    if (
      !latest.current.enabled ||
      receiver === null ||
      !receiver.isConnected ||
      receiver.readOnly ||
      document.hidden
    ) {
      return;
    }
    latest.current.cancelInput();
    // Refocus inside this trusted gesture, including a previously focused mode=none receiver.
    receiver.blur();
    receiver.inputMode = "text";
    receiver.focus({ preventScroll: true });
  }, []);
  const buttonRef = useBrowserToolbarTouch(onOpen);
  return {
    enabled: options.enabled,
    receiverRef,
    buttonRef,
    onOpen,
    onBlur: reset,
  };
}
