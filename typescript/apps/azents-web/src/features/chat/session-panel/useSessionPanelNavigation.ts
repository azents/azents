"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getTabOverflow } from "./sessionPanel";
import type { SessionPanelView } from "./sessionPanel";
import type { KeyboardEvent, RefObject } from "react";

export interface SessionPanelNavigation {
  viewportRef: RefObject<HTMLDivElement | null>;
  canScrollPrevious: boolean;
  canScrollNext: boolean;
  onScroll: () => void;
  scrollPrevious: () => void;
  scrollNext: () => void;
  onTabKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}

export function useSessionPanelNavigation(
  activeId: SessionPanelView,
  mobile: boolean,
): SessionPanelNavigation {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState({ previous: false, next: false });
  const measure = useCallback((): void => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const next = getTabOverflow(
      viewport.scrollLeft,
      viewport.clientWidth,
      viewport.scrollWidth,
    );
    setOverflow((current) =>
      current.previous === next.previous && current.next === next.next
        ? current
        : next,
    );
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const reveal = (): void => {
      const selected = viewport.querySelector<HTMLElement>(
        '[aria-selected="true"]',
      );
      if (selected) {
        if (mobile) {
          viewport.scrollLeft = Math.max(
            0,
            selected.offsetLeft -
              (viewport.clientWidth - selected.offsetWidth) / 2,
          );
        } else {
          selected.scrollIntoView({ block: "nearest", inline: "nearest" });
        }
      }
      measure();
    };
    reveal();
    const observer = new ResizeObserver(reveal);
    observer.observe(viewport);
    for (const child of viewport.children) {
      observer.observe(child);
    }
    return () => observer.disconnect();
  }, [activeId, mobile, measure]);

  const scroll = useCallback(
    (direction: number): void => {
      const viewport = viewportRef.current;
      if (!viewport) {
        return;
      }
      viewport.scrollBy({ left: direction * viewport.clientWidth * 0.65 });
      measure();
    },
    [measure],
  );

  const onTabKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>): void => {
      const viewport = viewportRef.current;
      if (!viewport) {
        return;
      }
      const tabs = Array.from(
        viewport.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
      );
      const index = tabs.indexOf(event.currentTarget);
      let next: number;
      switch (event.key) {
        case "Home":
          next = 0;
          break;
        case "End":
          next = tabs.length - 1;
          break;
        case "ArrowRight":
          if (!mobile) {
            return;
          }
          next = (index + 1) % tabs.length;
          break;
        case "ArrowLeft":
          if (!mobile) {
            return;
          }
          next = (index - 1 + tabs.length) % tabs.length;
          break;
        case "ArrowDown":
          if (mobile) {
            return;
          }
          next = (index + 1) % tabs.length;
          break;
        case "ArrowUp":
          if (mobile) {
            return;
          }
          next = (index - 1 + tabs.length) % tabs.length;
          break;
        default:
          return;
      }
      event.preventDefault();
      tabs[next]?.focus();
      tabs[next]?.click();
    },
    [mobile],
  );

  return {
    viewportRef,
    canScrollPrevious: mobile && overflow.previous,
    canScrollNext: mobile && overflow.next,
    onScroll: measure,
    scrollPrevious: () => scroll(-1),
    scrollNext: () => scroll(1),
    onTabKeyDown,
  };
}
