"use client";

import { useEffect } from "react";
import { accountLocaleToSynchronize } from "@/shared/lib/account-locale";
import { useLocale } from "@/shared/providers/locale";
import { trpc } from "@/trpc/client";

interface AccountLocaleSyncProps {
  authStatus: "authenticated" | "unauthenticated";
}

export function AccountLocaleSync({
  authStatus,
}: AccountLocaleSyncProps): null {
  const { locale, setLocale } = useLocale();
  const { data } = trpc.user.me.useQuery(void 0, {
    enabled: authStatus === "authenticated",
    retry: false,
  });
  const accountLocale = data?.locale;

  useEffect(() => {
    const localeToSynchronize = accountLocaleToSynchronize(
      locale,
      accountLocale,
    );
    if (localeToSynchronize !== null) {
      setLocale(localeToSynchronize);
    }
  }, [accountLocale, locale, setLocale]);

  return null;
}
