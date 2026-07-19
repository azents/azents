"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { KimiOAuthDeviceState } from "../types";

export interface KimiOAuthConnectionContainerProps {
  handle: string;
  onConnected?: () => void;
}

export interface KimiOAuthConnectionContainerOutput {
  state: KimiOAuthDeviceState;
  starting: boolean;
  cancelling: boolean;
  onStart: () => void;
  onCancel: () => void;
}

export function useKimiOAuthConnectionContainer({
  handle,
  onConnected,
}: KimiOAuthConnectionContainerProps): KimiOAuthConnectionContainerOutput {
  const t = useTranslations("workspace.llmSettings.kimiOAuth");
  const utils = trpc.useUtils();
  const [state, setState] = useState<KimiOAuthDeviceState>({ type: "IDLE" });
  const pendingSessionIdRef = useRef<string | null>(null);

  const startMutation =
    trpc.llmProviderIntegration.startKimiOauthDevice.useMutation({
      onSuccess: (data) => {
        pendingSessionIdRef.current = data.session_id;
        setState({
          type: "PENDING",
          sessionId: data.session_id,
          userCode: data.user_code,
          verificationUri: data.verification_uri,
          intervalMs: data.interval_seconds * 1000,
          expiresAt: data.expires_at,
        });
      },
      onError: (error) => {
        setState({ type: "ERROR", message: error.message });
      },
    });

  const cancelMutation =
    trpc.llmProviderIntegration.cancelKimiOauthDevice.useMutation({
      onSuccess: () => {
        pendingSessionIdRef.current = null;
        setState({ type: "IDLE" });
      },
      onError: (error) => {
        setState({ type: "ERROR", message: error.message });
      },
    });

  const cleanupCancelMutation =
    trpc.llmProviderIntegration.cancelKimiOauthDevice.useMutation();
  const cancelDeviceRef = useRef(cleanupCancelMutation.mutate);
  useEffect(() => {
    cancelDeviceRef.current = cleanupCancelMutation.mutate;
  }, [cleanupCancelMutation.mutate]);

  useEffect(
    () => () => {
      const pendingSessionId = pendingSessionIdRef.current;
      if (pendingSessionId === null) {
        return;
      }
      pendingSessionIdRef.current = null;
      cancelDeviceRef.current({ handle, sessionId: pendingSessionId });
    },
    [handle],
  );

  const sessionId = state.type === "PENDING" ? state.sessionId : "";
  const statusQuery =
    trpc.llmProviderIntegration.getKimiOauthDeviceStatus.useQuery(
      { handle, sessionId },
      {
        enabled: state.type === "PENDING",
        refetchInterval: state.type === "PENDING" ? state.intervalMs : false,
        retry: false,
      },
    );

  useEffect(() => {
    if (statusQuery.data?.status === "pending") {
      const intervalMs = statusQuery.data.interval_seconds * 1000;
      setState((current) =>
        current.type === "PENDING" && current.intervalMs !== intervalMs
          ? { ...current, intervalMs }
          : current,
      );
      return;
    }
    if (statusQuery.data?.status === "connected") {
      pendingSessionIdRef.current = null;
      setState({ type: "CONNECTED" });
      void utils.llmProviderIntegration.list.invalidate({ handle });
      void utils.llmProviderIntegration.listProviders.invalidate({ handle });
      void utils.llmProviderIntegration.listModels.invalidate();
      onConnected?.();
      return;
    }
    if (
      statusQuery.data?.status === "expired" ||
      statusQuery.data?.status === "failed" ||
      statusQuery.data?.status === "cancelled"
    ) {
      pendingSessionIdRef.current = null;
      setState({
        type: "ERROR",
        message: t("statusError", { status: statusQuery.data.status }),
      });
    }
  }, [
    handle,
    onConnected,
    statusQuery.data?.interval_seconds,
    statusQuery.data?.status,
    t,
    utils,
  ]);

  useEffect(() => {
    if (state.type !== "PENDING") {
      return;
    }
    const expiresAt = Date.parse(state.expiresAt);
    if (!Number.isFinite(expiresAt)) {
      return;
    }
    const sessionIdAtStart = state.sessionId;
    const timeout = window.setTimeout(
      () => {
        if (pendingSessionIdRef.current !== sessionIdAtStart) {
          return;
        }
        pendingSessionIdRef.current = null;
        cancelDeviceRef.current({ handle, sessionId: sessionIdAtStart });
        setState({
          type: "ERROR",
          message: t("statusError", { status: "expired" }),
        });
      },
      Math.max(expiresAt - Date.now(), 0),
    );
    return () => window.clearTimeout(timeout);
  }, [handle, state, t]);

  useEffect(() => {
    if (statusQuery.isError) {
      const pendingSessionId = pendingSessionIdRef.current;
      pendingSessionIdRef.current = null;
      if (pendingSessionId !== null) {
        cancelDeviceRef.current({ handle, sessionId: pendingSessionId });
      }
      setState({ type: "ERROR", message: statusQuery.error.message });
    }
  }, [handle, statusQuery.error?.message, statusQuery.isError]);

  const onStart = useCallback((): void => {
    startMutation.mutate({ handle });
  }, [handle, startMutation]);

  const onCancel = useCallback((): void => {
    if (state.type !== "PENDING") {
      return;
    }
    cancelMutation.mutate({ handle, sessionId: state.sessionId });
  }, [cancelMutation, handle, state]);

  return {
    state,
    starting: startMutation.isPending,
    cancelling: cancelMutation.isPending,
    onStart,
    onCancel,
  };
}
