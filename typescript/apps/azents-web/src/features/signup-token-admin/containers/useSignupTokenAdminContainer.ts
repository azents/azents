"use client";

import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  CreatedSignupTokenState,
  SignupTokenAdminState,
  SignupTokenCreateState,
} from "../types";

export interface SignupTokenAdminContainerProps {
  state: SignupTokenAdminState;
  createState: SignupTokenCreateState;
  createdToken: CreatedSignupTokenState | null;
  onCreateManualToken: (email: string) => void;
  onRevokeToken: (tokenId: string) => void;
  onClearCreatedToken: () => void;
}

function buildSignupUrl(plaintextToken: string): string {
  const path = `/signup?token=${encodeURIComponent(plaintextToken)}`;
  if (typeof window === "undefined") {
    return path;
  }
  return `${window.location.origin}${path}`;
}

export function useSignupTokenAdminContainer(): SignupTokenAdminContainerProps {
  const utils = trpc.useUtils();
  const [createState, setCreateState] = useState<SignupTokenCreateState>({
    type: "IDLE",
    error: null,
  });
  const [createdToken, setCreatedToken] =
    useState<CreatedSignupTokenState | null>(null);

  const listQuery = trpc.signupTokenAdmin.list.useQuery();
  const createMutation = trpc.signupTokenAdmin.create.useMutation({
    onMutate: () => setCreateState({ type: "CREATING" }),
    onSuccess: (data) => {
      setCreateState({ type: "IDLE", error: null });
      setCreatedToken({
        email: data.token.email,
        signupUrl: buildSignupUrl(data.plaintext_token),
      });
      void utils.signupTokenAdmin.list.invalidate();
    },
    onError: (error) => {
      setCreateState({ type: "IDLE", error: error.message });
    },
  });
  const revokeMutation = trpc.signupTokenAdmin.revoke.useMutation({
    onSuccess: () => {
      void utils.signupTokenAdmin.list.invalidate();
    },
  });

  const state: SignupTokenAdminState = listQuery.isLoading
    ? { type: "LOADING" }
    : listQuery.isError
      ? { type: "ERROR", message: listQuery.error.message }
      : { type: "LOADED", tokens: listQuery.data?.items ?? [] };

  const onCreateManualToken = useCallback(
    (email: string) => {
      createMutation.mutate({ email, deliveryMethod: "manual" });
    },
    [createMutation],
  );

  const onRevokeToken = useCallback(
    (tokenId: string) => {
      revokeMutation.mutate({ tokenId });
    },
    [revokeMutation],
  );

  const onClearCreatedToken = useCallback(() => {
    setCreatedToken(null);
  }, []);

  return {
    state,
    createState,
    createdToken,
    onCreateManualToken,
    onRevokeToken,
    onClearCreatedToken,
  };
}
