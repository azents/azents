"use client";

/**
 * Verification code validation container
 *
 * Manage all state with URL query params (refresh-safe):
 * - email: email address
 * - sentAt: code sent time (for timer calculation)
 * - state: csrfToken (obfuscated name)
 *
 * On verification success, redirect to next query param (default: /workspaces).
 * On resend, update sentAt + state query params.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";
import { trpc } from "@/trpc/client";
import type { VerifyState } from "../types";

export interface VerifyStepContainerProps {
  state: VerifyState;
  isResending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}

export function useVerifyStep(): VerifyStepContainerProps {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const email = searchParams.get("email") ?? "";
  const sentAt = parseInt(searchParams.get("sentAt") ?? "0", 10) || 0;
  const csrfToken = searchParams.get("state") ?? "";
  const next = searchParams.get("next");

  /** Redirect target after authentication (default: /workspaces) */
  const redirectUrl = next || "/workspaces";

  /** Redirect to first step when required data is missing */
  useEffect(() => {
    if (!email || !csrfToken) {
      router.replace("/login");
    }
  }, [email, csrfToken, router]);

  const verifyMutation = trpc.auth.verify.useMutation({
    onSuccess: () => {
      // hard navigation re-renders server layout (refresh authStatus)
      window.location.href = redirectUrl;
    },
  });

  /** Resend-only mutation (tracks loading state separately) */
  const resendMutation = trpc.auth.sendCode.useMutation({
    onSuccess: (data) => {
      // Update sentAt + state(csrfToken) query params -> reset timer
      const newSentAt = Date.now();
      const params = new URLSearchParams(searchParams.toString());
      params.set("sentAt", String(newSentAt));
      params.set("state", data.csrf_token);
      router.replace(`${pathname}?${params.toString()}`);
    },
  });

  // Keep VERIFYING state after success until navigation completes (prevents error flash on IDLE transition)
  const state: VerifyState =
    verifyMutation.isPending || verifyMutation.isSuccess
      ? { type: "VERIFYING", email, sentAt }
      : {
          type: "IDLE",
          email,
          sentAt,
          error: verifyMutation.error?.message ?? null,
        };

  const onSubmit = useCallback(
    (code: string) => {
      if (!email || !csrfToken) {
        return;
      }
      verifyMutation.mutate({ email, code, csrfToken });
    },
    [verifyMutation, email, csrfToken],
  );

  const onResend = useCallback(() => {
    if (email) {
      resendMutation.mutate({ email });
    }
  }, [resendMutation, email]);

  return { state, isResending: resendMutation.isPending, onSubmit, onResend };
}
