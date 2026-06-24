"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { PasswordResetState } from "../types";

export interface PasswordResetContainerProps {
  state: PasswordResetState;
  password: string;
  onPasswordChange: (password: string) => void;
  onSubmit: () => void;
}

export function usePasswordResetContainer(
  token: string,
): PasswordResetContainerProps {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const previewQuery = trpc.auth.previewPasswordResetToken.useQuery(
    { token },
    { enabled: token.length > 0, retry: false },
  );
  const redeemMutation = trpc.auth.redeemPasswordResetToken.useMutation({
    onError: (err) => setError(err.message),
  });

  const state: PasswordResetState = useMemo(() => {
    if (redeemMutation.isSuccess) {
      return { type: "SUCCESS" };
    }
    if (error) {
      return { type: "ERROR", message: error };
    }
    if (previewQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (previewQuery.error) {
      return { type: "ERROR", message: previewQuery.error.message };
    }
    const preview = previewQuery.data;
    if (!preview || !preview.valid) {
      return { type: "INVALID" };
    }
    if (redeemMutation.isPending) {
      return { type: "SAVING", preview };
    }
    return { type: "READY", preview };
  }, [
    error,
    previewQuery.data,
    previewQuery.error,
    previewQuery.isLoading,
    redeemMutation.isPending,
    redeemMutation.isSuccess,
  ]);

  const onPasswordChange = useCallback((nextPassword: string): void => {
    setPassword(nextPassword);
    setError(null);
  }, []);

  const onSubmit = useCallback((): void => {
    setError(null);
    redeemMutation.mutate({ token, password });
  }, [password, redeemMutation, token]);

  return {
    state,
    password,
    onPasswordChange,
    onSubmit,
  };
}
