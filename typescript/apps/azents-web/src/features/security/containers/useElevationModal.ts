"use client";

/**
 * Elevation modal container
 *
 * Manage step-up authentication flow:
 * - Send email OTP → enter code → elevation
 * - Password input → elevation
 */
import { useCallback, useEffect, useState } from "react";
import { trpc } from "@/trpc/client";
import type { ElevationState } from "../types";
import type { AuthMethod } from "@azents/public-client";

export interface ElevationModalContainerProps {
  state: ElevationState;
  onSelectEmail: () => void;
  onSelectPassword: () => void;
  onSubmitEmailCode: (code: string) => void;
  onSubmitPassword: (password: string) => void;
  onResendCode: () => void;
}

export function useElevationModal(
  methods: AuthMethod[],
  onElevated: () => void,
): ElevationModalContainerProps {
  const [state, setState] = useState<ElevationState>({
    type: "CHOOSE_METHOD",
    methods,
  });

  // Synchronize CHOOSE_METHOD state when methods prop updates asynchronously
  useEffect(() => {
    setState((prev) => {
      if (prev.type === "CHOOSE_METHOD") {
        return { type: "CHOOSE_METHOD", methods };
      }
      return prev;
    });
  }, [methods]);

  const sendCodeMutation = trpc.security.sendElevationCode.useMutation();
  const elevateEmailMutation = trpc.security.elevateWithEmail.useMutation();
  const elevatePasswordMutation =
    trpc.security.elevateWithPassword.useMutation();

  const onSelectEmail = useCallback(() => {
    setState({ type: "EMAIL_SENDING" });
    sendCodeMutation.mutate(void 0, {
      onSuccess: (data) => {
        setState({
          type: "EMAIL_CODE",
          csrfToken: data.csrf_token,
          sentAt: Date.now(),
          error: null,
        });
      },
      onError: (err) => {
        setState({ type: "CHOOSE_METHOD", methods });
        console.error("Failed to send elevation code:", err.message);
      },
    });
  }, [sendCodeMutation, methods]);

  const onSubmitEmailCode = useCallback(
    (code: string) => {
      if (state.type !== "EMAIL_CODE") {
        return;
      }
      const { csrfToken, sentAt } = state;
      setState({ type: "EMAIL_VERIFYING", csrfToken, sentAt });
      elevateEmailMutation.mutate(
        { code, csrfToken },
        {
          onSuccess: () => onElevated(),
          onError: (err) =>
            setState({
              type: "EMAIL_CODE",
              csrfToken,
              sentAt,
              error: err.message,
            }),
        },
      );
    },
    [state, elevateEmailMutation, onElevated],
  );

  const onSubmitPassword = useCallback(
    (password: string) => {
      setState({ type: "PASSWORD_VERIFYING" });
      elevatePasswordMutation.mutate(
        { password },
        {
          onSuccess: () => onElevated(),
          onError: (err) =>
            setState({ type: "PASSWORD_INPUT", error: err.message }),
        },
      );
    },
    [elevatePasswordMutation, onElevated],
  );

  const onSelectPassword = useCallback(() => {
    setState({ type: "PASSWORD_INPUT", error: null });
  }, []);

  const onResendCode = useCallback(() => {
    setState({ type: "EMAIL_SENDING" });
    sendCodeMutation.mutate(void 0, {
      onSuccess: (data) => {
        setState({
          type: "EMAIL_CODE",
          csrfToken: data.csrf_token,
          sentAt: Date.now(),
          error: null,
        });
      },
      onError: () => {
        setState({ type: "CHOOSE_METHOD", methods });
      },
    });
  }, [sendCodeMutation, methods]);

  return {
    state,
    onSelectEmail,
    onSelectPassword,
    onSubmitEmailCode,
    onSubmitPassword,
    onResendCode,
  };
}
