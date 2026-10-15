"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { browserAddress, browserFrameMatchesStatus } from "../input";
import { browserProjectionState } from "../projection";
import { browserPanelHref, parseBrowserTarget } from "../route";
import {
  browserAccessError,
  useBrowserConnection,
} from "./useBrowserConnection";
import { useBrowserInteraction } from "./useBrowserInteraction";
import type { SessionBrowserPanelProps } from "../components/SessionBrowserPanel";
import type {
  BrowserNavigationAction,
  BrowserPageChoice,
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

/** Bind one fresh admitted attachment to the exact concrete Session and selected resource. */
export function useSessionBrowserContainer(
  resource: SessionBrowserContainerProps,
): SessionBrowserPanelProps {
  const t = useTranslations("chat.browser");
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const utils = trpc.useUtils();
  const resourceKey = JSON.stringify([
    resource.handle,
    resource.agentId,
    resource.sessionId,
  ]);
  const [denial, setDenial] = useState<{
    key: string;
    kind: "access" | "target";
  } | null>(null);
  const denied = denial?.key === resourceKey ? denial.kind : null;
  const query = trpc.browser.projection.useQuery(resource, {
    retry: false,
    refetchInterval: 5000,
    enabled: denied === null,
  });
  const { mutateAsync: connectionInfo } =
    trpc.browser.connectionInfo.useMutation({ retry: false });
  const { handle, agentId, sessionId } = resource;
  const connect = useCallback(
    () => connectionInfo({ handle, agentId, sessionId }),
    [connectionInfo, handle, agentId, sessionId],
  );
  const rejected = useCallback(
    (kind: "access" | "target"): void => {
      setDenial({ key: resourceKey, kind });
      void utils.browser.projection.reset({ handle, agentId, sessionId });
    },
    [resourceKey, handle, agentId, sessionId, utils.browser.projection],
  );
  const close = trpc.browser.closePage.useMutation({
    retry: false,
    onSuccess: async () => {
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
    if (denied === null && query.isError && browserAccessError(query.error)) {
      rejected("access");
    }
  }, [denied, query.isError, query.error, rejected]);

  let state: BrowserViewState;
  if (denied === "access") {
    state = { type: "ACCESS_CHANGED" };
  } else if (denied === "target") {
    state = { type: "CLOSED_TARGET", pages: [] };
  } else if (query.isLoading) {
    state = { type: "LOADING" };
  } else if (query.isError || !query.data) {
    state = { type: "ERROR" };
  } else if (!query.data.available) {
    state = {
      type: "UNAVAILABLE",
      reason:
        query.data.reason_code === "browser_disabled"
          ? t("browserDisabled")
          : query.data.reason_code === "runtime_unavailable"
            ? t("runtimeUnavailable")
            : query.data.reason_code === "working_folder_unavailable"
              ? t("workingFolderUnavailable")
              : t("capabilityUnavailable"),
    };
  } else {
    state = browserProjectionState(
      pages(query.data),
      parseBrowserTarget(search.toString()),
      query.data.allow_input,
    );
  }

  const cancel = useRef<() => void>(() => {});
  const live = useBrowserConnection({
    resourceKey: `${resourceKey}\u0000${query.data?.allow_input === true ? "direct" : "observe"}`,
    target: state.type === "READY" ? state.selected.target : null,
    connect,
    rejected,
    cancelInteraction: () => cancel.current(),
  });
  const [dialogText, setDialogText] = useState("");
  const [focused, setFocused] = useState(false);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    if (state.type !== "READY") {
      setFocused(false);
    }
  }, [state.type]);
  const [addressDraft, setAddressDraft] = useState<string | null>(null);
  const [addressError, setAddressError] = useState(false);
  const dialogId = live.state.status?.dialog?.id;
  useEffect(() => {
    setDialogText("");
  }, [resourceKey, dialogId]);
  const source = live.state.displayed;
  const status = live.state.status;
  const selectedAddress = state.type === "READY" ? state.selected.url : "";
  const selectedPage =
    state.type === "READY" ? state.selected.target.page_id : null;
  useEffect(() => {
    setAddressDraft(null);
    setAddressError(false);
  }, [resourceKey, selectedPage]);
  const interaction = useBrowserInteraction({
    enabled:
      state.type === "READY" &&
      !close.isPending &&
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
        !close.isPending &&
        status?.allow_input === true &&
        live.state.connection === "connected",
      canClose:
        state.canClose &&
        !close.isPending &&
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
      document.body.style.overflow = previousOverflow;
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
  return {
    state,
    focused,
    zoom,
    onToggleFocus: () => {
      interaction.cancel();
      setFocused((value) => !value);
    },
    onZoomChange: (value) => {
      if (Number.isFinite(value) && value >= 1 && value <= 3) {
        interaction.cancel();
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
    onSelect: (target) => {
      interaction.cancel();
      if (!close.isPending) {
        close.reset();
      }
      router.replace(browserPanelHref(pathname, search.toString(), target), {
        scroll: false,
      });
    },
    onClosePage: () => {
      if (
        currentState.type !== "READY" ||
        !currentState.canClose ||
        close.isPending
      ) {
        return;
      }
      interaction.cancel();
      close.mutate({
        ...resource,
        taskId: currentState.selected.target.task_id,
        pageId: currentState.selected.target.page_id,
        resourceIncarnation: currentState.selected.target.resource_incarnation,
      });
    },
    onRetry: () => {
      interaction.cancel();
      if (!close.isPending) {
        close.reset();
      }
      setDenial(null);
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
  };
}
