"use client";

import { useWindowEvent } from "@mantine/hooks";
import { useCallback, useEffect, useRef } from "react";
import {
  browserKey,
  browserPoint,
  browserPointerButton,
  browserReleaseFrame,
  browserRemoteModifiers,
  browserTextareaModifier,
  browserTextareaTextKey,
} from "../input";
import { useBrowserPaste } from "./useBrowserPaste";
import type { BrowserInteractionHandlers } from "../components/SessionBrowserPanel";
import type { BrowserCoordinateAction, BrowserFrame } from "../types";
import type { BrowserPasteControls } from "./useBrowserPaste";
import type { RefObject } from "react";

export interface BrowserInteractionOptions {
  enabled: boolean;
  frame: BrowserFrame | null;
  onAction: (frame: BrowserFrame, action: BrowserCoordinateAction) => boolean;
  readClipboard: (() => Promise<string>) | null;
}

export interface BrowserInteractionOutput {
  keyboardRef: RefObject<HTMLTextAreaElement | null>;
  interaction: BrowserInteractionHandlers | null;
  cancel: () => void;
  paste: BrowserPasteControls;
}

/** Track actual DOM interactions only; this hook does not open a connection or replay input. */
export function useBrowserInteraction({
  enabled,
  frame,
  onAction,
  readClipboard,
}: BrowserInteractionOptions): BrowserInteractionOutput {
  const keyboardRef = useRef<HTMLTextAreaElement>(null);
  const latest = useRef({ enabled, frame, onAction });
  latest.current = { enabled, frame, onAction };
  const pointer = useRef<{
    id: number;
    x: number;
    y: number;
    frame: BrowserFrame;
    receiver: HTMLTextAreaElement | null;
  } | null>(null);
  const composing = useRef<BrowserFrame | null>(null);
  const suppressInput = useRef<string | null>(null);
  const pressed = useRef(new Map<string, BrowserFrame>());

  const send = useCallback((action: BrowserCoordinateAction): boolean => {
    const current = latest.current;
    return (
      current.enabled &&
      current.frame !== null &&
      current.onAction(current.frame, action)
    );
  }, []);

  const releaseKeys = useCallback((): boolean => {
    const current = latest.current;
    let released = true;
    for (const [key, original] of pressed.current) {
      const source = browserReleaseFrame(original, current.frame);
      if (current.onAction(source, { kind: "key", phase: "up", key })) {
        pressed.current.delete(key);
      } else {
        released = false;
      }
    }
    return released;
  }, []);

  const cancel = useCallback((): void => {
    const current = latest.current;
    const heldPointer = pointer.current;
    pointer.current = null;
    if (heldPointer !== null) {
      current.onAction(heldPointer.frame, {
        kind: "pointer",
        phase: "cancel",
        x: heldPointer.x,
        y: heldPointer.y,
        button: null,
      });
    }
    const compositionFrame = composing.current;
    composing.current = null;
    suppressInput.current = null;
    if (compositionFrame !== null) {
      current.onAction(compositionFrame, {
        kind: "composition",
        phase: "cancel",
        text: null,
      });
    }
    releaseKeys();
    pressed.current.clear();
    if (keyboardRef.current !== null) {
      keyboardRef.current.value = "";
    }
  }, [releaseKeys]);

  const paste = useBrowserPaste({
    enabled,
    frame,
    onAction,
    readClipboard,
    cancelInput: cancel,
  });

  const attachment = frame?.attachment_id;
  const navigation = frame?.navigation_id;
  useWindowEvent("blur", cancel);
  useWindowEvent("pagehide", cancel);
  useWindowEvent(
    "pointerdown",
    (event: globalThis.PointerEvent): void => {
      if (composing.current !== null && event.target !== keyboardRef.current) {
        cancel();
      }
    },
    true,
  );
  useEffect(() => {
    if (!enabled) {
      cancel();
    }
    const visibility = (): void => {
      if (document.hidden) {
        cancel();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      cancel();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [enabled, attachment, navigation, cancel]);

  const softwareKey = useCallback(
    (key: string): boolean => {
      const source = latest.current.frame;
      if (source === null || !send({ kind: "key", phase: "down", key })) {
        return false;
      }
      pressed.current.set(key, source);
      if (!send({ kind: "key", phase: "up", key })) {
        return false;
      }
      pressed.current.delete(key);
      return true;
    },
    [send],
  );
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const beforeInput = (event: InputEvent): void => {
      const field = keyboardRef.current;
      if (
        field === null ||
        event.target !== field ||
        document.activeElement !== field ||
        event.isComposing ||
        composing.current !== null
      ) {
        return;
      }
      const key =
        event.inputType === "deleteContentBackward"
          ? "Backspace"
          : event.inputType === "deleteContentForward"
            ? "Delete"
            : ["insertLineBreak", "insertParagraph"].includes(event.inputType)
              ? "Enter"
              : null;
      if (key !== null && (pressed.current.has(key) || softwareKey(key))) {
        event.preventDefault();
      }
    };
    // Portal mounting can follow this effect; bind by the current receiver at event time.
    document.addEventListener("beforeinput", beforeInput, true);
    return () => document.removeEventListener("beforeinput", beforeInput, true);
  }, [enabled, softwareKey]);

  const interaction: BrowserInteractionHandlers = {
    onKeyboardFocus: (event) => {
      keyboardRef.current = event.currentTarget;
      paste.onFocus(event);
    },
    onPaste: paste.onPaste,
    onKeyboardPointerDown: paste.onPointerDown,
    onSendTab: (reverse) => {
      const source = latest.current.frame;
      if (source === null) {
        return;
      }
      if (reverse) {
        if (!send({ kind: "key", phase: "down", key: "Shift" })) {
          return;
        }
        pressed.current.set("Shift", source);
      }
      softwareKey("Tab");
      if (reverse && send({ kind: "key", phase: "up", key: "Shift" })) {
        pressed.current.delete("Shift");
      }
    },
    onContextMenu: (event) => {
      if (!(
        event.target instanceof HTMLTextAreaElement &&
        event.target.hasAttribute("data-browser-native-input") &&
        !event.target.readOnly
      )) {
        event.preventDefault();
      }
    },
    onPointerDown: (event) => {
      const source = latest.current.frame;
      if (source === null || pointer.current !== null) {
        return;
      }
      const point = browserPoint(
        event.clientX,
        event.clientY,
        event.currentTarget.getBoundingClientRect(),
        source,
      );
      const button = browserPointerButton(event.button);
      if (point === null || button === null) {
        return;
      }
      for (const modifier of browserRemoteModifiers({
        control: event.ctrlKey,
        meta: event.metaKey,
        alt: event.altKey,
        shift: event.shiftKey,
        altGraph: false,
      })) {
        if (!pressed.current.has(modifier)) {
          if (!send({ kind: "key", phase: "down", key: modifier })) {
            releaseKeys();
            return;
          }
          pressed.current.set(modifier, source);
        }
      }
      if (!send({ kind: "pointer", phase: "down", ...point, button })) {
        releaseKeys();
        return;
      }
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      pointer.current = {
        id: event.pointerId,
        ...point,
        frame: source,
        receiver:
          event.target instanceof HTMLTextAreaElement &&
          event.target.hasAttribute("data-browser-native-input")
            ? event.target
            : null,
      };
    },
    onPointerMove: (event) => {
      const source = latest.current.frame;
      if (
        source === null ||
        (pointer.current !== null && pointer.current.id !== event.pointerId)
      ) {
        return;
      }
      const point = browserPoint(
        event.clientX,
        event.clientY,
        event.currentTarget.getBoundingClientRect(),
        source,
      );
      if (point === null) {
        return;
      }
      if (pointer.current !== null) {
        pointer.current = { ...pointer.current, ...point };
      }
      send({ kind: "pointer", phase: "move", ...point, button: null });
    },
    onPointerUp: (event) => {
      const held = pointer.current;
      if (held === null || held.id !== event.pointerId) {
        return;
      }
      const source = latest.current.frame;
      const point =
        source === null
          ? null
          : browserPoint(
              event.clientX,
              event.clientY,
              event.currentTarget.getBoundingClientRect(),
              source,
            );
      const button = browserPointerButton(event.button);
      pointer.current = null;
      if (point === null || button === null) {
        latest.current.onAction(held.frame, {
          kind: "pointer",
          phase: "cancel",
          x: held.x,
          y: held.y,
          button: null,
        });
      } else {
        if (send({ kind: "pointer", phase: "up", ...point, button })) {
          if (held.receiver !== null) {
            keyboardRef.current = held.receiver;
          }
          if (
            held.receiver !== null &&
            document.activeElement !== held.receiver
          ) {
            held.receiver.focus({ preventScroll: true });
          } else if (held.receiver === null) {
            event.currentTarget
              .querySelector<HTMLTextAreaElement>(
                "textarea:not([data-browser-native-input])",
              )
              ?.focus({ preventScroll: true });
          }
        } else {
          latest.current.onAction(held.frame, {
            kind: "pointer",
            phase: "cancel",
            x: held.x,
            y: held.y,
            button: null,
          });
        }
      }
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      releaseKeys();
    },
    onPointerCancel: cancel,
    onLostPointerCapture: () => {
      if (pointer.current !== null) {
        cancel();
      }
    },
    onWheel: (event) => {
      const source = latest.current.frame;
      if (source === null) {
        return;
      }
      const point = browserPoint(
        event.clientX,
        event.clientY,
        event.currentTarget.getBoundingClientRect(),
        source,
      );
      if (
        point === null ||
        !Number.isFinite(event.deltaX) ||
        !Number.isFinite(event.deltaY)
      ) {
        return;
      }
      const multiplier =
        event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? source.height : 1;
      if (
        send({
          kind: "wheel",
          ...point,
          delta_x: Math.max(
            -100000,
            Math.min(100000, event.deltaX * multiplier),
          ),
          delta_y: Math.max(
            -100000,
            Math.min(100000, event.deltaY * multiplier),
          ),
        })
      ) {
        event.preventDefault();
      }
    },
    onKeyDown: (event) => {
      if (event.key === "Tab") {
        cancel();
        return;
      }
      if (
        event.nativeEvent.isComposing ||
        composing.current !== null ||
        event.key === "Process" ||
        event.key === "Dead" ||
        event.key === "Unidentified"
      ) {
        return;
      }
      suppressInput.current = null;
      const textarea = event.currentTarget instanceof HTMLTextAreaElement;
      if (
        textarea &&
        (((event.ctrlKey || event.metaKey) &&
          !event.altKey &&
          event.key.toLowerCase() === "v") ||
          (event.shiftKey && event.key === "Insert"))
      ) {
        // Let the local OS deliver its authorized paste event, not a remote chord.
        releaseKeys();
        return;
      }
      const modifiers = {
        control: event.ctrlKey,
        meta: event.metaKey,
        alt: event.altKey,
        shift: event.shiftKey,
        altGraph: event.getModifierState("AltGraph"),
      };
      if (textarea) {
        // Native text applies local modifiers; SDK modifiers belong only to concrete key chords.
        if (browserTextareaModifier(event.key)) {
          return;
        }
        if (browserTextareaTextKey(event.key, modifiers)) {
          if (!releaseKeys()) {
            event.preventDefault();
          }
          return;
        }
      }
      if (event.repeat) {
        event.preventDefault();
        return;
      }
      const key = browserKey(event.key);
      const source = latest.current.frame;
      if (textarea && key !== null && source !== null) {
        for (const modifier of browserRemoteModifiers(modifiers)) {
          if (pressed.current.has(modifier)) {
            continue;
          }
          if (!send({ kind: "key", phase: "down", key: modifier })) {
            event.preventDefault();
            return;
          }
          pressed.current.set(modifier, source);
        }
      }
      if (
        key !== null &&
        source !== null &&
        send({ kind: "key", phase: "down", key })
      ) {
        pressed.current.set(key, source);
        event.preventDefault();
      }
    },
    onKeyUp: (event) => {
      const key = browserKey(event.key);
      if (key === null || !pressed.current.has(key)) {
        return;
      }
      const original = pressed.current.get(key) ?? null;
      if (
        original !== null &&
        latest.current.onAction(original, { kind: "key", phase: "up", key })
      ) {
        event.preventDefault();
      }
      pressed.current.delete(key);
    },
    onBlur: (event) => {
      if (
        event.relatedTarget instanceof Node &&
        event.currentTarget.contains(event.relatedTarget)
      ) {
        return;
      }
      cancel();
    },
    onCompositionStart: (event) => {
      if (document.activeElement !== event.currentTarget) {
        return;
      }
      if (!releaseKeys()) {
        return;
      }
      const source = latest.current.frame;
      if (
        source !== null &&
        send({ kind: "composition", phase: "start", text: null })
      ) {
        composing.current = source;
      }
    },
    onCompositionEnd: (event) => {
      if (
        composing.current === null ||
        document.activeElement !== event.currentTarget
      ) {
        event.currentTarget.value = "";
        return;
      }
      const original = composing.current;
      composing.current = null;
      const text = event.data;
      suppressInput.current = text;
      if (!send({ kind: "composition", phase: "commit", text })) {
        latest.current.onAction(original, {
          kind: "composition",
          phase: "cancel",
          text: null,
        });
      }
      event.currentTarget.value = "";
    },
    onKeyboardInput: (event) => {
      if (document.activeElement !== event.currentTarget) {
        event.currentTarget.value = "";
        return;
      }
      if (
        composing.current !== null ||
        (event.nativeEvent instanceof InputEvent &&
          event.nativeEvent.isComposing)
      ) {
        return;
      }
      const text = event.currentTarget.value;
      event.currentTarget.value = "";
      if (suppressInput.current !== null) {
        const duplicate =
          text === suppressInput.current ||
          (event.nativeEvent instanceof InputEvent &&
            event.nativeEvent.data === suppressInput.current);
        suppressInput.current = null;
        if (duplicate) {
          return;
        }
      }
      if (!text) {
        return;
      }
      if (!releaseKeys()) {
        return;
      }
      if (send({ kind: "composition", phase: "start", text: null })) {
        send({ kind: "composition", phase: "commit", text });
      }
    },
  };
  return {
    keyboardRef,
    interaction: enabled ? interaction : null,
    cancel,
    paste: paste.controls,
  };
}
