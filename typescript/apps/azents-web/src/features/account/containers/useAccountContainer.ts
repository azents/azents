"use client";

import { useTranslations } from "next-intl";
/**
 * Account settings page container
 *
 * Fetch current user email and join date.
 */
import { trpc } from "@/trpc/client";
import type { AccountState } from "../types";

export interface AccountContainerProps {
  state: AccountState;
}

export function useAccountContainer(): AccountContainerProps {
  const t = useTranslations("common");
  const meQuery = trpc.user.me.useQuery(void 0, { retry: false });

  const data = meQuery.data;

  const state: AccountState = meQuery.isLoading
    ? { type: "LOADING" }
    : meQuery.isError || !data
      ? { type: "ERROR", message: meQuery.error?.message ?? t("unknownError") }
      : {
          type: "LOADED",
          email: data.email,
          createdAt: new Date(data.created_at),
        };

  return { state };
}
