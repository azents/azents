"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { browserPoint, browserReleaseFrame } from "../input";
import type { BrowserCoordinateAction, BrowserFrame } from "../types";
import type { PointerEventHandler, RefObject } from "react";

interface Point {
  x: number;
  y: number;
}

type Gesture =
  | { type: "idle" }
  | { type: "tap"; id: number; start: Point; last: Point; frame: BrowserFrame }
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
  frame: BrowserFrame | null;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onAction: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  keyboardRef: RefObject<HTMLTextAreaElement | null>;
  cancelInput: () => void;
}

export interface BrowserTouchView {
  cancel: () => void;
  viewWindowRef: RefObject<HTMLDivElement | null>;
  touch: BrowserTouchHandlers;
  touchFeedback: BrowserTouchFeedback | null;
  onTouchFeedbackEnd: () => void;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Touch gestures are local until a single stationary tap completes; pinch never presses a remote pointer. */
export function useBrowserTouchView(options: Options): BrowserTouchView {
  const latest = useRef(options);
  latest.current = options;
  const viewWindowRef = useRef<HTMLDivElement>(null);
  const fingers = useRef(new Map<number, Point>());
  const gesture = useRef<Gesture>({ type: "idle" });
  const pendingScroll = useRef<Point | null>(null);
  const feedbackSequence = useRef(0);
  const [touchFeedback, setTouchFeedback] =
    useState<BrowserTouchFeedback | null>(null);
  const clear = useCallback((): void => {
    fingers.current.clear();
    gesture.current = { type: "idle" };
    pendingScroll.current = null;
    setTouchFeedback(null);
  }, []);
  const attachment = options.frame?.attachment_id;
  const navigation = options.frame?.navigation_id;
  useEffect(() => {
    clear();
    window.addEventListener("blur", clear);
    window.addEventListener("pagehide", clear);
    const visibility = (): void => {
      if (document.hidden) {
        clear();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      clear();
      window.removeEventListener("blur", clear);
      window.removeEventListener("pagehide", clear);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [options.enabled, options.canInput, attachment, navigation, clear]);
  useLayoutEffect(() => {
    const window = viewWindowRef.current;
    const scroll = pendingScroll.current;
    pendingScroll.current = null;
    if (window !== null && scroll !== null) {
      window.scrollLeft = scroll.x;
      window.scrollTop = scroll.y;
    }
  }, [options.zoom]);

  const touch: BrowserTouchHandlers = {
    onPointerDown: (event) => {
      const current = latest.current;
      const window = viewWindowRef.current;
      if (!current.enabled || current.frame === null || window === null) {
        return;
      }
      const point = { x: event.clientX, y: event.clientY };
      fingers.current.set(event.pointerId, point);
      event.currentTarget.setPointerCapture(event.pointerId);
      if (fingers.current.size === 1) {
        current.cancelInput();
        gesture.current = {
          type: "tap",
          id: event.pointerId,
          start: point,
          last: point,
          frame: current.frame,
        };
      } else if (fingers.current.size === 2) {
        current.cancelInput();
        const [a = null, b = null] = [...fingers.current.values()];
        if (a === null || b === null) {
          return;
        }
        const bounds = window.getBoundingClientRect();
        gesture.current = {
          type: "pinch",
          distance: Math.max(1, distance(a, b)),
          zoom: current.zoom,
          anchor: {
            x: window.scrollLeft + (a.x + b.x) / 2 - bounds.left,
            y: window.scrollTop + (a.y + b.y) / 2 - bounds.top,
          },
        };
      } else {
        gesture.current = { type: "blocked" };
      }
      // Suppress compatibility mousedown focus, which would steal the receiver focus after pointerup.
      // Keyboard focus is deferred to the trusted touch-end activation, not this pointerdown.
      event.preventDefault();
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
        const bounds = window.getBoundingClientRect();
        pendingScroll.current = {
          x:
            (held.anchor.x * zoom) / held.zoom -
            ((a.x + b.x) / 2 - bounds.left),
          y:
            (held.anchor.y * zoom) / held.zoom - ((a.y + b.y) / 2 - bounds.top),
        };
        if (zoom === current.zoom) {
          window.scrollLeft = pendingScroll.current.x;
          window.scrollTop = pendingScroll.current.y;
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
            feedbackSequence.current += 1;
            setTouchFeedback({
              id: feedbackSequence.current,
              x: ((event.clientX - bounds.left) / bounds.width) * 100,
              y: ((event.clientY - bounds.top) / bounds.height) * 100,
            });
            if (current.canInput) {
              // Run synchronously in the trusted touch-end activation, before any transport response.
              const field = current.keyboardRef.current;
              if (field !== null) {
                if (document.activeElement === field) {
                  field.blur();
                }
                field.focus({ preventScroll: true });
              }
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
    cancel: clear,
    viewWindowRef,
    touch,
    touchFeedback,
    onTouchFeedbackEnd: () => setTouchFeedback(null),
  };
}
