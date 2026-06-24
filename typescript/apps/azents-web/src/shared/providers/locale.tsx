"use client";

/**
 * Locale context.
 *
 * When locale is switched on client, stores it in cookie and refreshes page.
 * In SSR, i18n/request.ts resolves locale in this order:
 * cookie → Accept-Language → default value.
 */
import { createContext, type ReactNode, useContext, useMemo } from "react";
import { LOCALE_COOKIE, type SupportedLocale } from "@/shared/lib/locale";

interface LocaleContextType {
  /** Current locale */
  locale: SupportedLocale;
  /** Change locale (save cookie + refresh page) */
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

function setCookie(name: string, value: string, days: number = 365): void {
  if (typeof document === "undefined") {
    return;
  }
  const expires = new Date(
    Date.now() + days * 24 * 60 * 60 * 1000,
  ).toUTCString();
  document.cookie = `${name}=${value}; expires=${expires}; path=/; SameSite=Lax`;
}

export function LocaleProvider({
  children,
  locale,
}: LocaleProviderProps): ReactNode {
  const value = useMemo(
    () => ({
      locale,
      setLocale: (newLocale: SupportedLocale) => {
        setCookie(LOCALE_COOKIE, newLocale);
        // Refresh page to apply new locale in SSR
        window.location.reload();
      },
    }),
    [locale],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}
