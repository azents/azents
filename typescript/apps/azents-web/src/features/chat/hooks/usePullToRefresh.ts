"use client";

/**
 * Mobile pull-to-refresh hook.
 *
 * ScrollArea viewport  of touch event subscribes to pull calculate distance.
 * scrollTop  0 and user below with pull during toonly operate.
 * threshold(PULL_THRESHOLD) above text when released `onRefresh`  run and,
 * completetext whentext `isRefreshing` status keeps..
 *
 * Desktop environment in touch event does not occur, so naturally disabled.
 *
 * Smoothness:
 * - while dragging `isDragging: true`  with, consumer CSS transition  turns off
 *   finger keeps following uninterrupted.
 * - touchmove each `setState`  instead of calling latest value ref  to collect
 *   rAF  frame to  textonly flush text avoid excessive rerenders.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/** trigger threshold (px) */
export const PULL_THRESHOLD = 56;
/** maximum pull distance (px) — visual feedback upper bound */
const MAX_PULL = 96;
/** resistance factor — actual delta * RESISTANCE translate only by */
const RESISTANCE = 0.5;

interface UsePullToRefreshOptions {
  /** ScrollArea viewport element ref */
  viewportRef: RefObject<HTMLDivElement | null>;
  /** refresh callback — completetext whentext keep spinner */
  onRefresh: () => Promise<unknown>;
  /** false when pull ignore (text: un loading) */
  enabled?: boolean;
}

interface UsePullToRefreshResult {
  /** current translate distance (px). refreshing during to PULL_THRESHOLD. */
  pullDistance: number;
  /** new withandtext whether in progress */
  isRefreshing: boolean;
  /** threshold above pulled statuswhether (UI for UI hint) */
  canRelease: boolean;
  /** user current currently pulling with finger (CSS transition for disabling) */
  isDragging: boolean;
}

export function usePullToRefresh({
  viewportRef,
  onRefresh,
  enabled = true,
}: UsePullToRefreshOptions): UsePullToRefreshResult {
  const [pullDistance, setPullDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // refs — stale closure prevention + rAF based status flush
  const startYRef = useRef<number | null>(null);
  const pendingPullRef = useRef(0);
  const committedPullRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const isRefreshingRef = useRef(false);
  const enabledRef = useRef(enabled);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    isRefreshingRef.current = isRefreshing;
  }, [isRefreshing]);

  /** pending → committed → setState  rAF  frame to  textonly run */
  const schedulePullFlush = useCallback((): void => {
    if (rafRef.current !== null) {
      return;
    }
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const next = pendingPullRef.current;
      if (next !== committedPullRef.current) {
        committedPullRef.current = next;
        setPullDistance(next);
      }
    });
  }, []);

  /** pull  immediately 0  with reset to 0 and clear pending */
  const resetPull = useCallback((): void => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    pendingPullRef.current = 0;
    committedPullRef.current = 0;
    setPullDistance(0);
  }, []);

  const triggerRefresh = useCallback(async (): Promise<void> => {
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
      resetPull();
    }
  }, [onRefresh, resetPull]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const handleTouchStart = (e: TouchEvent): void => {
      if (!enabledRef.current || isRefreshingRef.current) {
        return;
      }
      if (viewport.scrollTop > 0) {
        return;
      }
      const touch = e.touches[0];
      if (!touch) {
        return;
      }
      startYRef.current = touch.clientY;
      pendingPullRef.current = 0;
      setIsDragging(true);
    };

    const handleTouchMove = (e: TouchEvent): void => {
      if (startYRef.current === null) {
        return;
      }
      if (viewport.scrollTop > 0) {
        // user above with scrolls back up → pull cancel
        startYRef.current = null;
        pendingPullRef.current = 0;
        setIsDragging(false);
        resetPull();
        return;
      }
      const touch = e.touches[0];
      if (!touch) {
        return;
      }
      const delta = touch.clientY - startYRef.current;
      if (delta <= 0) {
        pendingPullRef.current = 0;
        schedulePullFlush();
        return;
      }
      // default scroll(rubber-band) prevention
      e.preventDefault();
      pendingPullRef.current = Math.min(delta * RESISTANCE, MAX_PULL);
      schedulePullFlush();
    };

    const handleTouchEnd = (): void => {
      const wasPulling = startYRef.current !== null;
      startYRef.current = null;
      if (!wasPulling) {
        return;
      }
      setIsDragging(false);
      // ensure final flush — commit before ref value with threshold judge.
      const finalDistance = pendingPullRef.current;
      if (finalDistance >= PULL_THRESHOLD) {
        // refresh during indicator  PULL_THRESHOLD fixed (below displayDistance see).
        pendingPullRef.current = PULL_THRESHOLD;
        committedPullRef.current = PULL_THRESHOLD;
        setPullDistance(PULL_THRESHOLD);
        void triggerRefresh();
      } else {
        resetPull();
      }
    };

    const handleTouchCancel = (): void => {
      startYRef.current = null;
      setIsDragging(false);
      if (!isRefreshingRef.current) {
        resetPull();
      }
    };

    viewport.addEventListener("touchstart", handleTouchStart, {
      passive: true,
    });
    viewport.addEventListener("touchmove", handleTouchMove, { passive: false });
    viewport.addEventListener("touchend", handleTouchEnd);
    viewport.addEventListener("touchcancel", handleTouchCancel);

    return () => {
      viewport.removeEventListener("touchstart", handleTouchStart);
      viewport.removeEventListener("touchmove", handleTouchMove);
      viewport.removeEventListener("touchend", handleTouchEnd);
      viewport.removeEventListener("touchcancel", handleTouchCancel);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [viewportRef, triggerRefresh, resetPull, schedulePullFlush]);

  const displayDistance = isRefreshing ? PULL_THRESHOLD : pullDistance;

  return {
    pullDistance: displayDistance,
    isRefreshing,
    canRelease: pullDistance >= PULL_THRESHOLD,
    isDragging,
  };
}
