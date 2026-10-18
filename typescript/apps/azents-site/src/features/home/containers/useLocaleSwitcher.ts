"use client";
import { trackLocaleChange } from "@/shared/lib/analytics";
import { useLocale } from "@/shared/providers/locale";
import type { SupportedLocale } from "@/shared/lib/locale";
export interface LocaleSwitcherViewProps {
  locale: SupportedLocale;
  onSelect: (locale: SupportedLocale) => void;
}
export function useLocaleSwitcher(): LocaleSwitcherViewProps {
  const { locale, setLocale } = useLocale();
  return {
    locale,
    onSelect: (next) => {
      if (next !== locale) {
        trackLocaleChange({ fromLocale: locale, toLocale: next });
      }
      setLocale(next);
    },
  };
}
