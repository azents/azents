"use client";

import { useRef } from "react";
import type {
  FocusEventHandler,
  MouseEventHandler,
  PointerEventHandler,
} from "react";

export interface BrowserAddressSelection {
  onFocus: FocusEventHandler<HTMLInputElement>;
  onPointerDown: PointerEventHandler<HTMLInputElement>;
  onClick: MouseEventHandler<HTMLInputElement>;
  onBlur: FocusEventHandler<HTMLInputElement>;
}

/** Select on entry, not every click: later native caret/selection edits remain usable. */
export function useBrowserAddressSelection(): BrowserAddressSelection {
  const entering = useRef(false);
  return {
    onPointerDown: (event) => {
      entering.current =
        event.currentTarget.ownerDocument.activeElement !== event.currentTarget;
    },
    onFocus: (event) => {
      entering.current = true;
      event.currentTarget.select();
    },
    onClick: (event) => {
      if (entering.current) {
        // Native pointer placement can collapse the selection after focus.
        entering.current = false;
        event.currentTarget.select();
      }
    },
    onBlur: () => {
      entering.current = false;
    },
  };
}
