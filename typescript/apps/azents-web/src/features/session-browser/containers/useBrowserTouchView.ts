"use client";
import { useWindowEvent } from "@mantine/hooks";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { browserPoint, browserReleaseFrame } from "../input";
import { useBrowserDirectTouch } from "./useBrowserDirectTouch";
import type { BrowserInteractionHandlers } from "../components/SessionBrowserPanel";
import type { BrowserCoordinateAction, BrowserFrame } from "../types";
import type { BrowserDirectTouchControls } from "./useBrowserDirectTouch";
import type { PointerEventHandler, RefObject } from "react";

interface Point {
  x: number;
  y: number;
}

type Gesture =
  | { type: "idle" }
  | {
      type: "tap";
      id: number;
      start: Point;
      last: Point;
      frame: BrowserFrame;
      nativeInput: boolean;
      receiver: HTMLTextAreaElement | null;
    }
  | { type: "pan"; id: number; last: Point }
  | { type: "pinch"; distance: number; zoom: number; anchor: Point }
  | { type: "blocked" };

export interface BrowserTouchFeedback extends Point {
  id: number;
}

export interface BrowserTouchHandlers {
  onPointerDown: PointerEventHandler<HTMLDivElement>;
  onPointerMove: PointerEventHandler<HTMLDivElement>;
  onPointerUp: PointerEventHandler<HTMLDivElement>;
  onPointerCancel: PointerEventHandler<HTMLDivElement>;
  onLostPointerCapture: PointerEventHandler<HTMLDivElement>;
}

interface Options {
  enabled: boolean;
  canInput: boolean;
  pendingInputs: number;
  interrupted: boolean;
  frame: BrowserFrame | null;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onAction: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  keyboardRef: RefObject<HTMLTextAreaElement | null>;
  cancelInput: () => void;
  mouse: BrowserInteractionHandlers | null;
}

