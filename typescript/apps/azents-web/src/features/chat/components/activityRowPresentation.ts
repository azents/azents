import { rem } from "@mantine/core";
import { chatCollapsibleChevronSize } from "./collapsiblePresentation";
import type { DataAttributes, ScrollAreaProps } from "@mantine/core";

type ScrollViewportProps = NonNullable<ScrollAreaProps["viewportProps"]> &
  DataAttributes;

const SCROLL_BOUNDARY_TOLERANCE = 1;
const lastTouchClientY = new WeakMap<HTMLElement, number>();
const activityDetailScrollListeners = new WeakSet<HTMLElement>();

function reachesVerticalScrollBoundary(
  viewport: HTMLElement,
  deltaY: number,
): boolean {
  const maximumScrollTop = viewport.scrollHeight - viewport.clientHeight;
  if (maximumScrollTop <= SCROLL_BOUNDARY_TOLERANCE || deltaY === 0) {
    return false;
  }
  if (deltaY < 0) {
    return viewport.scrollTop <= SCROLL_BOUNDARY_TOLERANCE;
  }
  return viewport.scrollTop >= maximumScrollTop - SCROLL_BOUNDARY_TOLERANCE;
}

function activityDetailViewport(event: Event): HTMLElement | null {
  return event.currentTarget instanceof HTMLElement
    ? event.currentTarget
    : null;
}

function handleActivityDetailWheel(event: WheelEvent): void {
  const viewport = activityDetailViewport(event);
  if (
    viewport !== null &&
    event.cancelable &&
    reachesVerticalScrollBoundary(viewport, event.deltaY)
  ) {
    event.preventDefault();
  }
}

function handleActivityDetailTouchStart(event: TouchEvent): void {
  const viewport = activityDetailViewport(event);
  const touch = event.touches[0];
  if (viewport !== null && touch) {
    lastTouchClientY.set(viewport, touch.clientY);
  }
}

function handleActivityDetailTouchMove(event: TouchEvent): void {
  const viewport = activityDetailViewport(event);
  const touch = event.touches[0];
  if (viewport === null || !touch) {
    return;
  }

  const previousClientY = lastTouchClientY.get(viewport);
  lastTouchClientY.set(viewport, touch.clientY);
  if (
    typeof previousClientY === "number" &&
    event.cancelable &&
    reachesVerticalScrollBoundary(viewport, previousClientY - touch.clientY)
  ) {
    event.preventDefault();
  }
}

function clearActivityDetailTouch(event: TouchEvent): void {
  const viewport = activityDetailViewport(event);
  if (viewport !== null) {
    lastTouchClientY.delete(viewport);
  }
}

function attachActivityDetailScrollListeners(
  viewport: HTMLDivElement | null,
): void {
  if (viewport === null || activityDetailScrollListeners.has(viewport)) {
    return;
  }

  viewport.addEventListener("wheel", handleActivityDetailWheel, {
    passive: false,
  });
  viewport.addEventListener("touchstart", handleActivityDetailTouchStart, {
    passive: true,
  });
  viewport.addEventListener("touchmove", handleActivityDetailTouchMove, {
    passive: false,
  });
  viewport.addEventListener("touchend", clearActivityDetailTouch, {
    passive: true,
  });
  viewport.addEventListener("touchcancel", clearActivityDetailTouch, {
    passive: true,
  });
  activityDetailScrollListeners.add(viewport);
}

const activityDetailScrollViewportProps: ScrollViewportProps = {
  "data-activity-detail-scroll-viewport": true,
};

export const activityRowBorder =
  "1px solid var(--mantine-color-default-border)";
export const chatScrollOverscrollBehavior = "contain" as const;
export const chatScrollViewportProps: ScrollViewportProps = {
  "data-chat-scroll-viewport": true,
};
export const activityDetailScrollAreaProps = {
  overscrollBehavior: chatScrollOverscrollBehavior,
  viewportRef: attachActivityDetailScrollListeners,
  viewportProps: activityDetailScrollViewportProps,
} satisfies Pick<
  ScrollAreaProps,
  "overscrollBehavior" | "viewportProps" | "viewportRef"
>;
export const activityRowChevronSize = chatCollapsibleChevronSize;
export const activityRowDetailInset = rem(28);
export const activityDetailScrollbarSize = rem(6);
export const activityRowIconSize = 14;
export const activityRowSummarySize = "xs" as const;
export const activityRowVerticalPadding = rem(2);
