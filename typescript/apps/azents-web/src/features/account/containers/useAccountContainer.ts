"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { isSupportedLocale, type SupportedLocale } from "@/shared/lib/locale";
import { useLocale } from "@/shared/providers/locale";
/**
 * Account settings page container
 *
 * Fetch current user email and join date.
 */
import { trpc } from "@/trpc/client";
import type { AccountState } from "../types";

export interface AccountContainerProps {
  state: AccountState;
  onSubmit: (locale: SupportedLocale) => void;
}

export function useAccountContainer(): AccountContainerProps {
  const t = useTranslations("common");
  const { setLocale } = useLocale();
  const meQuery = trpc.user.me.useQuery(void 0, { retry: false });
  const updateMutation = trpc.user.updateMe.useMutation({
    onSuccess: (data) => {
      if (isSupportedLocale(data.locale)) {
        setLocale(data.locale);
      }
    },
  });

  const onSubmit = useCallback(
    (locale: SupportedLocale): void => {
      updateMutation.mutate({ locale });
    },
    [updateMutation],
  );

  const data = meQuery.data;

  const state: AccountState = meQuery.isLoading
    ? { type: "LOADING" }
    : meQuery.isError || !data
      ? { type: "ERROR", message: meQuery.error?.message ?? t("unknownError") }
      : {
          type: "LOADED",
          email: data.email,
          locale: data.locale,
          createdAt: new Date(data.created_at),
          localeUpdate: {
            isPending: updateMutation.isPending,
            hasError: updateMutation.isError,
          },
        };

  return { state, onSubmit };
}
