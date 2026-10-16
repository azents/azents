import { useReducedMotion } from "@mantine/hooks";
import { useLayoutEffect, useRef, useState } from "react";
import type { BrowserFieldEditorDraft } from "../components/BrowserFieldEditor";

export interface BrowserFieldEditorTransition {
  draft: BrowserFieldEditorDraft | null;
  duration: number;
  exitDuration: number;
  onExited: () => void;
}

/** Retain only the closing visual content until the native transition finishes. */
export function useBrowserFieldEditorTransition(
  draft: BrowserFieldEditorDraft | null,
  retainClosingDraft: boolean = true,
): BrowserFieldEditorTransition {
  const reducedMotion = useReducedMotion();
  const latest = useRef(draft);
  latest.current = draft;
  const [closingDraft, setClosingDraft] =
    useState<BrowserFieldEditorDraft | null>(draft);
  useLayoutEffect(() => {
    if (draft !== null) {
      setClosingDraft(draft);
    } else if (!retainClosingDraft) {
      setClosingDraft(null);
    }
  }, [draft, retainClosingDraft]);
  return {
    draft: draft ?? (retainClosingDraft ? closingDraft : null),
    duration: reducedMotion ? 0 : 160,
    exitDuration: reducedMotion ? 0 : 120,
    onExited: () => {
      if (latest.current === null) {
        setClosingDraft(null);
      }
    },
  };
}
