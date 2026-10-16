"use client";
import { useBrowserToolbarTouch } from "./useBrowserToolbarTouch";
import type { BrowserKeyboardToolbarProps } from "../components/BrowserKeyboardToolbar";
import type { RefCallback } from "react";
export function useBrowserKeyboardToolbar(
  props: BrowserKeyboardToolbarProps,
): BrowserKeyboardToolbarProps & {
  pasteRef: RefCallback<HTMLButtonElement>;
  openRef: RefCallback<HTMLButtonElement>;
} {
  const pasteRef = useBrowserToolbarTouch(props.onPaste);
  const openRef = useBrowserToolbarTouch(props.onOpen);
  return { ...props, pasteRef, openRef };
}