export interface BrowserTouchView {
  frame: BrowserFrame | null;
  direct: BrowserDirectTouchControls;
  cancel: () => void;
  viewWindowRef: RefObject<HTMLDivElement | null>;
  touch: BrowserTouchHandlers;
  pan: BrowserTouchHandlers;
  touchFeedback: BrowserTouchFeedback | null;
  onTouchFeedbackEnd: () => void;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Preserve local browsing gestures unless direct touch was explicitly enabled. */
export function useBrowserTouchView(options: Options): BrowserTouchView {
  const direct = useBrowserDirectTouch({
    enabled: options.enabled && options.canInput,
    frame: options.frame,
    pendingInputs: options.pendingInputs,
    interrupted: options.interrupted,
    keyboardRef: options.keyboardRef,
    onAction: options.onAction,
    cancelInput: options.cancelInput,
  });
  const latest = useRef(options);
  latest.current = options;
  const viewWindowRef = useRef<HTMLDivElement>(null);
  const fingers = useRef(new Map<number, Point>());
  const remoteMouse = useRef(new Set<number>());
  const gesture = useRef<Gesture>({ type: "idle" });
  const pendingScroll = useRef<{ anchor: Point; client: Point } | null>(null);
  const feedbackSequence = useRef(0);
  const [touchFeedback, setTouchFeedback] =
    useState<BrowserTouchFeedback | null>(null);
  const clear = useCallback((): void => {
    fingers.current.clear();
    remoteMouse.current.clear();
    gesture.current = { type: "idle" };
    pendingScroll.current = null;
    setTouchFeedback(null);
  }, []);
  const attachment = options.frame?.attachment_id;
  const navigation = options.frame?.navigation_id;
  useWindowEvent("blur", clear);
  useWindowEvent("pagehide", clear);
  useEffect(() => {
    clear();
    const visibility = (): void => {
      if (document.hidden) {
        clear();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      clear();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [options.enabled, options.canInput, attachment, navigation, clear]);
  useLayoutEffect(() => {
    const window = viewWindowRef.current;
    const scroll = pendingScroll.current;
    pendingScroll.current = null;
    if (window !== null && scroll !== null) {
      const bounds = window.firstElementChild?.getBoundingClientRect() ?? null;
      if (bounds !== null) {
        window.scrollLeft +=
          bounds.left + bounds.width * scroll.anchor.x - scroll.client.x;
        window.scrollTop +=
          bounds.top + bounds.height * scroll.anchor.y - scroll.client.y;
      }
    } else if (window !== null && options.zoom === 1) {
      window.scrollLeft = 0;
      window.scrollTop = 0;
    }
  }, [options.zoom]);
  // Capture non-passively so Ctrl+wheel never zooms the host or scrolls the site.
  useEffect(() => {
    if (!options.enabled) {
      return;
    }
    const wheel = (event: WheelEvent): void => {
      const view = viewWindowRef.current;
      if (
        !event.ctrlKey ||
        view === null ||
        !(event.target instanceof Node) ||
        !view.contains(event.target)
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const current = latest.current;
      const bounds = view.firstElementChild?.getBoundingClientRect() ?? null;
      if (
        bounds === null ||
        bounds.width <= 0 ||
        bounds.height <= 0 ||
        !Number.isFinite(event.deltaY) ||
        direct.controls.pressed ||
        direct.controls.sending
      ) {
        return;
      }
      const delta =
        event.deltaY *
        (event.deltaMode === 1
          ? 16
          : event.deltaMode === 2
            ? view.clientHeight
            : 1);
      const zoom = Math.max(
        1,
        Math.min(3, current.zoom * Math.exp(-delta * 0.002)),
      );
      if (zoom === current.zoom) {
        return;
      }
      clear();
      pendingScroll.current = {
        anchor: {
          x: Math.max(
            0,
            Math.min(1, (event.clientX - bounds.left) / bounds.width),
          ),
          y: Math.max(
            0,
            Math.min(1, (event.clientY - bounds.top) / bounds.height),
          ),
        },
        client: { x: event.clientX, y: event.clientY },
      };
      current.cancelInput();
      current.onZoomChange(zoom);
    };
    document.addEventListener("wheel", wheel, {
      passive: false,
      capture: true,
    });
    return () =>
      document.removeEventListener("wheel", wheel, { capture: true });
  }, [
    options.enabled,
    direct.controls.pressed,
    direct.controls.sending,
    clear,
  ]);

  const touch: BrowserTouchHandlers = {
    onPointerDown: (event) => {
      const current = latest.current;
      const window = viewWindowRef.current;
      if (!current.enabled || current.frame === null || window === null) {
        return;
      }
      const point = { x: event.clientX, y: event.clientY };
      fingers.current.set(event.pointerId, point);
      const nativeInput =
        event.target instanceof HTMLTextAreaElement &&
        event.target.hasAttribute("data-browser-native-input") &&
        current.canInput &&
        !event.target.readOnly;
      if (!nativeInput) {
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      if (fingers.current.size === 1) {
        current.cancelInput();
        gesture.current = {
          type: "tap",
          id: event.pointerId,
          start: point,
          last: point,
          frame: current.frame,
          nativeInput,
          receiver:
            nativeInput && event.target instanceof HTMLTextAreaElement
              ? event.target
              : null,
        };
      } else if (fingers.current.size === 2) {
        current.cancelInput();
        current.keyboardRef.current?.blur();
        const [a = null, b = null] = [...fingers.current.values()];
        if (a === null || b === null) {
          return;
        }
        const bounds = event.currentTarget.getBoundingClientRect();
        gesture.current = {
          type: "pinch",
          distance: Math.max(1, distance(a, b)),
          zoom: current.zoom,
          anchor: {
            x: ((a.x + b.x) / 2 - bounds.left) / bounds.width,
            y: ((a.y + b.y) / 2 - bounds.top) / bounds.height,
          },
        };
      } else {
        gesture.current = { type: "blocked" };
      }
      // Native editable hits use their own trusted touch activation.
      // Other image interactions must not request a software keyboard.
      if (!nativeInput || fingers.current.size !== 1) {
        event.preventDefault();
      }
    },
    onPointerMove: (event) => {
      const current = latest.current;
      const window = viewWindowRef.current;
      if (
        !current.enabled ||
        window === null ||
        !fingers.current.has(event.pointerId)
      ) {
        return;
      }
      const point = { x: event.clientX, y: event.clientY };
      fingers.current.set(event.pointerId, point);
      let held = gesture.current;
      if (held.type === "pinch") {
        const [a = null, b = null] = [...fingers.current.values()];
        if (a === null || b === null) {
          return;
        }
        const zoom = Math.max(
          1,
          Math.min(3, (held.zoom * distance(a, b)) / held.distance),
        );
        pendingScroll.current = {
          anchor: held.anchor,
          client: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        };
        if (zoom === current.zoom) {
          const bounds = event.currentTarget.getBoundingClientRect();
          window.scrollLeft +=
            bounds.left +
            bounds.width * held.anchor.x -
            pendingScroll.current.client.x;
          window.scrollTop +=
            bounds.top +
            bounds.height * held.anchor.y -
            pendingScroll.current.client.y;
          pendingScroll.current = null;
        } else {
          current.onZoomChange(zoom);
        }
        event.preventDefault();
        return;
      }
      if (held.type === "tap" && distance(held.start, point) > 8) {
        held = { type: "pan", id: held.id, last: held.last };
        gesture.current = held;
      }
      if (
        (held.type === "pan" || held.type === "tap") &&
        held.id === event.pointerId
      ) {
        if (held.type === "pan") {
          const dx = held.last.x - point.x;
          const dy = held.last.y - point.y;
          if (current.zoom > 1) {
            window.scrollLeft += dx;
            window.scrollTop += dy;
          } else if (current.canInput && current.frame !== null) {
            const remote = browserPoint(
              point.x,
              point.y,
              event.currentTarget.getBoundingClientRect(),
              current.frame,
            );
            if (remote !== null) {
              const scale =
                current.frame.width /
                event.currentTarget.getBoundingClientRect().width;
              current.onAction(current.frame, {
                kind: "wheel",
                ...remote,
                delta_x: dx * scale,
                delta_y: dy * scale,
              });
            }
          }
          event.preventDefault();
        }
        gesture.current = { ...held, last: point };
      }
    },
    onPointerUp: (event) => {
      const held = gesture.current;
      fingers.current.delete(event.pointerId);
      gesture.current =
        fingers.current.size === 0 ? { type: "idle" } : { type: "blocked" };
      if (
        held.type === "tap" &&
        held.id === event.pointerId &&
        distance(held.start, { x: event.clientX, y: event.clientY }) <= 8
      ) {
        const current = latest.current;
        const source = current.frame;
        if (
          current.enabled &&
          source !== null &&
          browserReleaseFrame(held.frame, source) === source
        ) {
          const bounds = event.currentTarget.getBoundingClientRect();
          const point = browserPoint(
            event.clientX,
            event.clientY,
            bounds,
            source,
          );
          if (point !== null) {
            if (!held.nativeInput && event.pointerType === "touch") {
              current.keyboardRef.current?.blur();
            } else if (
              held.receiver !== null &&
              held.receiver.isConnected &&
              !held.receiver.readOnly &&
              document.activeElement !== held.receiver
            ) {
              // Keep focus inside this completed trusted tap, including after a modal closes.
              held.receiver.focus({ preventScroll: true });
            }
            if (event.pointerType === "touch") {
              feedbackSequence.current += 1;
              setTouchFeedback({
                id: feedbackSequence.current,
                x: ((event.clientX - bounds.left) / bounds.width) * 100,
                y: ((event.clientY - bounds.top) / bounds.height) * 100,
              });
            }
            if (current.canInput) {
              if (
                current.onAction(source, {
                  kind: "pointer",
                  phase: "down",
                  ...point,
                  button: "left",
                })
              ) {
                if (
                  !current.onAction(source, {
                    kind: "pointer",
                    phase: "up",
                    ...point,
                    button: "left",
                  })
                ) {
                  current.onAction(source, {
                    kind: "pointer",
                    phase: "cancel",
                    ...point,
                    button: null,
                  });
                }
              }
            }
            if (event.pointerType !== "touch" && !held.nativeInput) {
              event.currentTarget
                .querySelector<HTMLTextAreaElement>(
                  "textarea:not([data-browser-native-input])",
                )
                ?.focus({ preventScroll: true });
            }
          }
        }
      }
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    },
    onPointerCancel: clear,
    onLostPointerCapture: (event) => {
      if (fingers.current.has(event.pointerId)) {
        clear();
      }
    },
  };
  return {
    frame: options.frame,
    direct: {
      ...direct.controls,
      onToggle: () => {
        clear();
        direct.controls.onToggle();
      },
    },
    cancel: () => {
      clear();
      direct.cancel();
    },
    viewWindowRef,
    pan: {
      onPointerDown: (event) => {
        if (
          event.button !== 0 ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey ||
          event.altKey
        ) {
          remoteMouse.current.add(event.pointerId);
          latest.current.mouse?.onPointerDown(event);
        } else {
          touch.onPointerDown(event);
        }
      },
      onPointerMove: (event) => {
        if (
          remoteMouse.current.has(event.pointerId) ||
          !fingers.current.has(event.pointerId)
        ) {
          latest.current.mouse?.onPointerMove(event);
        } else {
          touch.onPointerMove(event);
        }
      },
      onPointerUp: (event) => {
        if (remoteMouse.current.delete(event.pointerId)) {
          latest.current.mouse?.onPointerUp(event);
        } else {
          touch.onPointerUp(event);
        }
      },
      onPointerCancel: (event) => {
        if (remoteMouse.current.delete(event.pointerId)) {
          latest.current.mouse?.onPointerCancel(event);
        } else {
          touch.onPointerCancel(event);
        }
      },
      onLostPointerCapture: (event) => {
        if (remoteMouse.current.delete(event.pointerId)) {
          latest.current.mouse?.onLostPointerCapture(event);
        } else {
          touch.onLostPointerCapture(event);
        }
      },
    },
    touch: direct.controls.active ? direct.touch : touch,
    touchFeedback,
    onTouchFeedbackEnd: () => setTouchFeedback(null),
  };
}
