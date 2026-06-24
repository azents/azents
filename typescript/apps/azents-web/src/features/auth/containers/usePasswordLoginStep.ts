"use client";

/**
 * Password login step container
 *
 * Submit password → login → set cookies → redirect.
 * "Sign in another way" → switch to email OTP flow.
 */
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { PasswordLoginState } from "../types";

export interface PasswordLoginStepContainerProps {
  state: PasswordLoginState;
  onSubmit: (password: string) => void;
  onUseOtherMethod: () => void;
}

export function usePasswordLoginStep(): PasswordLoginStepContainerProps {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams.get("email") ?? "";
  const next = searchParams.get("next");

  const passwordLoginMutation = trpc.auth.passwordLogin.useMutation({
    onSuccess: () => {
      // hard navigation re-renders server layout (refresh authStatus)
      window.location.href = next ?? "/workspaces";
    },
  });

  const sendCodeMutation = trpc.auth.sendCode.useMutation({
    onSuccess: (data) => {
      const sentAt = Date.now();
      const params = new URLSearchParams({
        email,
        sentAt: String(sentAt),
        state: data.csrf_token,
      });
      if (next) {
        params.set("next", next);
      }
      router.push(`/login/verify?${params.toString()}`);
    },
  });

  const state: PasswordLoginState = passwordLoginMutation.isPending
    ? { type: "SUBMITTING", email }
    : {
        type: "IDLE",
        email,
        error: passwordLoginMutation.error?.message ?? null,
      };

  const onSubmit = useCallback(
    (password: string) => {
      passwordLoginMutation.mutate({ email, password });
    },
    [passwordLoginMutation, email],
  );

  const onUseOtherMethod = useCallback(() => {
    sendCodeMutation.mutate({ email });
  }, [sendCodeMutation, email]);

  return { state, onSubmit, onUseOtherMethod };
}
