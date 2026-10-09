"use client";
import { readSessionStorageValue, useSessionStorage } from "@mantine/hooks";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";
import { trpc } from "@/trpc/client";
import {
  deserializeGitHubUserCreation,
  GITHUB_USER_CREATION_KEY,
  parseGitHubCreationState,
} from "../github-user-creation-state";
import {
  deserializeGitHubUserContext,
  GITHUB_USER_COMPLETION_EVENT,
  GITHUB_USER_CONTEXT_KEY,
  githubUserErrorReason,
  parseGitHubUserState,
} from "../github-user-oauth-state";
import type { GitHubUserOAuthCallbackResultProps } from "../components/GitHubUserOAuthCallbackResult";
import type { GitHubUserCreationContext } from "../github-user-creation-state";
import type { GitHubUserContext } from "../github-user-oauth-state";

export interface GitHubUserOAuthCallbackContainerProps {
  code: string | null;
  state: string | null;
  providerError: string | null;
}
export function useGitHubUserOAuthCallbackContainer({
  code,
  state,
  providerError,
}: GitHubUserOAuthCallbackContainerProps): GitHubUserOAuthCallbackResultProps {
  const exchange = trpc.toolkit.githubUser.exchange.useMutation();
  const creationExchange =
    trpc.toolkit.githubUserCreation.exchange.useMutation();
  const creationCancel = trpc.toolkit.githubUserCreation.cancel.useMutation();
  const [, saveCreation] = useSessionStorage<GitHubUserCreationContext | null>({
    key: GITHUB_USER_CREATION_KEY,
    defaultValue: null,
    deserialize: deserializeGitHubUserCreation,
  });
  const router = useRouter();
  const [, saveContext] = useSessionStorage<GitHubUserContext | null>({
    key: GITHUB_USER_CONTEXT_KEY,
    defaultValue: null,
    deserialize: deserializeGitHubUserContext,
  });
  const cancel = trpc.toolkit.githubUser.cancel.useMutation();
  const started = useRef(false);
  const [result, setResult] = useState<GitHubUserOAuthCallbackResultProps>({
    state: { type: "LOADING" },
    returnPath: null,
  });
  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    const creationId = parseGitHubCreationState(state);
    if (creationId != null) {
      const creation =
        readSessionStorageValue<GitHubUserCreationContext | null>({
          key: GITHUB_USER_CREATION_KEY,
          deserialize: deserializeGitHubUserCreation,
        });
      if (
        creation == null ||
        creation.attemptId !== creationId ||
        creation.phase !== "AUTHORIZING"
      ) {
        setResult({
          state: { type: "ERROR", reason: "stale" },
          returnPath: null,
        });
        return;
      }
      const scope = { handle: creation.handle, agentId: creation.agentId };
      const operation =
        providerError != null || code == null || state == null
          ? creationCancel
              .mutateAsync({ ...scope, attemptId: creationId })
              .then<"ERROR">(() => "ERROR")
          : creationExchange
              .mutateAsync({ ...scope, code, state })
              .then<"REVIEW">(() => "REVIEW");
      void operation
        .then((phase) => {
          saveCreation({ ...creation, phase });
          router.replace(creation.returnPath);
        })
        .catch(() => {
          saveCreation({ ...creation, phase: "ERROR" });
          router.replace(creation.returnPath);
        });
      return;
    }
    const context = readSessionStorageValue<GitHubUserContext | null>({
      key: GITHUB_USER_CONTEXT_KEY,
      deserialize: deserializeGitHubUserContext,
    });
    const attemptId = parseGitHubUserState(state);
    if (context == null || attemptId == null) {
      setResult({
        state: { type: "ERROR", reason: "stale" },
        returnPath: null,
      });
      return;
    }
    const apiContext = {
      handle: context.handle,
      agentId: context.agentId,
      toolkitId: context.toolkitId,
    };
    function notify(): void {
      const opener: unknown = window.opener;
      if (isWindowMessageTarget(opener)) {
        opener.postMessage(
          { type: GITHUB_USER_COMPLETION_EVENT, attempt_id: attemptId },
          window.location.origin,
        );
      }
    }
    if (providerError != null || code == null || state == null) {
      void cancel
        .mutateAsync({ ...apiContext, attemptId })
        .then(() =>
          setResult({
            state: { type: "ERROR", reason: "setupFailed" },
            returnPath: context.returnPath,
          }),
        )
        .catch((error: unknown) =>
          setResult({
            state: {
              type: "ERROR",
              reason: githubUserErrorReason(error, "setupFailed"),
            },
            returnPath: context.returnPath,
          }),
        )
        .finally(notify);
      return;
    }
    void exchange
      .mutateAsync({ ...apiContext, code, state })
      .then(() => {
        saveContext({ ...context, reviewAttemptId: attemptId });
        setResult({
          state: { type: "COMPLETE" },
          returnPath: context.returnPath,
        });
        notify();
        router.replace(context.returnPath);
      })
      .catch((error: unknown) => {
        setResult({
          state: {
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
          },
          returnPath: context.returnPath,
        });
        notify();
      });
  }, [
    cancel,
    code,
    creationCancel,
    creationExchange,
    exchange,
    providerError,
    router,
    saveContext,
    saveCreation,
    state,
  ]);
  return result;
}
