"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  browserAddress,
  browserFrameMatchesStatus,
  sameBrowserTarget,
} from "../input";
import { browserProjectionState } from "../projection";
import { recentBrowserTargets } from "../recentTargets";
import { browserPanelHref, parseBrowserTarget } from "../route";
import {
  browserAccessError,
  useBrowserConnection,
} from "./useBrowserConnection";
import { useBrowserInteraction } from "./useBrowserInteraction";
import { useBrowserTouchView } from "./useBrowserTouchView";
import type { SessionBrowserPanelProps } from "../components/SessionBrowserPanel";
import type {
  BrowserNavigationAction,
  BrowserPageChoice,
  BrowserTarget,
  BrowserViewState,
} from "../types";
import type { BrowserProjectionResponse } from "@azents/public-client";

export interface SessionBrowserContainerProps {
  handle: string;
  agentId: string;
  sessionId: string;
}

function pages(projection: BrowserProjectionResponse): BrowserPageChoice[] {
  return projection.tasks.flatMap((task) =>
    task.pages.map((page) => ({
      target: {
        task_id: page.task_id,
        page_id: page.id,
        resource_incarnation: page.resource_incarnation,
      },
      taskLabel: task.label,
      title: page.title,
      url: page.url,
    })),
  );
}

/** Select current tabs by preference, then independently admit every exact live attachment. */
export function useSessionBrowserContainer(
  resource: SessionBrowserContainerProps,
): SessionBrowserPanelProps {
  const t = useTranslations("chat.browser");
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const utils = trpc.useUtils();
  const { handle, agentId, sessionId } = resource;
  const resourceKey = JSON.stringify([handle, agentId, sessionId]);
  const [deniedResource, setDeniedResource] = useState<string | null>(null);
  const denied = deniedResource === resourceKey;
  const selectedRef = useRef<BrowserTarget | null>(null);
  const [unavailable, setUnavailable] = useState<{
    key: string;
    targets: BrowserTarget[];
  } | null>(null);
  const query = trpc.browser.projection.useQuery(resource, {
    retry: false,
    refetchInterval: 5000,
    enabled: !denied,
  });
  const history = trpc.chat.listSessionEvents.useQuery(
    { sessionId, limit: 100 },
    {
      enabled: !denied && query.data?.available === true,
      retry: false,
      staleTime: 5000,
    },
  );
  const { mutateAsync: connectionInfo } =
    trpc.browser.connectionInfo.useMutation({ retry: false });
  const connect = useCallback(
    () => connectionInfo({ handle, agentId, sessionId }),
    [connectionInfo, handle, agentId, sessionId],
  );
  const rejected = useCallback(
    (kind: "access" | "target"): void => {
      if (kind === "access") {
        setDeniedResource(resourceKey);
      } else {
        const target = selectedRef.current;
        if (target !== null) {
          setUnavailable((current) => ({
            key: resourceKey,
            targets: [
              ...(current?.key === resourceKey ? current.targets : []),
              target,
            ].slice(-512),
          }));
        }
      }
      void utils.browser.projection.reset({ handle, agentId, sessionId });
    },
    [resourceKey, handle, agentId, sessionId, utils.browser.projection],
  );
  const close = trpc.browser.closePage.useMutation({
    retry: false,
    onSuccess: async (projection) => {
      utils.browser.projection.setData(resource, projection);
      await utils.browser.projection.invalidate(resource);
    },
    onError: (error) => {
      if (browserAccessError(error)) {
        rejected("access");
      } else {
        void utils.browser.projection.invalidate(resource);
      }
    },
  });
  const create = trpc.browser.createPage.useMutation({
    retry: false,
    onSuccess: async (created) => {
      utils.browser.projection.setData(resource, created.projection);
      router.replace(
        browserPanelHref(pathname, search.toString(), {
          task_id: created.page.task_id,
          page_id: created.page.id,
          resource_incarnation: created.page.resource_incarnation,
        }),
        { scroll: false },
      );
      await utils.browser.projection.invalidate(resource);
    },
    onError: (error) => {
      if (browserAccessError(error)) {
        rejected("access");
      } else {
        void utils.browser.projection.invalidate(resource);
      }
    },
  });
  useEffect(() => {
    if (!denied && query.isError && browserAccessError(query.error)) {
      rejected("access");
    }
  }, [denied, query.isError, query.error, rejected]);

  let state: BrowserViewState;
  if (denied) {
    state = { type: "ACCESS_CHANGED" };
  } else if (query.isLoading) {
    state = { type: "LOADING" };
  } else if (query.isError || !query.data) {
    state = { type: "ERROR" };
  } else if (!query.data.available) {
    state = {
      type: "UNAVAILABLE",
      reason: t(
        query.data.reason_code === "browser_disabled"
          ? "browserDisabled"
          : query.data.reason_code === "runtime_unavailable"
            ? "runtimeUnavailable"
            : query.data.reason_code === "working_folder_unavailable"
              ? "workingFolderUnavailable"
              : "capabilityUnavailable",
      ),
    };
  } else {
    const candidates = pages(query.data).filter(
      (page) =>
        unavailable?.key !== resourceKey ||
        !unavailable.targets.some((target) =>
          sameBrowserTarget(page.target, target),
        ),
    );
    const linked = parseBrowserTarget(search.toString());
    const explicit =
      linked.type === "TARGET" &&
      candidates.some((page) => sameBrowserTarget(page.target, linked.target));
    state =
      !explicit && candidates.length > 0 && history.isLoading
        ? { type: "LOADING" }
        : browserProjectionState(
            candidates,
            linked,
            query.data.allow_input,
            recentBrowserTargets([
              ...(history.data?.history.items ?? []),
              ...(history.data?.live.partial_history.items ?? []),
            ]),
          );
  }
  selectedRef.current = state.type === "READY" ? state.selected.target : null;
  const selectedTarget = selectedRef.current;
  useEffect(() => {
    if (selectedTarget === null) {
      return;
    }
    const linked = parseBrowserTarget(search.toString());
    if (
      linked.type !== "TARGET" ||
      !sameBrowserTarget(linked.target, selectedTarget)
    ) {
      router.replace(
        browserPanelHref(pathname, search.toString(), selectedTarget),
        { scroll: false },
      );
    }
  }, [selectedTarget, pathname, router, search]);

  const cancel = useRef<() => void>(() => {});
  const live = useBrowserConnection({
    resourceKey: `${resourceKey}\u0000${query.data?.allow_input === true ? "direct" : "observe"}`,
    target: selectedTarget,
    connect,
    rejected,
    cancelInteraction: () => cancel.current(),
  });
  const [dialogText, setDialogText] = useState("");
  const [focused, setFocused] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [focusViewport, setFocusViewport] = useState<{
    top: number;
    height: number;
  } | null>(null);
  useEffect(() => {
    if (!["READY", "EMPTY", "LOADING"].includes(state.type)) {
      setFocused(false);
    }
  }, [state.type]);
  const [addressDraft, setAddressDraft] = useState<string | null>(null);
  const [addressError, setAddressError] = useState(false);
  const source = live.state.displayed;
  const status = live.state.status;
  const dialogId = status?.dialog?.id;
  useEffect(() => {
    setDialogText("");
  }, [resourceKey, dialogId]);
  const selectedAddress = state.type === "READY" ? state.selected.url : "";
  const selectedPage =
    state.type === "READY" ? state.selected.target.page_id : null;
  useEffect(() => {
    setAddressDraft(null);
    setAddressError(false);
  }, [resourceKey, selectedPage]);
  const mutationPending = close.isPending || create.isPending;
  const interaction = useBrowserInteraction({
    enabled:
      focused &&
      state.type === "READY" &&
      !mutationPending &&
      query.data?.allow_input === true &&
      live.state.connection === "connected" &&
      status !== null &&
      status.allow_input &&
      status.dialog === null &&
      source !== null &&
      browserFrameMatchesStatus(source, status),
    frame: source,
    onAction: (frame, action) =>
      query.data?.allow_input === true && live.coordinate(frame, action),
  });
  const touchView = useBrowserTouchView({
    enabled:
      focused &&
      !mutationPending &&
      source !== null &&
      status !== null &&
      browserFrameMatchesStatus(source, status) &&
      live.state.connection === "connected" &&
      status.dialog === null,
    canInput: interaction.interaction !== null,
    frame: source,
    zoom,
    onZoomChange: setZoom,
    onAction: (frame, action) =>
      query.data?.allow_input === true && live.coordinate(frame, action),
    keyboardRef: interaction.keyboardRef,
    cancelInput: interaction.cancel,
  });
  cancel.current = interaction.cancel;
  if (state.type === "READY") {
    state = {
      ...state,
      connection:
        live.state.connection === "revoked" ? "stale" : live.state.connection,
      image: live.state.image,
      status,
      canInput:
        state.canClose &&
        !mutationPending &&
        status?.allow_input === true &&
        live.state.connection === "connected",
      canClose:
        state.canClose &&
        !mutationPending &&
        live.state.connection !== "closed",
      dialog: status?.dialog ?? null,
      conflict: live.state.conflict,
      outcomeUnknown: live.state.outcomeUnknown,
    };
  }
  const currentState = state;
  useEffect(() => {
    if (!focused) {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const viewport = window.visualViewport;
    const updateViewport = (): void =>
      setFocusViewport(
        viewport === null
          ? null
          : { top: viewport.offsetTop, height: viewport.height },
      );
    updateViewport();
    viewport?.addEventListener("resize", updateViewport);
    viewport?.addEventListener("scroll", updateViewport);
    const escape = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !event.isComposing) {
        event.preventDefault();
        event.stopPropagation();
        cancel.current();
        setFocused(false);
      }
    };
    window.addEventListener("keydown", escape, true);
    return () => {
      window.removeEventListener("keydown", escape, true);
      viewport?.removeEventListener("resize", updateViewport);
      viewport?.removeEventListener("scroll", updateViewport);
      document.body.style.overflow = previousOverflow;
      setFocusViewport(null);
    };
  }, [focused]);
  const navigationEnabled =
    currentState.type === "READY" &&
    currentState.canInput &&
    currentState.dialog === null &&
    source !== null &&
    status !== null &&
    browserFrameMatchesStatus(source, status) &&
    live.state.pendingInputs === 0;
  const navigate = (action: BrowserNavigationAction): void => {
    if (!navigationEnabled) {
      return;
    }
    interaction.cancel();
    if (live.coordinate(source, action)) {
      setAddressDraft(null);
      setAddressError(false);
      void utils.browser.projection.invalidate(resource);
    }
  };
  const canCreate =
    !denied &&
    query.data?.available === true &&
    query.data.allow_input &&
    !mutationPending;
  return {
    state,
    focused,
    focusViewport,
    zoom,
    onToggleFocus: () => {
      interaction.cancel();
      interaction.keyboardRef.current?.blur();
      setFocused((value) => !value);
    },
    onZoomChange: (value) => {
      if (Number.isFinite(value) && value >= 1 && value <= 3) {
        interaction.cancel();
        touchView.cancel();
        setZoom(value);
      }
    },
    addressValue: addressDraft ?? selectedAddress,
    addressError,
    navigationEnabled,
    onAddressChange: (value) => {
      setAddressDraft(value);
      setAddressError(false);
    },
    onAddressFocus: () => setAddressDraft(selectedAddress),
    onAddressBlur: () => {
      setAddressDraft(null);
      setAddressError(false);
    },
    onAddressSubmit: () => {
      const url = browserAddress(addressDraft ?? selectedAddress);
      if (url === null) {
        setAddressError(true);
      } else {
        navigate({ kind: "navigation", action: "navigate", url });
      }
    },
    onNavigate: navigate,
    closeError: close.isError,
    createError: create.isError,
    creating: create.isPending,
    canCreate,
    onCreatePage: () => {
      if (canCreate) {
        interaction.cancel();
        create.mutate(resource);
      }
    },
    onSelect: (target) => {
      interaction.cancel();
      if (!close.isPending) {
        close.reset();
      }
      router.replace(browserPanelHref(pathname, search.toString(), target), {
        scroll: false,
      });
    },
    onClosePage: (target) => {
      if (
        currentState.type !== "READY" ||
        !currentState.canClose ||
        mutationPending ||
        !currentState.pages.some((page) =>
          sameBrowserTarget(page.target, target),
        )
      ) {
        return;
      }
      interaction.cancel();
      close.mutate({
        ...resource,
        taskId: target.task_id,
        pageId: target.page_id,
        resourceIncarnation: target.resource_incarnation,
      });
    },
    onRetry: () => {
      interaction.cancel();
      if (!close.isPending) {
        close.reset();
      }
      if (!create.isPending) {
        create.reset();
      }
      setDeniedResource(null);
      live.reconnect();
      void utils.browser.projection.invalidate(resource);
    },
    onFrameDisplayed: live.displayed,
    onFrameError: live.frameError,
    onDialogResponse: (accept) => {
      if (
        query.data?.allow_input === true &&
        live.dialog(
          accept,
          status?.dialog?.type === "prompt" ? dialogText : null,
        )
      ) {
        setDialogText("");
      }
    },
    dialogText,
    onDialogTextChange: setDialogText,
    keyboardRef: interaction.keyboardRef,
    interaction: interaction.interaction,
    touchView,
  };
}
