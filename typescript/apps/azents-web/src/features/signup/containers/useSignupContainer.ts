"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { SignupPageProps, SignupState } from "../types";

export interface SignupContainerProps {
  state: SignupState;
  onSubmit: (email: string, password: string) => void;
}

export function useSignupContainer({
  token,
}: SignupPageProps): SignupContainerProps {
  const router = useRouter();
  const t = useTranslations("auth.signup");
  const previewQuery = trpc.auth.previewSignupToken.useQuery(
    { token },
    { enabled: token.length > 0 },
  );
  const redeemMutation = trpc.auth.redeemSignupToken.useMutation({
    onSuccess: () => {
      router.replace("/workspaces");
      router.refresh();
    },
  });

  const emailHint = previewQuery.data?.email ?? null;
  const state: SignupState = previewQuery.isLoading
    ? { type: "LOADING" }
    : previewQuery.isError
      ? { type: "ERROR", message: t("previewError") }
      : !token || !previewQuery.data?.valid || !emailHint
        ? { type: "INVALID", message: t("invalidDescription") }
        : redeemMutation.isSuccess
          ? { type: "SUCCESS" }
          : {
              type: "READY",
              emailHint,
              error: redeemMutation.error?.message ?? null,
              submitting: redeemMutation.isPending,
            };

  const onSubmit = useCallback(
    (email: string, password: string) => {
      redeemMutation.mutate({ token, email, password });
    },
    [redeemMutation, token],
  );

  return { state, onSubmit };
}
