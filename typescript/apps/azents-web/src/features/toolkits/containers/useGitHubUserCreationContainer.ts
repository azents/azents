"use client";
import { readSessionStorageValue, useSessionStorage } from "@mantine/hooks";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  creationReturnPath,
  deserializeGitHubUserCreation,
  GITHUB_USER_CREATION_KEY,
} from "../github-user-creation-state";
import { githubUserErrorReason } from "../github-user-oauth-state";
import type { GitHubUserCreationContext } from "../github-user-creation-state";
import type { GitHubUserSetupState } from "../github-user-oauth-state";
import type { ToolkitFormValues } from "../schemas";
import type { GitHubUserCreationReview } from "@azents/public-client";

export interface GitHubUserCreationControl {
  state: GitHubUserSetupState;
  start: (
    values: ToolkitFormValues,
    credentials: Record<string, unknown> | null,
  ) => void;
  cancel: () => void;
  confirm: () => void;
}
export function useGitHubUserCreationContainer({
  handle,
  agentId,
  enabled,
  onReview,
  onComplete,
  onPendingChange,
}: {
  handle: string;
  agentId?: string;
  enabled: boolean;
  onReview: (review: GitHubUserCreationReview) => void;
  onComplete?: () => void;
  onPendingChange?: (pending: boolean) => void;
}): GitHubUserCreationControl {
  const router = useRouter();
  const utils = trpc.useUtils();
  const connect = trpc.toolkit.githubUserCreation.connect.useMutation();
  const cancel = trpc.toolkit.githubUserCreation.cancel.useMutation();
  const confirm = trpc.toolkit.githubUserCreation.confirm.useMutation();
  const [, saveContext, clearContext] =
    useSessionStorage<GitHubUserCreationContext | null>({
      key: GITHUB_USER_CREATION_KEY,
      defaultValue: null,
      deserialize: deserializeGitHubUserCreation,
    });
  const [state, setState] = useState<GitHubUserSetupState>({ type: "IDLE" });
  const attempt = useRef<string | null>(null);
  const resumed = useRef(false);
  const returnPath = creationReturnPath(handle, agentId);
  useEffect(() => {
    if (!enabled || resumed.current) {
      return;
    }
    resumed.current = true;
    const saved = readSessionStorageValue<GitHubUserCreationContext | null>({
      key: GITHUB_USER_CREATION_KEY,
      deserialize: deserializeGitHubUserCreation,
    });
    if (
      saved == null ||
      saved.handle !== handle ||
      saved.agentId !== agentId ||
      saved.returnPath !== returnPath
    ) {
      return;
    }
    attempt.current = saved.attemptId;
    if (saved.phase !== "REVIEW") {
      setState({
        type: "ERROR",
        reason: "setupFailed",
        attemptId: saved.attemptId,
      });
      return;
    }
    setState({ type: "REVIEW_LOADING", attemptId: saved.attemptId });
    void utils.toolkit.githubUserCreation.review
      .fetch({ handle, agentId, attemptId: saved.attemptId })
      .then((review) => {
        onReview(review);
        setState({ type: "REVIEW", candidate: review.candidate });
      })
      .catch((error: unknown) =>
        setState({
          type: "ERROR",
          reason: githubUserErrorReason(error, "reviewFailed"),
          attemptId: saved.attemptId,
        }),
      );
  }, [
    agentId,
    enabled,
    handle,
    onReview,
    returnPath,
    utils.toolkit.githubUserCreation.review,
  ]);
  useEffect(() => {
    const pending =
      state.type !== "IDLE" &&
      (state.type !== "ERROR" || state.attemptId != null);
    onPendingChange?.(pending);
    return () => onPendingChange?.(false);
  }, [onPendingChange, state]);
  return {
    state,
    start: (values, credentials) => {
      if (!enabled || attempt.current != null || connect.isPending) {
        return;
      }
      setState({ type: "STARTING" });
      void connect
        .mutateAsync({
          handle,
          agentId,
          toolkitType: "github",
          ...(values.name.trim() && { name: values.name }),
          ...(values.slug.trim() && { slug: values.slug }),
          description: values.description ?? null,
          prompt: values.prompt ?? null,
          config: values.config,
          ...(credentials != null && { credentials }),
          enabled: values.enabled,
          alwaysExposeTools: values.alwaysExposeTools,
        })
        .then((result) => {
          attempt.current = result.attempt_id;
          saveContext({
            handle,
            agentId,
            attemptId: result.attempt_id,
            returnPath,
            phase: "AUTHORIZING",
          });
          window.location.assign(result.authorization_url);
        })
        .catch((error: unknown) =>
          setState({
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
            attemptId: null,
          }),
        );
    },
    cancel: () => {
      const id = attempt.current;
      if (id == null) {
        clearContext();
        setState({ type: "IDLE" });
        return;
      }
      setState({ type: "CANCELLING", attemptId: id });
      void cancel
        .mutateAsync({ handle, agentId, attemptId: id })
        .then(() => {
          attempt.current = null;
          clearContext();
          setState({ type: "IDLE" });
        })
        .catch((error: unknown) => {
          attempt.current = null;
          clearContext();
          setState({
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
            attemptId: null,
          });
        });
    },
    confirm: () => {
      if (state.type !== "REVIEW") {
        return;
      }
      setState({ type: "CONFIRMING", candidate: state.candidate });
      void confirm
        .mutateAsync({ handle, agentId, attemptId: state.candidate.attempt_id })
        .then(async (result) => {
          attempt.current = null;
          clearContext();
          setState({ type: "IDLE" });
          await Promise.allSettled([
            utils.toolkit.listConfigs.invalidate(),
            utils.toolkit.listAvailableConfigs.invalidate(),
            utils.toolkit.listAgentManagement.invalidate(),
          ]);
          onComplete?.();
          router.replace(
            agentId == null
              ? `/w/${handle}/toolkits/${result.toolkit_id}/edit`
              : returnPath,
          );
        })
        .catch((error: unknown) =>
          setState({
            type: "ERROR",
            reason: githubUserErrorReason(error, "setupFailed"),
            attemptId: attempt.current,
          }),
        );
    },
  };
}
