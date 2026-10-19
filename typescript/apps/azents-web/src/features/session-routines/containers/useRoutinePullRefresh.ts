"use client";

import { useEventListener, useMergedRef } from "@mantine/hooks";
import { useCallback, useRef, useState } from "react";

export type RoutineRefreshState =
  | { type: "IDLE" }
  | { type: "PULLING"; ready: boolean }
  | { type: "REFRESHING" }
  | { type: "ERROR" };

interface PullStart {
  x: number;
  y: number;
}

const passiveTouch = { passive: true };
const cancellableTouch = { passive: false };

export function useRoutinePullRefresh(onRefresh: () => void | Promise<void>): {
  viewportRef: (node: HTMLDivElement | null) => void;
  state: RoutineRefreshState;
  refresh: () => Promise<void>;
  getScrollTop: () => number;
  restoreScroll: (top: number) => void;
} {
  const [state, setState] = useState<RoutineRefreshState>({ type: "IDLE" });
  const elementRef = useRef<HTMLDivElement | null>(null);
  const start = useRef<PullStart | null>(null);
  const ready = useRef(false);
  const busy = useRef(false);

  async function refresh(): Promise<void> {
    if (busy.current) {
      return;
    }
    busy.current = true;
    setState({ type: "REFRESHING" });
    try {
      await onRefresh();
      setState({ type: "IDLE" });
    } catch {
      setState({ type: "ERROR" });
    } finally {
      busy.current = false;
    }
  }

  function reset(): void {
    start.current = null;
    ready.current = false;
    if (!busy.current) {
      setState({ type: "IDLE" });
    }
  }

  const startRef = useEventListener(
    "touchstart",
    (event: TouchEvent) => {
      if (busy.current || !(event.currentTarget instanceof HTMLElement)) {
        return;
      }
      const touch = event.touches[0];
      if (
        event.touches.length !== 1 ||
        !touch ||
        event.currentTarget.scrollTop > 0
      ) {
        reset();
        return;
      }
      start.current = { x: touch.clientX, y: touch.clientY };
      ready.current = false;
    },
    passiveTouch,
  );
  const moveRef = useEventListener(
    "touchmove",
    (event: TouchEvent) => {
      const origin = start.current;
      const touch = event.touches[0];
      if (origin === null || busy.current || !touch) {
        return;
      }
      const distance = touch.clientY - origin.y;
      if (
        event.touches.length !== 1 ||
        distance <= 0 ||
        Math.abs(touch.clientX - origin.x) > distance
      ) {
        reset();
        return;
      }
      if (
        event.currentTarget instanceof HTMLElement &&
        event.currentTarget.scrollTop > 0
      ) {
        reset();
        return;
      }
      if (!event.cancelable) {
        reset();
        return;
      }
      event.preventDefault();
      ready.current = distance >= 64;
      setState({ type: "PULLING", ready: ready.current });
    },
    cancellableTouch,
  );
  const endRef = useEventListener("touchend", () => {
    const shouldRefresh = ready.current;
    reset();
    if (shouldRefresh) {
      void refresh();
    }
  });
  const cancelRef = useEventListener("touchcancel", reset);
  const viewportRef = useMergedRef(
    elementRef,
    startRef,
    moveRef,
    endRef,
    cancelRef,
  );
  const getScrollTop = useCallback(
    (): number => elementRef.current?.scrollTop ?? 0,
    [],
  );
  const restoreScroll = useCallback((top: number): void => {
    elementRef.current?.scrollTo({ top });
  }, []);
  return {
    viewportRef,
    state,
    refresh,
    getScrollTop,
    restoreScroll,
  };
}
