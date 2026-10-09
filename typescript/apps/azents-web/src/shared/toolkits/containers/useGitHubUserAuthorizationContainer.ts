"use client";
import {
  readSessionStorageValue,
  useInterval,
  useSessionStorage,
  useWindowEvent,
} from "@mantine/hooks";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  decodeGitHubUserCompletion,
  deserializeGitHubUserContext,
  GITHUB_USER_CONTEXT_KEY,
  githubUserErrorReason,
  gitHubUserResumeMatches,
  mergeGitHubUserAccess,
} from "../github-user-oauth-state";
import type { GitHubUserAuthorizationProps } from "../components/GitHubUserAuthorization";
import type { GitHubUserContext } from "../github-user-oauth-state";
import type {
  GitHubUserAccessState,
  GitHubUserOperationState,
  GitHubUserSetupState,
} from "../types";
import type { ToolkitConfigResponse } from "@azents/public-client";

export interface GitHubUserAuthorizationContainerProps {
  context: GitHubUserContext;
  toolkit: ToolkitConfigResponse;
  registrationDirty?: boolean;
  initialPopup?: Window | null;
  onInitialPopupAccepted?: (popup: Window) => void;
  onPendingChange?: (pending: boolean) => void;
}
export function useGitHubUserAuthorizationContainer({
  context,
  toolkit,
  registrationDirty = false,
  initialPopup = null,
  onInitialPopupAccepted,
  onPendingChange,
}: GitHubUserAuthorizationContainerProps): GitHubUserAuthorizationProps {
  const utils = trpc.useUtils();
  const apiContext = {
    handle: context.handle,
    toolkitId: context.toolkitId,
    agentId: context.agentId,
  };
  const status = trpc.toolkit.githubUser.status.useQuery(apiContext);
  const [, saveContext, clearContext] =
    useSessionStorage<GitHubUserContext | null>({
      key: GITHUB_USER_CONTEXT_KEY,
      defaultValue: null,
      deserialize: deserializeGitHubUserContext,
    });
  const [setup, setSetup] = useState<GitHubUserSetupState>({ type: "IDLE" });
  const [operation, setOperation] = useState<GitHubUserOperationState>({
    type: "IDLE",
  });
  const [access, setAccess] = useState<GitHubUserAccessState>({ type: "IDLE" });
  const popup = useRef<Window | null>(null);
  const attempt = useRef<string | null>(null);
  const accessRequest = useRef(0);
  const currentConnectionId = status.data?.connection?.id;
  useEffect(() => {
    accessRequest.current += 1;
    setAccess({ type: "IDLE" });
  }, [currentConnectionId]);
  const connect = trpc.toolkit.githubUser.connect.useMutation();
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) {
      return;
    }
    resumed.current = true;
    const saved =
      readSessionStorageValue<GitHubUserContext | null>({
        key: GITHUB_USER_CONTEXT_KEY,
        deserialize: deserializeGitHubUserContext,
      }) ?? null;
    if (!gitHubUserResumeMatches(saved, context)) {
      return;
    }
    const id = saved.reviewAttemptId;
    attempt.current = id;
    setSetup({ type: "REVIEW_LOADING", attemptId: id });
    void utils.toolkit.githubUser.review
      .fetch({
        handle: context.handle,
        toolkitId: context.toolkitId,
        agentId: context.agentId,
        attemptId: id,
      })
      .then((candidate) => {
        if (attempt.current === id) {
          setSetup({ type: "REVIEW", candidate });
        }
      })
      .catch((error: unknown) => {
        if (attempt.current === id) {
          setSetup({
            type: "ERROR",
            reason: githubUserErrorReason(error, "reviewFailed"),
            attemptId: id,
          });
        }
      });
  }, [context, utils.toolkit.githubUser.review]);
  async function invalidate(): Promise<void> {
    accessRequest.current += 1;
    setAccess({ type: "IDLE" });
    await Promise.allSettled([
      utils.toolkit.githubUser.status.invalidate(apiContext),
      utils.toolkit.githubUser.review.invalidate(),
      utils.toolkit.githubUser.access.invalidate(),
      utils.toolkit.listConfigs.invalidate(),
      utils.toolkit.listAvailableConfigs.invalidate(),
      utils.toolkit.listAgentManagement.invalidate(),
      context.agentId == null
        ? utils.toolkit.getConfig.invalidate({
            handle: context.handle,
            toolkitId: context.toolkitId,
          })
        : utils.toolkit.getAgentConfig.invalidate({
            handle: context.handle,
            agentId: context.agentId,
            toolkitConfigId: context.toolkitId,
          }),
    ]);
  }
  const confirm = trpc.toolkit.githubUser.confirm.useMutation({
    onSettled: invalidate,
  });
  const cancel = trpc.toolkit.githubUser.cancel.useMutation({
    onSettled: invalidate,
  });
  const disconnect = trpc.toolkit.githubUser.disconnect.useMutation({
    onSettled: invalidate,
  });
  async function cancelAttempt(reason?: "popupClosed"): Promise<void> {
    const id = attempt.current;
    if (id == null) {
      setSetup({ type: "IDLE" });
      return;
    }
    popup.current?.close();
    popup.current = null;
    stop();
    setSetup({ type: "CANCELLING", attemptId: id });
    attempt.current = null;
    clearContext();
    try {
      await cancel.mutateAsync({ ...apiContext, attemptId: id });
      setSetup(
        reason ? { type: "ERROR", reason, attemptId: null } : { type: "IDLE" },
      );
    } catch (error) {
      setSetup({
        type: "ERROR",
        reason: githubUserErrorReason(error, "setupFailed"),
        attemptId: null,
      });
    }
  }
  const { start, stop } = useInterval(() => {
    if (popup.current?.closed) {
      void cancelAttempt("popupClosed");
    }
  }, 500);
  useEffect(
    () => () => {
      stop();
    },
    [stop],
  );
  const pending =
    (setup.type !== "IDLE" &&
      (setup.type !== "ERROR" || setup.attemptId != null)) ||
    operation.type === "DISCONNECT_CONFIRM" ||
    operation.type === "DISCONNECTING";
  useEffect(() => {
    onPendingChange?.(pending);
    return () => onPendingChange?.(false);
  }, [onPendingChange, pending]);
  function onStart(): void {
    if (registrationDirty || attempt.current != null || connect.isPending) {
      return;
    }
    saveContext(context);
    const reserved = window.open(
      "about:blank",
      "_blank",
      "width=1024,height=768",
    );
    if (reserved == null) {
      clearContext();
      setSetup({ type: "ERROR", reason: "popupBlocked", attemptId: null });
      return;
    }
    begin(reserved);
  }
  function begin(reserved: Window): void {
    popup.current = reserved;
    setSetup({ type: "STARTING" });
    void connect
      .mutateAsync(apiContext)
      .then((result) => {
        attempt.current = result.attempt_id;
        if (reserved.closed) {
          void cancelAttempt("popupClosed");
          return;
        }
        setSetup({
          type: "WAITING",
          attemptId: result.attempt_id,
          installUrl: result.install_url,
        });
        reserved.location.href = result.authorization_url;
        start();
      })
      .catch((error: unknown) => {
        reserved.close();
        popup.current = null;
        clearContext();
        setSetup({
          type: "ERROR",
          reason: githubUserErrorReason(error, "setupFailed"),
          attemptId: null,
        });
        void invalidate();
      });
  }
  const started = useRef<Window | null>(null);
  const beginFromEffect = useEffectEvent(begin);
  useEffect(() => {
    if (initialPopup != null && started.current !== initialPopup) {
      started.current = initialPopup;
      onInitialPopupAccepted?.(initialPopup);
      if (initialPopup.closed) {
        setSetup({ type: "ERROR", reason: "setupFailed", attemptId: null });
      } else {
        beginFromEffect(initialPopup);
      }
    }
  }, [initialPopup, onInitialPopupAccepted]);
  useWindowEvent("message", (event: MessageEvent<unknown>): void => {
    if (
      !decodeGitHubUserCompletion(
        event,
        window.location.origin,
        popup.current,
        attempt.current,
      )
    ) {
      return;
    }
    const id = attempt.current;
    if (id == null) {
      return;
    }
    stop();
    popup.current = null;
    setSetup({ type: "REVIEW_LOADING", attemptId: id });
    void utils.toolkit.githubUser.review
      .fetch({ ...apiContext, attemptId: id })
      .then((candidate) => {
        if (attempt.current === id) {
          setSetup({ type: "REVIEW", candidate });
        }
      })
      .catch((error: unknown) => {
        if (attempt.current !== id) {
          return;
        }
        setSetup({
          type: "ERROR",
          reason: githubUserErrorReason(error, "reviewFailed"),
          attemptId: id,
        });
        void invalidate();
      });
  });
  async function loadAccess(more: boolean): Promise<void> {
    if (access.type === "LOADING" || access.type === "MORE") {
      return;
    }
    const previous =
      more && "installations" in access ? access.installations : [];
    const cursor = more && "nextCursor" in access ? access.nextCursor : null;
    if (more && cursor == null) {
      return;
    }
    const requestId = ++accessRequest.current;
    setAccess(
      more && cursor != null
        ? { type: "MORE", installations: previous, nextCursor: cursor }
        : { type: "LOADING" },
    );
    try {
      const page = await utils.toolkit.githubUser.access.fetch({
        ...apiContext,
        cursor,
      });
      if (requestId === accessRequest.current) {
        setAccess({
          type: "READY",
          installations: mergeGitHubUserAccess(previous, page.installations),
          nextCursor: page.next_cursor,
        });
      }
    } catch {
      if (requestId === accessRequest.current) {
        setAccess({
          type: "ERROR",
          installations: previous,
          nextCursor: cursor,
        });
      }
      await utils.toolkit.githubUser.status.invalidate(apiContext);
    }
  }
  return {
    setup,
    operation,
    access,
    registrationDirty,
    status: status.isError
      ? { type: "ERROR" }
      : status.data
        ? {
            type: "READY",
            connection: status.data.connection,
          }
        : { type: "LOADING" },
    currentConnection: status.data
      ? status.data.connection
      : (toolkit.github_user_connection ?? null),
    sharingScope: context.agentId == null ? "workspace_shared" : "agent_only",
    onStart,
    onCancel: () => {
      void cancelAttempt();
    },
    onConfirm: () => {
      if (setup.type !== "REVIEW") {
        return;
      }
      const candidate = setup.candidate;
      setSetup({ type: "CONFIRMING", candidate });
      void confirm
        .mutateAsync({ ...apiContext, attemptId: candidate.attempt_id })
        .then(() => {
          attempt.current = null;
          clearContext();
          setSetup({ type: "IDLE" });
        })
        .catch((error: unknown) => {
          attempt.current = null;
          clearContext();
          setSetup({
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
            attemptId: null,
          });
        });
    },
    onRequestDisconnect: () => setOperation({ type: "DISCONNECT_CONFIRM" }),
    onCancelDisconnect: () => setOperation({ type: "IDLE" }),
    onDisconnect: () => {
      popup.current?.close();
      popup.current = null;
      attempt.current = null;
      stop();
      clearContext();
      setOperation({ type: "DISCONNECTING" });
      void disconnect
        .mutateAsync(apiContext)
        .then(() => {
          attempt.current = null;
          setSetup({ type: "IDLE" });
          setOperation({ type: "IDLE" });
        })
        .catch((error: unknown) => {
          attempt.current = null;
          setSetup({ type: "IDLE" });
          setOperation({
            type: "ERROR",
            reason: githubUserErrorReason(error, "disconnectFailed"),
          });
        });
    },
    onRetryStatus: () => {
      void utils.toolkit.githubUser.status.invalidate(apiContext);
    },
    onRecheckAccess: () => {
      void utils.toolkit.githubUser.access
        .invalidate()
        .then(() => loadAccess(false));
    },
    onMoreAccess: () => {
      void loadAccess(true);
    },
  };
}
