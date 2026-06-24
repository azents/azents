"use client";

import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  CreatedSignupTokenState,
  SignupTokenCreateState,
  SignupTokenListState,
} from "../types";

export interface SignupTokensPageContentProps {
  state: SignupTokenListState;
  createState: SignupTokenCreateState;
  createdToken: CreatedSignupTokenState | null;
  onCreateToken: (email: string) => void;
  onCopyCreatedToken: () => void;
  onRevokeToken: (tokenId: string) => void;
  onClearCreatedToken: () => void;
}

export function useSignupTokensPageContainer(): SignupTokensPageContentProps {
  const utils = trpc.useUtils();
  const [createState, setCreateState] = useState<SignupTokenCreateState>({
    type: "IDLE",
    error: null,
  });
  const [createdToken, setCreatedToken] =
    useState<CreatedSignupTokenState | null>(null);

  const listQuery = trpc.signupToken.list.useQuery();
  const createMutation = trpc.signupToken.create.useMutation({
    onMutate: () => setCreateState({ type: "CREATING" }),
    onSuccess: (data) => {
      setCreateState({ type: "IDLE", error: null });
      setCreatedToken({
        email: data.token.email,
        signupUrl: data.signupUrl,
        copied: false,
      });
      void utils.signupToken.list.invalidate();
    },
    onError: (error) => {
      setCreateState({ type: "IDLE", error: error.message });
    },
  });
  const revokeMutation = trpc.signupToken.revoke.useMutation({
    onSuccess: () => {
      void utils.signupToken.list.invalidate();
    },
  });

  const state: SignupTokenListState = listQuery.isLoading
    ? { type: "LOADING" }
    : listQuery.isError
      ? { type: "ERROR", message: listQuery.error.message }
      : { type: "LOADED", tokens: listQuery.data?.items ?? [] };

  const handleCreateToken = useCallback(
    (email: string): void => {
      createMutation.mutate({ email });
    },
    [createMutation],
  );

  const handleCopyCreatedToken = useCallback((): void => {
    if (!createdToken) {
      return;
    }
    void navigator.clipboard.writeText(createdToken.signupUrl);
    setCreatedToken({ ...createdToken, copied: true });
  }, [createdToken]);

  const handleRevokeToken = useCallback(
    (tokenId: string): void => {
      revokeMutation.mutate({ tokenId });
    },
    [revokeMutation],
  );

  const handleClearCreatedToken = useCallback((): void => {
    setCreatedToken(null);
  }, []);

  return {
    state,
    createState,
    createdToken,
    onCreateToken: handleCreateToken,
    onCopyCreatedToken: handleCopyCreatedToken,
    onRevokeToken: handleRevokeToken,
    onClearCreatedToken: handleClearCreatedToken,
  };
}
