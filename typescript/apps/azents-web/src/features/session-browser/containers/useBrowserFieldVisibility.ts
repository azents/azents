import { rem } from "@mantine/core";
import { useLayoutEffect } from "react";
import type { BrowserEditorViewport } from "./useBrowserEditorViewport";
import type { RefObject } from "react";

interface Options {
  enabled: boolean;
  viewport: BrowserEditorViewport | null;
  viewWindowRef: RefObject<HTMLDivElement | null>;
}

/** Reveal the selected native receiver in local viewing space without remote input. */
export function useBrowserFieldVisibility({
  enabled,
  viewport,
  viewWindowRef,
}: Options): void {
  useLayoutEffect(() => {
    const view = viewWindowRef.current;
    if (!enabled || viewport === null || view === null) {
      return;
    }
    const toolbar = view.ownerDocument.querySelector<HTMLElement>(
      "[data-browser-input-toolbar]",
    );
    if (toolbar === null) {
      return;
    }
    const previousPadding = view.style.paddingBottom;
    const align = (): void => {
      const receiver = view.ownerDocument.activeElement;
      if (
        !(receiver instanceof HTMLElement) ||
        !view.contains(receiver) ||
        !receiver.hasAttribute("data-browser-native-input")
      ) {
        return;
      }
      const visibleBottom = viewport.top + viewport.height;
      const viewBounds = view.getBoundingClientRect();
      const toolbarTop = toolbar.getBoundingClientRect().top;
      const covered = Math.max(
        0,
        viewBounds.bottom - Math.min(visibleBottom, toolbarTop),
      );
      view.style.paddingBottom = rem(covered + 12);
      const bounds = receiver.getBoundingClientRect();
      const top = Math.max(viewBounds.top, viewport.top) + 12;
      const bottom =
        Math.min(viewBounds.bottom, visibleBottom, toolbarTop) - 12;
      if (bottom <= top) {
        return;
      }
      const context = Math.min(
        bounds.height,
        Math.max(0, bottom - top - bounds.height),
      );
      const delta =
        bounds.bottom > bottom
          ? bounds.bottom - bottom
          : bounds.top - context < top
            ? bounds.top - context - top
            : 0;
      if (Math.abs(delta) > 0.5) {
        view.scrollTop += delta;
      }
    };
    align();
    const observer = new ResizeObserver(align);
    observer.observe(view, { box: "border-box" });
    observer.observe(toolbar, { box: "border-box" });
    view.ownerDocument.addEventListener("focusin", align);
    return () => {
      observer.disconnect();
      view.ownerDocument.removeEventListener("focusin", align);
      view.style.paddingBottom = previousPadding;
    };
  }, [enabled, viewport, viewWindowRef]);
}
