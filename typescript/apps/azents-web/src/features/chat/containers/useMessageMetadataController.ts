"use client";

import { useMediaQuery } from "@mantine/hooks";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface MessageMetadataVisibility {
  activeOverlay: "model" | "timestamp" | null;
  isTouchPrimary: boolean;
  visible: boolean;
  setActiveOverlay: (overlay: "model" | "timestamp" | null) => void;
  showForTouch: () => void;
}
export const MessageMetadataVisibilityContext =
  createContext<MessageMetadataVisibility | null>(null);

export interface MessageTimestampOutput {
  createdAt: string;
  isTouchPrimary: boolean;
  opened: boolean;
  handlePointerDown: (event: React.PointerEvent<HTMLElement>) => void;
}
export function useMessageTimestampController({
  createdAt,
}: {
  createdAt: string;
}): MessageTimestampOutput {
  const visibility = useContext(MessageMetadataVisibilityContext);
  const isTouchPrimary = visibility?.isTouchPrimary ?? false;
  const [relativeTimeTick, setRelativeTimeTick] = useState(0);
  useEffect(() => {
    const created = new Date(createdAt).getTime();
    const diff = Math.max(0, Date.now() - created);
    const delay = !Number.isFinite(created)
      ? 60_000
      : diff < 60_000
        ? 60_000 - diff
        : 60_000 - (diff % 60_000);
    const timer = setTimeout(
      () => setRelativeTimeTick((current) => current + 1),
      delay,
    );
    return () => clearTimeout(timer);
  }, [createdAt, relativeTimeTick]);
  function handlePointerDown(event: React.PointerEvent<HTMLElement>): void {
    if (!isTouchPrimary || visibility === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    visibility.showForTouch();
    visibility.setActiveOverlay(
      visibility.activeOverlay === "timestamp" ? null : "timestamp",
    );
  }
  return {
    createdAt,
    isTouchPrimary,
    opened: visibility?.activeOverlay === "timestamp" && visibility.visible,
    handlePointerDown,
  };
}

export interface ModelMetadataOutput {
  opened: boolean;
  setOpened: (opened: boolean) => void;
}
export function useModelMetadataController(): ModelMetadataOutput {
  const visibility = useContext(MessageMetadataVisibilityContext);
  const [desktopOpened, setDesktopOpened] = useState(false);
  const isTouchPrimary = visibility?.isTouchPrimary ?? false;
  const opened = isTouchPrimary
    ? visibility?.activeOverlay === "model"
    : desktopOpened;
  function setOpened(nextOpened: boolean): void {
    if (isTouchPrimary && visibility !== null) {
      visibility.setActiveOverlay(nextOpened ? "model" : null);
      return;
    }
    setDesktopOpened(nextOpened);
  }
  return { opened, setOpened };
}

export interface MessageMetadataSurfaceOutput {
  children: React.ReactNode;
  value: MessageMetadataVisibility;
  visible: boolean;
  showForTouch: () => void;
}
export function useMessageMetadataSurfaceController({
  children,
}: {
  children: React.ReactNode;
}): MessageMetadataSurfaceOutput {
  const isTouchPrimary = useMediaQuery("(hover: none)");
  const [activeOverlay, setActiveOverlay] = useState<
    "model" | "timestamp" | null
  >(null);
  const [visible, setVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
      }
    },
    [],
  );
  useEffect(() => {
    if (!isTouchPrimary || activeOverlay === null) {
      return;
    }
    function dismissOverlay(event: PointerEvent): void {
      if (
        event.target instanceof Element &&
        event.target.closest(
          `[data-message-metadata-trigger="${activeOverlay}"], [data-message-metadata-popover]`,
        )
      ) {
        return;
      }
      setActiveOverlay(null);
    }
    document.addEventListener("pointerdown", dismissOverlay, true);
    return () =>
      document.removeEventListener("pointerdown", dismissOverlay, true);
  }, [activeOverlay, isTouchPrimary]);
  const showForTouch = useCallback((): void => {
    if (!isTouchPrimary) {
      return;
    }
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
    }
    setVisible(true);
    hideTimerRef.current = setTimeout(() => {
      setActiveOverlay(null);
      setVisible(false);
      hideTimerRef.current = null;
    }, 5000);
  }, [isTouchPrimary]);
  const value = useMemo(
    () => ({
      activeOverlay,
      isTouchPrimary,
      visible,
      setActiveOverlay,
      showForTouch,
    }),
    [activeOverlay, isTouchPrimary, showForTouch, visible],
  );
  return { children, value, visible, showForTouch };
}
