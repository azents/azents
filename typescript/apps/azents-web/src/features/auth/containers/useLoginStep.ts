"use client";

import { useHash } from "@mantine/hooks";
/**
 * Login step container
 *
 * On email submit:
 * 1. Check password setup with getLoginMethods
 * 2. If password exists → move to /login/password page
 * 3. If password absent → sendCode then move to /login/verify page
 */
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import {
  getPostLoginRedirect,
  getSafeLoginNext,
} from "@/shared/lib/login-redirect";
import { runtimeWebLoginNextWithFragment } from "@/shared/lib/runtime-web-return-target";
import { trpc } from "@/trpc/client";
import type { LoginState } from "../types";

export interface LoginStepContainerProps {
  state: LoginState;
  emailAvailable: boolean;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  onSubmit: (email: string, password: string) => void;
  onRequestSignupEmail: (email: string) => void;
}

export function useLoginStep({
  emailAvailable,
}: {
  emailAvailable: boolean;
}): LoginStepContainerProps {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [fragment] = useHash();
  const next = runtimeWebLoginNextWithFragment(
    getSafeLoginNext(searchParams.get("next")),
    fragment,
  );
  const utils = trpc.useUtils();
  const signupStatusQuery = trpc.auth.getSignupStatus.useQuery();

  /** Store email (used in mutation callback) */
  const emailRef = useRef("");
  const [checking, setChecking] = useState(false);
  const [signupEmailSent, setSignupEmailSent] = useState(false);

  const passwordLoginMutation = trpc.auth.passwordLogin.useMutation({
    onSuccess: () => {
      window.location.href = getPostLoginRedirect(next);
    },
  });

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
    : passwordLoginMutation.isPending
      ? { type: "SUBMITTING" }
      : sendCodeMutation.isPending || requestSignupEmailMutation.isPending
        ? { type: "SENDING" }
        : {
            type: "IDLE",
            error:
              passwordLoginMutation.error?.message ??
              sendCodeMutation.error?.message ??
              requestSignupEmailMutation.error?.message ??
              null,
          };

  const onSubmit = useCallback(
    (email: string, password: string) => {
      if (!emailAvailable) {
        passwordLoginMutation.mutate({ email, password });
        return;
      }
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
    [
      emailAvailable,
      passwordLoginMutation,
      utils,
      sendCodeMutation,
      next,
      router,
    ],
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
    emailAvailable,
    signupEmailAvailable:
      signupStatusQuery.data?.email_signup_available ?? false,
    signupEmailSent,
    onSubmit,
    onRequestSignupEmail,
  };
}
