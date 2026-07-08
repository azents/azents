"use client";

import { createContext, type ReactNode, useContext, useMemo } from "react";
import { type SupportedLocale } from "@/shared/lib/locale";

interface LocaleContextType {
  locale: SupportedLocale;
  setLocale: (locale: SupportedLocale) => void;
}

const LocaleContext = createContext<LocaleContextType>({
  locale: "en-US",
  setLocale: () => {},
});

export const useLocale = (): LocaleContextType => useContext(LocaleContext);

interface LocaleProviderProps {
  children: ReactNode;
  locale: SupportedLocale;
}

function getLocaleHref(locale: SupportedLocale): string {
  if (typeof window === "undefined") {
    return `/${locale}/`;
  }

  return `/${locale}/${window.location.hash}`;
}

export function LocaleProvider({
  children,
  locale,
}: LocaleProviderProps): ReactNode {
  const value = useMemo(
    () => ({
      locale,
      setLocale: (newLocale: SupportedLocale) => {
        window.location.href = getLocaleHref(newLocale);
      },
    }),
    [locale],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}
