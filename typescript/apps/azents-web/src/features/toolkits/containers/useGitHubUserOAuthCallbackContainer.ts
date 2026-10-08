"use client";
import { readSessionStorageValue } from "@mantine/hooks";
import { useEffect, useRef, useState } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";
import { trpc } from "@/trpc/client";
import {
  deserializeGitHubUserContext,
  GITHUB_USER_COMPLETION_EVENT,
  GITHUB_USER_CONTEXT_KEY,
  githubUserErrorReason,
  parseGitHubUserState,
} from "../../../shared/toolkits/github-user-oauth-state";
import type { GitHubUserContext } from "../../../shared/toolkits/github-user-oauth-state";
import type { GitHubUserOAuthCallbackResultProps } from "../components/GitHubUserOAuthCallbackResult";

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
        setResult({
          state: { type: "COMPLETE" },
          returnPath: context.returnPath,
        });
      })
      .catch((error: unknown) => {
        setResult({
          state: {
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
          },
          returnPath: context.returnPath,
        });
      })
      .finally(notify);
  }, [cancel, code, exchange, providerError, state]);
  return result;
}
