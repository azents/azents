/** Supported locale list */
export const SUPPORTED_LOCALES = ["en-US", "ko-KR", "ja-JP", "fr-FR"] as const;

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

/** Default locale */
export const DEFAULT_LOCALE: SupportedLocale = "en-US";

/** Cookie name */
export const LOCALE_COOKIE = "locale";

/** Check whether value is a supported locale */
export function isSupportedLocale(value: string): value is SupportedLocale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/**
 * Extract the best matching locale from Accept-Language header.
 */
export function resolveLocaleFromHeader(
  acceptLanguage: string | null,
): SupportedLocale | null {
  if (!acceptLanguage) {
    return null;
  }

  const entries = acceptLanguage
    .split(",")
    .map((part) => {
      const [lang = "", ...params] = part.trim().split(";");
      const qParam = params.find((p) => p.trim().startsWith("q="));
      const q = qParam ? parseFloat(qParam.trim().slice(2)) : 1;
      return { lang: lang.trim(), q };
    })
    .sort((a, b) => b.q - a.q);

  const langToLocale: Record<string, SupportedLocale> = {
    en: "en-US",
    fr: "fr-FR",
    ja: "ja-JP",
    ko: "ko-KR",
  };

  for (const entry of entries) {
    if (isSupportedLocale(entry.lang)) {
      return entry.lang;
    }

    const langPrefix = entry.lang.split("-")[0];
    if (langPrefix != null && langPrefix in langToLocale) {
      return langToLocale[langPrefix] as SupportedLocale;
    }
  }

  return null;
}

/** Locale language names, shown in each locale language. */
export const LOCALE_DISPLAY_NAMES: Record<SupportedLocale, string> = {
  "en-US": "English",
  "fr-FR": "Français",
  "ja-JP": "日本語",
  "ko-KR": "한국어",
};
