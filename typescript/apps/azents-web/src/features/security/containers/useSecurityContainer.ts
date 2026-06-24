"use client";

/**
 * Security page main container
 *
 * Fetch auth methods. Switch to elevation-required state on 403.
 */
import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type { PasswordManageState, SecurityState } from "../types";

export interface SecurityContainerProps {
  state: SecurityState;
  passwordState: PasswordManageState;
  passwordResetKey: number;
  onSetPassword: (password: string) => void;
  onElevated: () => void;
}

export function useSecurityContainer(): SecurityContainerProps {
  const utils = trpc.useUtils();
  const [passwordState, setPasswordState] = useState<PasswordManageState>({
    type: "IDLE",
    error: null,
  });
  const [passwordResetKey, setPasswordResetKey] = useState(0);

  const authMethodsQuery = trpc.security.getAuthMethods.useQuery(void 0, {
    retry: false,
  });

  /** Fetch auth methods available for elevation (no elevation required) */
  const needsElevation = authMethodsQuery.error?.data?.code === "FORBIDDEN";
  const elevationMethodsQuery = trpc.security.getElevationMethods.useQuery(
    void 0,
    { enabled: needsElevation },
  );

  const setPasswordMutation = trpc.security.setPassword.useMutation({
    onMutate: () => setPasswordState({ type: "SAVING" }),
    onSuccess: () => {
      setPasswordState({ type: "IDLE", error: null });
      setPasswordResetKey((k) => k + 1);
      void utils.security.getAuthMethods.invalidate();
    },
    onError: (err) => setPasswordState({ type: "IDLE", error: err.message }),
  });

  const data = authMethodsQuery.data;
  const error = authMethodsQuery.error;

  const state: SecurityState = authMethodsQuery.isLoading
    ? { type: "LOADING" }
    : error?.data?.code === "FORBIDDEN"
      ? {
          type: "ELEVATION_REQUIRED",
          elevationMethods: elevationMethodsQuery.data?.methods ?? null,
        }
      : error
        ? { type: "ERROR", message: error.message }
        : data
          ? {
              type: "LOADED",
              methods: data.methods,
              hasPassword: data.methods.some(
                (m) => m.type === "password" && m.enabled,
              ),
            }
          : { type: "LOADING" };

  const onSetPassword = useCallback(
    (password: string) => {
      setPasswordMutation.mutate({ password });
    },
    [setPasswordMutation],
  );

  const onElevated = useCallback(() => {
    void utils.security.getAuthMethods.invalidate();
  }, [utils]);

  return {
    state,
    passwordState,
    passwordResetKey,
    onSetPassword,
    onElevated,
  };
}
