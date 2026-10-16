"use client";

import { useLocalStorage } from "@mantine/hooks";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  availableSessionPanelView,
  parseSessionPanelView,
  sessionPanelHref,
} from "./sessionPanel";
import type { SessionPanelView } from "./sessionPanel";
import type { PointerEvent, RefObject } from "react";

export interface SessionPanelState {
  activeView: SessionPanelView;
  activationRevision: number;
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

export function useSessionPanelState({
  mobile,
  browserEnabled,
}: {
  mobile: boolean;
  browserEnabled: boolean;
}): SessionPanelState {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const page = params.get("page");
  const selected = availableSessionPanelView(
    parseSessionPanelView(page),
    browserEnabled,
  );
  const [activeView, setActiveView] = useState<SessionPanelView>(
    selected ?? "files",
  );
  const [activationRevision, setActivationRevision] = useState(0);
  const [opened, setOpened] = useState(selected !== null || !mobile);
  const pendingPageRef = useRef<{ value: string | null } | null>(null);
  const availableActiveView =
    availableSessionPanelView(activeView, browserEnabled) ?? "files";
  useEffect(() => {
    if (!browserEnabled && activeView === "browser") {
      setActiveView("files");
      pendingPageRef.current = null;
    }
  }, [browserEnabled, activeView]);
  useEffect(() => {
    if (!browserEnabled && page === "browser") {
      setActiveView("files");
      setOpened(true);
      pendingPageRef.current = { value: "files" };
      router.replace(sessionPanelHref(pathname, params.toString(), "files"), {
        scroll: false,
      });
      return;
    }
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
  }, [mobile, page, selected, browserEnabled, router, pathname, params]);
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
      const nextView =
        availableSessionPanelView(view, browserEnabled) ?? "files";
      setActiveView(nextView);
      setActivationRevision((revision) => revision + 1);
      setOpened(true);
      if (page === nextView) {
        return;
      }
      pendingPageRef.current = { value: nextView };
      router.replace(sessionPanelHref(pathname, params.toString(), nextView), {
        scroll: false,
      });
    },
    [page, router, pathname, params, browserEnabled],
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
    setActivationRevision((revision) => revision + 1);
    if (page === availableActiveView) {
      return;
    }
    pendingPageRef.current = { value: availableActiveView };
    router.replace(
      sessionPanelHref(pathname, params.toString(), availableActiveView),
      {
        scroll: false,
      },
    );
  }, [availableActiveView, page, params, pathname, router]);
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
    activeView: availableActiveView,
    activationRevision,
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
