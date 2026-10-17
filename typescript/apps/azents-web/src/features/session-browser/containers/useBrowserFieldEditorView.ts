"use client";
import { useRef } from "react";
import { useBrowserFieldEditorTransition } from "./useBrowserFieldEditorTransition";
import { useBrowserToolbarTouch } from "./useBrowserToolbarTouch";
import type { BrowserFieldEditorControls } from "../components/BrowserFieldEditor";
import type { RefCallback, RefObject } from "react";
export interface BrowserFieldEditorViewProps {
  controls: BrowserFieldEditorControls;
  motion: ReturnType<typeof useBrowserFieldEditorTransition>;
  textRef: RefObject<HTMLInputElement | null>;
  multilineRef: RefObject<HTMLTextAreaElement | null>;
  cancelRef: RefCallback<HTMLButtonElement>;
  confirmRef: RefCallback<HTMLButtonElement>;
  pasteRef: RefCallback<HTMLButtonElement>;
  activatePaste: () => void;
}
export function useBrowserFieldEditorView({
  controls,
}: {
  controls: BrowserFieldEditorControls;
}): BrowserFieldEditorViewProps {
  const motion = useBrowserFieldEditorTransition(
    controls.draft,
    controls.retainClosingDraft,
  );
  const draft = motion.draft;
  const textRef = useRef<HTMLInputElement>(null);
  const multilineRef = useRef<HTMLTextAreaElement>(null);
  const activatePaste = (): void => {
    if (draft === null) {
      return;
    }
    const input =
      draft.kind === "multiline" ? multilineRef.current : textRef.current;
    if (input === null) {
      return;
    }
    controls.onPaste((text) => {
      if (
        !input.isConnected ||
        document.activeElement !== input ||
        typeof document.execCommand !== "function"
      ) {
        return null;
      }
      // Native insertion retains email selection where selectionStart is unavailable.
      return document.execCommand("insertText", false, text)
        ? input.value
        : null;
    });
  };
  const cancelRef = useBrowserToolbarTouch(controls.onCancel);
  const confirmRef = useBrowserToolbarTouch(controls.onConfirm);
  const pasteRef = useBrowserToolbarTouch(activatePaste);
  return {
    controls,
    motion,
    textRef,
    multilineRef,
    cancelRef,
    confirmRef,
    pasteRef,
    activatePaste,
  };
}
