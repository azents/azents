import { useCallback, useRef } from "react";
import type { RefCallback } from "react";

/** Keep touch activation inside the trusted gesture without focusing the button. */
export function useBrowserToolbarTouch(
  onActivate: () => void,
): RefCallback<HTMLButtonElement> {
  const latest = useRef(onActivate);
  latest.current = onActivate;
  return useCallback((button: HTMLButtonElement | null) => {
    if (button === null) {
      return;
    }
    let start: { id: number; x: number; y: number } | null = null;
    const down = (event: TouchEvent): void => {
      if (button.disabled) {
        start = null;
        return;
      }
      const touch = event.changedTouches.item(0);
      start =
        event.touches.length === 1 && touch !== null
          ? { id: touch.identifier, x: touch.clientX, y: touch.clientY }
          : null;
      // Native non-passive listeners are needed for Safari focus preservation.
      event.preventDefault();
    };
    const move = (event: TouchEvent): void => {
      if (start === null) {
        return;
      }
      const touch = Array.from(event.changedTouches).find(
        (item) => item.identifier === start?.id,
      );
      if (
        !touch ||
        Math.hypot(touch.clientX - start.x, touch.clientY - start.y) > 8
      ) {
        start = null;
      }
      event.preventDefault();
    };
    const up = (event: TouchEvent): void => {
      const held = start;
      start = null;
      // Suppress the synthetic mouse click; keyboard/mouse onClick stays native.
      event.preventDefault();
      if (button.disabled || held === null || event.touches.length !== 0) {
        return;
      }
      const touch = Array.from(event.changedTouches).find(
        (item) => item.identifier === held.id,
      );
      const bounds = button.getBoundingClientRect();
      if (
        touch &&
        Math.hypot(touch.clientX - held.x, touch.clientY - held.y) <= 8 &&
        touch.clientX >= bounds.left &&
        touch.clientX <= bounds.right &&
        touch.clientY >= bounds.top &&
        touch.clientY <= bounds.bottom
      ) {
        latest.current();
      }
    };
    const cancel = (): void => {
      start = null;
    };
    button.addEventListener("touchstart", down, { passive: false });
    button.addEventListener("touchmove", move, { passive: false });
    button.addEventListener("touchend", up, { passive: false });
    button.addEventListener("touchcancel", cancel);
    return () => {
      button.removeEventListener("touchstart", down);
      button.removeEventListener("touchmove", move);
      button.removeEventListener("touchend", up);
      button.removeEventListener("touchcancel", cancel);
    };
  }, []);
}
