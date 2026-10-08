"use client";
import { useSessionStorage, useWindowEvent } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  consumeGitHubUserPopupHandoff,
  deserializeGitHubUserContext,
  GITHUB_USER_CONTEXT_KEY,
  isGitHubUserMode,
} from "@/shared/toolkits/github-user-oauth-state";
import { trpc } from "@/trpc/client";
import {
  canAuthorizeAgentToolkitOAuth,
  completedToolkitEditor,
  decodeAgentToolkitOAuthCallback,
  projectAgentToolkitManagementState,
} from "../agentToolkitManagementState";
import type {
  AgentToolkitEditorState,
  AgentToolkitManagementState,
  AgentToolkitMutationState,
} from "../types";
import type { GitHubUserContext } from "@/shared/toolkits/github-user-oauth-state";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";

export interface AgentToolkitManagementContainerProps {
  handle: string;
  agentId: string;
}

export interface AgentToolkitManagementContainerOutput extends AgentToolkitManagementContainerProps {
  state: AgentToolkitManagementState;
  editor: AgentToolkitEditorState;
  mutationState: AgentToolkitMutationState;
  deleteTarget: AgentToolkitManagementItemResponse | null;
  pending: boolean;
  attachPending: boolean;
  setupPending: boolean;
  attachPendingId: string | null;
  deletePending: boolean;
  canAuthorizeShared: boolean;
  authorizationPendingId: string | null;
  githubUserPopup?: { toolkitId: string; popup: Window } | null;
  onGithubUserPopupAccepted: (popup: Window) => void;
  onAuthorize: (item: AgentToolkitManagementItemResponse) => void;
  onStartAdd: () => void;
  onCatalogTabChange: (tab: "new" | "workspace") => void;
  onConfigureType: (toolkitType: string) => void;
  onDetails: (toolkitConfigId: string) => void;
  onEdit: (toolkitConfigId: string) => void;
  onCloseEditor: () => void;
  onCompleteSetup: () => void;
  onSetupPendingChange: (pending: boolean) => void;
  onRetryRead: () => void;
  onAttach: (toolkitId: string) => void;
  onDetach: (agentToolkitId: string) => void;
  onToggle: (item: AgentToolkitManagementItemResponse) => void;
  onRequestDelete: (item: AgentToolkitManagementItemResponse) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

export function useAgentToolkitManagementContainer({
  handle,
  agentId,
}: AgentToolkitManagementContainerProps): AgentToolkitManagementContainerOutput {
  const t = useTranslations("workspace.agents.toolkitManagement");
  const utils = trpc.useUtils();
  const [editor, setEditor] = useState<AgentToolkitEditorState>({
    type: "CLOSED",
  });
  const [mutationState, setMutationState] = useState<AgentToolkitMutationState>(
    { type: "IDLE" },
  );
  const [setupPending, setSetupPending] = useState(false);
  const [deleteTarget, setDeleteTarget] =
    useState<AgentToolkitManagementItemResponse | null>(null);
  const [authorizationPendingId, setAuthorizationPendingId] = useState<
    string | null
  >(null);
  const oauthPopup = useRef<Window | null>(null);
  const [githubUserPopup, setGithubUserPopup] = useState<{
    toolkitId: string;
    popup: Window;
  } | null>(null);
  const onGithubUserPopupAccepted = useCallback(
    (acceptedPopup: Window): void => {
      setGithubUserPopup((current) =>
        consumeGitHubUserPopupHandoff(current, acceptedPopup),
      );
    },
    [],
  );
  const [, saveGithubContext] = useSessionStorage<GitHubUserContext | null>({
    key: GITHUB_USER_CONTEXT_KEY,
    defaultValue: null,
    deserialize: deserializeGitHubUserContext,
  });
  const query = trpc.toolkit.listAgentManagement.useQuery({ handle, agentId });
  const definitionsQuery = trpc.toolkit.listToolkits.useQuery();
  const memberQuery = trpc.workspaceMember.me.useQuery({ handle });
  const canAuthorizeShared =
    memberQuery.data?.role === "owner" || memberQuery.data?.role === "manager";
  const invalidate = useCallback(async (): Promise<void> => {
    // The query owns read errors; an acknowledged write is still committed.
    await utils.toolkit.listAgentManagement
      .invalidate({ handle, agentId })
      .catch(() => null);
  }, [agentId, handle, utils.toolkit.listAgentManagement]);
  const attachMutation = trpc.toolkit.attachToAgent.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      setEditor({ type: "CLOSED" });
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const detachMutation = trpc.toolkit.detachFromAgent.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const updateMutation = trpc.toolkit.updateAgentConfig.useMutation({
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const deleteMutation = trpc.toolkit.removeAgentConfig.useMutation({
    onSettled: async () => {
      await Promise.allSettled([
        invalidate(),
        utils.toolkit.githubUser.status.invalidate(),
        utils.toolkit.githubUser.access.invalidate(),
        utils.toolkit.githubUser.review.invalidate(),
        utils.toolkit.getAgentConfig.invalidate(),
      ]);
    },
    onSuccess: async () => {
      setMutationState({ type: "IDLE" });
      setDeleteTarget(null);
      await invalidate();
    },
    onError: (error) =>
      setMutationState({ type: "ERROR", message: error.message }),
  });
  const connectSharedMutation = trpc.toolkit.connectOauth.useMutation();
  const connectAgentMutation = trpc.toolkit.connectAgentOauth.useMutation();
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    const callback = decodeAgentToolkitOAuthCallback(
      event,
      window.location.origin,
      oauthPopup.current,
    );
    if (callback == null) {
      return;
    }
    oauthPopup.current = null;
    if (callback === "SUCCESS") {
      setMutationState({ type: "IDLE" });
      void invalidate();
    } else {
      setMutationState({ type: "ERROR", message: t("authorizationFailed") });
    }
  });
  const onAuthorize = useCallback(
    (item: AgentToolkitManagementItemResponse): void => {
      if (
        !canAuthorizeAgentToolkitOAuth(item, canAuthorizeShared) ||
        authorizationPendingId != null ||
        setupPending
      ) {
        return;
      }
      if (oauthPopup.current && !oauthPopup.current.closed) {
        oauthPopup.current.focus();
        return;
      }
      setMutationState({ type: "IDLE" });
      if (
        item.toolkit.toolkit_type === "github" &&
        isGitHubUserMode(item.toolkit.config.github_auth_type)
      ) {
        setEditor({ type: "DETAIL", toolkitConfigId: item.toolkit.id });
        saveGithubContext({
          handle,
          toolkitId: item.toolkit.id,
          ...(item.ownership_scope === "agent_only" && { agentId }),
          returnView: "DETAIL",
          returnPath: `/w/${handle}/agents/${agentId}/settings/capabilities#agent-toolkits`,
        });
        const reserved = window.open(
          "about:blank",
          "_blank",
          "width=1024,height=768",
        );
        if (reserved == null) {
          setMutationState({ type: "ERROR", message: t("popupBlocked") });
          return;
        }
        setGithubUserPopup({ toolkitId: item.toolkit.id, popup: reserved });
        return;
      }
      // Reserve a popup in the click handler before awaiting the OAuth URL.
      const popup = window.open(
        "about:blank",
        "mcp-oauth-popup",
        "width=1024,height=768",
      );
      if (!popup) {
        setMutationState({
          type: "ERROR",
          message: t("popupBlocked"),
        });
        return;
      }
      oauthPopup.current = popup;
      setAuthorizationPendingId(item.toolkit.id);
      const request =
        item.ownership_scope === "workspace_shared"
          ? connectSharedMutation.mutateAsync({
              handle,
              toolkitConfigId: item.toolkit.id,
            })
          : connectAgentMutation.mutateAsync({
              handle,
              agentId,
              toolkitConfigId: item.toolkit.id,
            });
      void request
        .then((data) => {
          if (popup.closed) {
            setMutationState({
              type: "ERROR",
              message: t("popupClosed"),
            });
          } else {
            popup.location.href = data.authorization_url;
          }
        })
        .catch((error: unknown) => {
          popup.close();
          setMutationState({
            type: "ERROR",
            message:
              error instanceof Error
                ? error.message
                : t("authorizationStartFailed"),
          });
        })
        .finally(() => setAuthorizationPendingId(null));
    },
    [
      agentId,
      authorizationPendingId,
      canAuthorizeShared,
      connectAgentMutation,
      connectSharedMutation,
      handle,
      saveGithubContext,
      setupPending,
      t,
    ],
  );
  const state = useMemo(
    () =>
      projectAgentToolkitManagementState({
        loading: query.isLoading || definitionsQuery.isLoading,
        error: query.isError
          ? query.error.message
          : definitionsQuery.isError
            ? definitionsQuery.error.message
            : null,
        data: query.data,
        toolkitDefinitions: definitionsQuery.data?.items,
      }),
    [
      definitionsQuery.data,
      definitionsQuery.error,
      definitionsQuery.isError,
      definitionsQuery.isLoading,
      query.data,
      query.error,
      query.isError,
      query.isLoading,
    ],
  );
  const closeEditor = useCallback((): void => {
    if (setupPending || attachMutation.isPending) {
      return;
    }
    setEditor({ type: "CLOSED" });
    setGithubUserPopup(null);
    void invalidate();
  }, [invalidate, setupPending, attachMutation.isPending]);

  return {
    handle,
    agentId,
    state,
    editor,
    mutationState,
    deleteTarget,
    pending:
      detachMutation.isPending ||
      updateMutation.isPending ||
      deleteMutation.isPending,
    attachPending: attachMutation.isPending,
    setupPending,
    attachPendingId: attachMutation.isPending
      ? attachMutation.variables.toolkitId
      : null,
    deletePending: deleteMutation.isPending,
    canAuthorizeShared,
    authorizationPendingId,
    githubUserPopup,
    onGithubUserPopupAccepted,
    onAuthorize,
    onStartAdd: () => {
      setMutationState({ type: "IDLE" });
      setEditor({ type: "CATALOG", tab: "new" });
    },
    onCatalogTabChange: (tab) => {
      setMutationState({ type: "IDLE" });
      setEditor({ type: "CATALOG", tab });
    },
    onConfigureType: (toolkitType) =>
      setEditor({ type: "CREATE", toolkitType }),
    onDetails: (toolkitConfigId) =>
      setEditor({ type: "DETAIL", toolkitConfigId }),
    onEdit: (toolkitConfigId) => setEditor({ type: "EDIT", toolkitConfigId }),
    onCloseEditor: closeEditor,
    onSetupPendingChange: setSetupPending,
    onRetryRead: () => {
      void utils.toolkit.listAgentManagement.invalidate({ handle, agentId });
      void utils.toolkit.listToolkits.invalidate();
    },
    onCompleteSetup: () => {
      setSetupPending(false);
      setEditor((current) => completedToolkitEditor(current, editor));
      void invalidate();
    },
    onAttach: (toolkitId) => {
      if (!attachMutation.isPending) {
        setMutationState({ type: "IDLE" });
        attachMutation.mutate({
          handle,
          agentId,
          toolkitId,
        });
      }
    },
    onDetach: (agentToolkitId) => {
      setMutationState({ type: "IDLE" });
      detachMutation.mutate({ handle, agentId, agentToolkitId });
    },
    onToggle: (item) => {
      setMutationState({ type: "IDLE" });
      updateMutation.mutate({
        handle,
        agentId,
        toolkitConfigId: item.toolkit.id,
        enabled: !item.toolkit.enabled,
      });
    },
    onRequestDelete: (item) => {
      setMutationState({ type: "IDLE" });
      setDeleteTarget(item);
    },
    onCancelDelete: () => setDeleteTarget(null),
    onConfirmDelete: () => {
      if (deleteTarget) {
        setMutationState({ type: "IDLE" });
        deleteMutation.mutate({
          handle,
          agentId,
          toolkitConfigId: deleteTarget.toolkit.id,
        });
      }
    },
  };
}
