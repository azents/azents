"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { useRoutinePullRefresh } from "./useRoutinePullRefresh";
import type { RoutineRefreshState } from "./useRoutinePullRefresh";
import type { RefObject } from "react";

export interface RoutinePanelNavigation {
  detailHeading: RefObject<HTMLHeadingElement | null>;
  viewportRef: (node: HTMLDivElement | null) => void;
  refreshState: RoutineRefreshState;
  onSelect: (slug: string, trigger: HTMLElement) => void;
  onBack: () => void;
  onRefresh: () => Promise<void>;
}

export function useRoutinePanelNavigation({
  selectedSlug,
  onSelect,
  onBack,
  onRefresh,
}: {
  selectedSlug: string | null;
  onSelect: (slug: string, trigger: HTMLElement) => void;
  onBack: () => void;
  onRefresh: () => Promise<void>;
}): RoutinePanelNavigation {
  const { viewportRef, state, refresh, getScrollTop, restoreScroll } =
    useRoutinePullRefresh(onRefresh);
  const listScroll = useRef(0);
  const previousSelection = useRef(selectedSlug);
  const trigger = useRef<HTMLElement | null>(null);
  const detailHeading = useRef<HTMLHeadingElement | null>(null);

  useLayoutEffect(() => {
    if (previousSelection.current === selectedSlug) {
      return;
    }
    restoreScroll(selectedSlug === null ? listScroll.current : 0);
    previousSelection.current = selectedSlug;
  }, [selectedSlug, restoreScroll]);

  useEffect(() => {
    if (selectedSlug !== null) {
      detailHeading.current?.focus({ preventScroll: true });
    } else if (trigger.current?.isConnected) {
      trigger.current.focus({ preventScroll: true });
      trigger.current = null;
    }
  }, [selectedSlug]);

  return {
    detailHeading,
    viewportRef,
    refreshState: state,
    onRefresh: refresh,
    onSelect: (slug, element) => {
      if (selectedSlug === null) {
        listScroll.current = getScrollTop();
      }
      trigger.current = element;
      onSelect(slug, element);
    },
    onBack,
  };
}
