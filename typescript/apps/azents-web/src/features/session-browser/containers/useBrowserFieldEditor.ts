"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useBrowserEditorViewport } from "./useBrowserEditorViewport";
import type {
  BrowserFieldEditorControls,
  BrowserFieldEditorDraft,
} from "../components/BrowserFieldEditor";
import type { BrowserFieldResult, BrowserFrame } from "../types";

interface Options {
  scope: string;
  enabled: boolean;
  frame: BrowserFrame | null;
  label: string;
  open: (frame: BrowserFrame, editableId: string) => boolean;
  finish: (text: string | null) => boolean;
  cancelInput: () => void;
  readClipboard: (() => Promise<string>) | null;
}
type EditorState =
  | { type: "idle"; animate: boolean }
  | { type: "opening"; scope: string }
  | { type: "editing"; scope: string; draft: BrowserFieldEditorDraft }
  | { type: "submitting"; scope: string; draft: BrowserFieldEditorDraft };

export interface BrowserFieldEditorOutput {
  controls: BrowserFieldEditorControls;
  active: boolean;
  result: (result: BrowserFieldResult) => void;
}

/** Field values live only in this transient editor, never in projection or live status. */
export function useBrowserFieldEditor(
  options: Options,
): BrowserFieldEditorOutput {
  const latest = useRef(options);
  const closingScope = useRef(options.scope);
  const [failedScope, setFailedScope] = useState<string | null>(null);
  const [sendFailed, setSendFailed] = useState(false);
  latest.current = options;
  const [state, setState] = useState<EditorState>({
    type: "idle",
    animate: false,
  });
  const current = useRef(state);
  current.current = state;
  const valid =
    options.enabled && (state.type === "idle" || state.scope === options.scope);
  const draft =
    valid && (state.type === "editing" || state.type === "submitting")
      ? state.draft
      : null;
  const viewport = useBrowserEditorViewport(options.enabled || draft !== null);
  const clear = useCallback((): void => {
    latest.current.finish(null);
    current.current = { type: "idle", animate: false };
    setState(current.current);
  }, []);
  useEffect(() => {
    if (!valid) {
      clear();
    }
  }, [valid, clear]);
  useEffect(() => {
    const hidden = (): void => {
      if (document.hidden) {
        clear();
      }
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", clear);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", clear);
    };
  }, [clear]);
  const result = useCallback((result: BrowserFieldResult): void => {
    const value = current.current;
    const options = latest.current;
    if (
      result.type === "opened" &&
      value.type === "opening" &&
      value.scope === options.scope &&
      options.enabled
    ) {
      const editing: EditorState = {
        type: "editing",
        scope: value.scope,
        draft: {
          label: options.label,
          kind: result.field.kind,
          attributes: result.field.attributes,
          value: result.field.value,
        },
      };
      current.current = editing;
      setState(editing);
    } else {
      if (result.type === "opened") {
        options.finish(null);
      }
      if (result.type === "failed" && result.reason !== null) {
        setFailedScope(options.scope);
      }
      current.current = { type: "idle", animate: result.type === "completed" };
      setState(current.current);
    }
  }, []);
  return {
    active: valid && state.type !== "idle",
    result,
    controls: {
      enabled: options.enabled && state.type === "idle",
      pending: state.type === "submitting",
      failed: options.enabled && failedScope === options.scope,
      sendFailed,
      draft,
      retainClosingDraft:
        valid &&
        closingScope.current === options.scope &&
        (state.type === "submitting" ||
          (state.type === "idle" && state.animate)),
      viewport,
      toolbarVisible: false,
      toolbarAppearance: "floating",
      onOpen: () => {
        setFailedScope(null);
        setSendFailed(false);
        closingScope.current = options.scope;
        const receiver = document.activeElement;
        const id =
          receiver instanceof HTMLTextAreaElement
            ? receiver.getAttribute("data-browser-native-input")
            : null;
        if (
          !options.enabled ||
          state.type !== "idle" ||
          options.frame === null ||
          id === null
        ) {
          return;
        }
        options.cancelInput();
        const opening: EditorState = { type: "opening", scope: options.scope };
        current.current = opening;
        setState(opening);
        if (!options.open(options.frame, id)) {
          clear();
        }
      },
      onChange: (value) => {
        setSendFailed(false);
        if (current.current.type === "editing" && [...value].length <= 32768) {
          current.current = {
            ...current.current,
            draft: { ...current.current.draft, value },
          };
          setState(current.current);
        }
      },
      onConfirm: () => {
        const value = current.current;
        if (valid && value.type === "editing") {
          if (!options.finish(value.draft.value)) {
            setSendFailed(true);
            return;
          }
          current.current = {
            type: "submitting",
            scope: options.scope,
            draft: value.draft,
          };
          setState(current.current);
        }
      },
      onCancel: () => {
        if (current.current.type === "submitting") {
          return;
        }
        options.finish(null);
        current.current = { type: "idle", animate: true };
        setState(current.current);
      },
      onPaste: (insertNative) => {
        const before = current.current;
        const readClipboard = latest.current.readClipboard;
        if (before.type !== "editing" || readClipboard === null) {
          return;
        }
        // Clipboard admission must happen synchronously in the trusted activation.
        const read = readClipboard();
        void read.then(
          (text) => {
            if (
              current.current !== before ||
              !latest.current.enabled ||
              latest.current.scope !== before.scope ||
              !text
            ) {
              return;
            }
            if ([...text].length > 32768) {
              return;
            }
            const nativeValue = insertNative(text);
            if (nativeValue === null) {
              return;
            }
            current.current = {
              ...before,
              draft: { ...before.draft, value: nativeValue },
            };
            setState(current.current);
          },
          () => {
            /* Native paste remains available when permission is denied. */
          },
        );
      },
      onDirectPaste: () => {},
    },
  };
}
