"use client";

/**
 * Login step: Email input container
 *
 * On email submit:
 * 1. Check password setup with getLoginMethods
 * 2. If password exists → move to /login/password page
 * 3. If password absent → sendCode then move to /login/verify page
 */
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { LoginState } from "../types";

export interface LoginStepContainerProps {
  state: LoginState;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  onSubmit: (email: string) => void;
  onRequestSignupEmail: (email: string) => void;
}

export function useLoginStep(): LoginStepContainerProps {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next");
  const utils = trpc.useUtils();
  const signupStatusQuery = trpc.auth.getSignupStatus.useQuery();

  /** Store email (used in mutation callback) */
  const emailRef = useRef("");
  const [checking, setChecking] = useState(false);
  const [signupEmailSent, setSignupEmailSent] = useState(false);

  const requestSignupEmailMutation = trpc.auth.requestSignupEmail.useMutation({
    onSuccess: () => {
      setSignupEmailSent(true);
    },
  });

  const sendCodeMutation = trpc.auth.sendCode.useMutation({
    onSuccess: (data) => {
      const sentAt = Date.now();
      const params = new URLSearchParams({
        email: emailRef.current,
        sentAt: String(sentAt),
        state: data.csrf_token,
      });
      if (next) {
        params.set("next", next);
      }
      router.push(`/login/verify?${params.toString()}`);
    },
  });

  const state: LoginState = checking
    ? { type: "CHECKING_METHODS" }
    : sendCodeMutation.isPending || requestSignupEmailMutation.isPending
      ? { type: "SENDING" }
      : {
          type: "IDLE",
          error:
            sendCodeMutation.error?.message ??
            requestSignupEmailMutation.error?.message ??
            null,
        };

  const onSubmit = useCallback(
    (email: string) => {
      emailRef.current = email;

      void (async () => {
        try {
          setChecking(true);
          const methods = await utils.auth.getLoginMethods.fetch({ email });
          if (methods.has_password) {
            const params = new URLSearchParams({ email });
            if (next) {
              params.set("next", next);
            }
            router.push(`/login/password?${params.toString()}`);
            return;
          }
        } catch {
          // Fallback to default email OTP flow when login method fetch fails
        } finally {
          setChecking(false);
        }

        sendCodeMutation.mutate({ email });
      })();
    },
    [utils, sendCodeMutation, next, router],
  );

  const onRequestSignupEmail = useCallback(
    (email: string) => {
      setSignupEmailSent(false);
      requestSignupEmailMutation.mutate({ email });
    },
    [requestSignupEmailMutation],
  );

  return {
    state,
    signupEmailAvailable:
      signupStatusQuery.data?.email_signup_available ?? false,
    signupEmailSent,
    onSubmit,
    onRequestSignupEmail,
  };
}
