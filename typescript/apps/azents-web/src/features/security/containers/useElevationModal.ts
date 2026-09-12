"use client";

/**
 * Elevation modal container
 *
 * Manage step-up authentication flow:
 * - Send email OTP → enter code → elevation
 * - Password input → elevation
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { synchronizeElevationState } from "../elevation-state";
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
  resetKey = 0,
): ElevationModalContainerProps {
  const [state, setState] = useState<ElevationState>({
    type: "CHOOSE_METHOD",
    methods,
  });
  const resetKeyRef = useRef(resetKey);

  // Synchronize methods while choosing and reset completed flows for a new challenge.
  useEffect(() => {
    const shouldReset = resetKeyRef.current !== resetKey;
    resetKeyRef.current = resetKey;
    setState((previous) =>
      synchronizeElevationState({
        state: previous,
        methods,
        reset: shouldReset,
      }),
    );
  }, [methods, resetKey]);

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
