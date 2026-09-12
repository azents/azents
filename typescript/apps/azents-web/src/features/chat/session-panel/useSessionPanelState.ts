"use client";

import { useLocalStorage } from "@mantine/hooks";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { parseSessionPanelView, sessionPanelHref } from "./sessionPanel";
import type { SessionPanelView } from "./sessionPanel";
import type { PointerEvent, RefObject } from "react";

export interface SessionPanelState {
  activeView: SessionPanelView;
  opened: boolean;
  onSelect: (view: SessionPanelView) => void;
  onOpen: () => void;
  onClose: () => void;
  containerRef: RefObject<HTMLDivElement | null>;
  chatRatio: number;
  onResizeStart: (event: PointerEvent<HTMLDivElement>) => void;
  onResizeBy: (delta: number) => void;
  initialTaskId: string | null;
  openInitialTaskForEdit: boolean;
}

export function useSessionPanelState(mobile: boolean): SessionPanelState {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const page = params.get("page");
  const selected = parseSessionPanelView(page);
  const [activeView, setActiveView] = useState<SessionPanelView>(
    selected ?? "files",
  );
  const [opened, setOpened] = useState(selected !== null || !mobile);
  const pendingPageRef = useRef<{ value: string | null } | null>(null);
  useEffect(() => {
    const pendingPage = pendingPageRef.current;
    if (pendingPage !== null) {
      if (page === pendingPage.value) {
        pendingPageRef.current = null;
      }
      return;
    }
    if (selected !== null) {
      setActiveView(selected);
      setOpened(true);
      return;
    }
    setOpened(!mobile);
  }, [mobile, page, selected]);
  const containerRef = useRef<HTMLDivElement>(null);
  const [chatRatio, setChatRatio] = useLocalStorage<number>({
    key: "azents.chat.workspaceRatio",
    defaultValue: 0.55,
    deserialize: (value?: string): number => {
      const parsed = Number.parseFloat(value ?? "");
      return Number.isFinite(parsed)
        ? Math.min(0.75, Math.max(0.35, parsed))
        : 0.55;
    },
    serialize: (value: number): string => value.toString(),
  });
  const onSelect = useCallback(
    (view: SessionPanelView): void => {
      setActiveView(view);
      setOpened(true);
      if (page === view) {
        return;
      }
      pendingPageRef.current = { value: view };
      router.replace(sessionPanelHref(pathname, params.toString(), view), {
        scroll: false,
      });
    },
    [page, router, pathname, params],
  );
  const onClose = useCallback((): void => {
    setOpened(false);
    if (page === null) {
      return;
    }
    pendingPageRef.current = { value: null };
    router.replace(sessionPanelHref(pathname, params.toString(), null), {
      scroll: false,
    });
  }, [page, router, pathname, params]);
  const onOpen = useCallback((): void => {
    setOpened(true);
    if (page === activeView) {
      return;
    }
    pendingPageRef.current = { value: activeView };
    router.replace(sessionPanelHref(pathname, params.toString(), activeView), {
      scroll: false,
    });
  }, [activeView, page, params, pathname, router]);
  const onResizeBy = useCallback(
    (delta: number): void => {
      setChatRatio((ratio) => Math.min(0.75, Math.max(0.35, ratio + delta)));
    },
    [setChatRatio],
  );
  const onResizeStart = useCallback(
    (event: PointerEvent<HTMLDivElement>): void => {
      const container = containerRef.current;
      if (!container) {
        return;
      }
      event.preventDefault();
      const target = event.currentTarget;
      target.setPointerCapture(event.pointerId);
      const rect = container.getBoundingClientRect();
      const move = (next: globalThis.PointerEvent): void => {
        setChatRatio(
          Math.min(
            0.75,
            Math.max(0.35, (next.clientX - rect.left) / rect.width),
          ),
        );
      };
      const stop = (): void => {
        target.removeEventListener("pointermove", move);
        target.removeEventListener("lostpointercapture", stop);
      };
      target.addEventListener("pointermove", move);
      target.addEventListener("lostpointercapture", stop);
    },
    [setChatRatio],
  );
  return {
    activeView,
    opened,
    onSelect,
    onOpen,
    onClose,
    containerRef,
    chatRatio,
    onResizeStart,
    onResizeBy,
    initialTaskId: params.get("taskId"),
    openInitialTaskForEdit: params.get("edit") === "1" && params.has("taskId"),
  };
}
