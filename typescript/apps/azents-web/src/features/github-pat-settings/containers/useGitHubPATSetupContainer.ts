"use client";

/**
 * GitHub PAT settings page container hook.
 *
 * Handles settings status fetch and PAT register/delete mutations.
 */

import { useCallback, useMemo, useState } from "react";

import { trpc } from "@/trpc/client";

import type { SetupPageState } from "../types";

export interface GitHubPATSetupContainerProps {
  handle: string;
}

export interface GitHubPATSetupContainerOutput {
  state: SetupPageState;
  registerError: string | null;
  isRegistering: boolean;
  onRegister: (token: string) => void;
}

export function useGitHubPATSetupContainer(
  props: GitHubPATSetupContainerProps,
): GitHubPATSetupContainerOutput {
  const { handle } = props;

  const utils = trpc.useUtils();
  const [successUsername, setSuccessUsername] = useState<string | null>(null);

  // Fetch settings status
  const setupQuery = trpc.githubPat.getSetupStatus.useQuery({
    handle,
  });

  // PAT registration mutation
  const registerMutation = trpc.githubPat.register.useMutation({
    onSuccess: (data) => {
      setSuccessUsername(data.github_username);
      void utils.githubPat.getStatus.invalidate({ handle });
      void utils.githubPat.getSetupStatus.invalidate({ handle });
    },
  });

  const state: SetupPageState = useMemo(() => {
    // On registration success
    if (successUsername) {
      return { type: "DONE", githubUsername: successUsername };
    }

    if (setupQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (setupQuery.isError) {
      return { type: "ERROR", message: setupQuery.error.message };
    }

    const data = setupQuery.data;
    if (!data) {
      return { type: "LOADING" };
    }

    // PAT already registered
    if (data.pat_registered && data.github_username) {
      return { type: "DONE", githubUsername: data.github_username };
    }

    // PAT registration form
    return { type: "PAT_FORM" };
  }, [
    setupQuery.isLoading,
    setupQuery.isError,
    setupQuery.data,
    setupQuery.error,
    successUsername,
  ]);

  const onRegister = useCallback(
    (token: string): void => {
      registerMutation.mutate({ handle, token });
    },
    [handle, registerMutation],
  );

  return {
    state,
    registerError: registerMutation.error?.message ?? null,
    isRegistering: registerMutation.isPending,
    onRegister,
  };
}
