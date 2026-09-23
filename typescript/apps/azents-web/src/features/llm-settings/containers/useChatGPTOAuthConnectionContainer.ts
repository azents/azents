"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { trpc } from "@/trpc/client";
import type { ChatGPTOAuthDeviceState } from "../components/ChatGPTOAuthConnectionCard";

interface ChatGPTOAuthConnectionContainerInput {
  handle: string;
  integrationId?: string;
  onConnected?: () => void;
}

interface ChatGPTOAuthConnectionContainerOutput {
  state: ChatGPTOAuthDeviceState;
  starting: boolean;
  cancelling: boolean;
  onStart: () => void;
  onCancel: () => void;
}

export function useChatGPTOAuthConnectionContainer({
  handle,
  integrationId,
  onConnected,
}: ChatGPTOAuthConnectionContainerInput): ChatGPTOAuthConnectionContainerOutput {
  const t = useTranslations("workspace.llmSettings.chatgptOAuth");
  const utils = trpc.useUtils();
  const [state, setState] = useState<ChatGPTOAuthDeviceState>({ type: "IDLE" });

  const startMutation =
    trpc.llmProviderIntegration.startChatgptOauthDevice.useMutation({
      onSuccess: (data) => {
        setState({
          type: "PENDING",
          sessionId: data.session_id,
          userCode: data.user_code,
          verificationUri: data.verification_uri,
          intervalMs: data.interval_seconds * 1000,
        });
      },
      onError: (error) => {
        setState({ type: "ERROR", message: error.message });
      },
    });

  const cancelMutation =
    trpc.llmProviderIntegration.cancelChatgptOauthDevice.useMutation({
      onSuccess: () => {
        setState({ type: "IDLE" });
      },
    });

  const deviceSessionId = state.type === "PENDING" ? state.sessionId : "";
  const statusQuery =
    trpc.llmProviderIntegration.getChatgptOauthDeviceStatus.useQuery(
      { handle, sessionId: deviceSessionId },
      {
        enabled: state.type === "PENDING",
        refetchInterval: state.type === "PENDING" ? state.intervalMs : false,
      },
    );

  useEffect(() => {
    if (statusQuery.data?.status === "connected") {
      setState({ type: "CONNECTED" });
      void utils.llmProviderIntegration.list.invalidate({ handle });
      onConnected?.();
    } else if (
      statusQuery.data?.status === "expired" ||
      statusQuery.data?.status === "failed" ||
      statusQuery.data?.status === "cancelled"
    ) {
      setState({
        type: "ERROR",
        message: t("statusError", { status: statusQuery.data.status }),
      });
    }
  }, [statusQuery.data?.status, handle, onConnected, t, utils]);

  useEffect(() => {
    if (statusQuery.isError) {
      setState({ type: "ERROR", message: statusQuery.error.message });
    }
  }, [statusQuery.error?.message, statusQuery.isError]);

  const onStart = useCallback((): void => {
    startMutation.mutate({ handle, integrationId });
  }, [startMutation, handle, integrationId]);

  const onCancel = useCallback((): void => {
    if (state.type !== "PENDING") {
      return;
    }
    cancelMutation.mutate({ handle, sessionId: state.sessionId });
  }, [cancelMutation, state, handle]);

  return {
    state,
    starting: startMutation.isPending,
    cancelling: cancelMutation.isPending,
    onStart,
    onCancel,
  };
}
