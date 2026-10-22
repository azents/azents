"use client";

import { useWindowEvent } from "@mantine/hooks";
import { useCallback, useEffect, useRef, useState } from "react";
import { browserPoint, browserReleaseFrame } from "../input";
import type { BrowserCoordinateAction, BrowserFrame } from "../types";
import type { BrowserTouchHandlers } from "./useBrowserTouchView";
import type { RefObject } from "react";

interface Options {
  enabled: boolean;
  frame: BrowserFrame | null;
  pendingInputs: number;
  interrupted: boolean;
  keyboardRef: RefObject<HTMLTextAreaElement | null>;
  onAction: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  cancelInput: () => void;
}

export interface BrowserDirectTouchControls {
  active: boolean;
  pressed: boolean;
  sending: boolean;
  available: boolean;
  onToggle: () => void;
  onRelease: () => void;
}

interface HeldTouch {
  id: number;
  x: number;
  y: number;
  frame: BrowserFrame;
  receiver: HTMLTextAreaElement | null;
}

interface Output {
  controls: BrowserDirectTouchControls;
  touch: BrowserTouchHandlers;
  cancel: () => void;
}

/** Interpret an explicitly enabled single touch as a held native mouse button. */
export function useBrowserDirectTouch(options: Options): Output {
  const latest = useRef(options);
  latest.current = options;
  const [phase, setPhase] = useState<"off" | "ready" | "pressed">("off");
  const phaseRef = useRef(phase);
  const held = useRef<HeldTouch | null>(null);
  const fingers = useRef(new Set<number>());
  const blocked = useRef(false);
  const update = useCallback((value: typeof phase): void => {
    phaseRef.current = value;
    setPhase(value);
  }, []);
  const release = useCallback((): void => {
    const original = held.current;
    held.current = null;
    if (original !== null) {
      const current = latest.current;
      current.onAction(browserReleaseFrame(original.frame, current.frame), {
        kind: "pointer",
        phase: "cancel",
        x: original.x,
        y: original.y,
        button: null,
      });
    }
    if (phaseRef.current !== "off") {
      update("ready");
    }
  }, [update]);
  const reset = useCallback((): void => {
    release();
    fingers.current.clear();
    blocked.current = false;
    update("off");
  }, [release, update]);
  const attachment = options.frame?.attachment_id;
  const navigation = options.frame?.navigation_id;
  useWindowEvent("blur", reset);
  useWindowEvent("pagehide", reset);
  const endContact = (event: globalThis.PointerEvent): void => {
    fingers.current.delete(event.pointerId);
    blocked.current = fingers.current.size > 0 && blocked.current;
    // Capture loss can send the final lift outside the viewport's handlers.
    if (held.current?.id === event.pointerId) {
      release();
    }
  };
  useWindowEvent("pointerup", endContact);
  useWindowEvent("pointercancel", endContact);
  useEffect(() => {
    if (!options.enabled) {
      reset();
    }
    const visibility = (): void => {
      if (document.hidden) {
        reset();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      reset();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [options.enabled, attachment, navigation, reset]);
  useEffect(() => {
    if (options.interrupted) {
      reset();
    }
  }, [options.interrupted, reset]);

  const touch: BrowserTouchHandlers = {
    onPointerDown: (event) => {
      event.preventDefault();
      fingers.current.add(event.pointerId);
      if (fingers.current.size !== 1 || blocked.current) {
        blocked.current = true;
        release();
        return;
      }
      const current = latest.current;
      if (
        !current.enabled ||
        phaseRef.current !== "ready" ||
        current.frame === null
      ) {
        return;
      }
      const point = browserPoint(
        event.clientX,
        event.clientY,
        event.currentTarget.getBoundingClientRect(),
        current.frame,
      );
      if (point === null) {
        return;
      }
      current.cancelInput();
      const receiver =
        event.target instanceof HTMLTextAreaElement &&
        event.target.hasAttribute("data-browser-native-input") &&
        !event.target.readOnly
          ? event.target
          : null;
      if (receiver === null) {
        current.keyboardRef.current?.blur();
      } else {
        receiver.focus({ preventScroll: true });
      }
      if (
        !current.onAction(current.frame, {
          kind: "pointer",
          phase: "down",
          ...point,
          button: "left",
        })
      ) {
        return;
      }
      held.current = {
        id: event.pointerId,
        ...point,
        frame: current.frame,
        receiver,
      };
      update("pressed");
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    onPointerMove: (event) => {
      const original = held.current;
      if (original === null || original.id !== event.pointerId) {
        return;
      }
      event.preventDefault();
      const current = latest.current;
      const source = browserReleaseFrame(original.frame, current.frame);
      const point = browserPoint(
        event.clientX,
        event.clientY,
        event.currentTarget.getBoundingClientRect(),
        source,
      );
      if (
        !current.enabled ||
        source !== current.frame ||
        point === null ||
        !current.onAction(source, {
          kind: "pointer",
          phase: "move",
          ...point,
          button: null,
        })
      ) {
        blocked.current = true;
        release();
        return;
      }
      held.current = { ...original, ...point };
    },
    onPointerUp: (event) => {
      fingers.current.delete(event.pointerId);
      const original = held.current;
      if (original !== null && original.id === event.pointerId) {
        const current = latest.current;
        const source = browserReleaseFrame(original.frame, current.frame);
        const point = browserPoint(
          event.clientX,
          event.clientY,
          event.currentTarget.getBoundingClientRect(),
          source,
        );
        if (
          current.enabled &&
          source === current.frame &&
          point !== null &&
          current.onAction(source, {
            kind: "pointer",
            phase: "up",
            ...point,
            button: "left",
          })
        ) {
          held.current = null;
          update("ready");
          original.receiver?.focus({ preventScroll: true });
        } else {
          release();
        }
      }
      if (fingers.current.size === 0) {
        blocked.current = false;
      }
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    },
    onPointerCancel: (event) => {
      fingers.current.delete(event.pointerId);
      blocked.current = fingers.current.size > 0;
      release();
    },
    onLostPointerCapture: (event) => {
      if (held.current?.id === event.pointerId) {
        blocked.current = fingers.current.size > 0;
        release();
      }
    },
  };
  return {
    touch,
    cancel: release,
    controls: {
      active: phase !== "off",
      pressed: phase === "pressed",
      sending: phase === "pressed" && options.pendingInputs > 0,
      available: options.enabled && options.pendingInputs === 0,
      onToggle: () => {
        if (phaseRef.current !== "off") {
          reset();
        } else if (
          latest.current.enabled &&
          latest.current.pendingInputs === 0
        ) {
          latest.current.cancelInput();
          update("ready");
        }
      },
      onRelease: () => {
        blocked.current = fingers.current.size > 0;
        release();
      },
    },
  };
}
