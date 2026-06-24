/**
 * Locale utilities.
 *
 * Uses BCP 47 locale format: en-US, ko-KR, ja-JP, fr-FR.
 * Resolves locale without URL-based routing in this order:
 * cookie → Accept-Language → default value.
 */

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
 *
 * Returns the highest-priority supported locale from values like
 * "ko-KR,ko;q=0.9,en-US;q=0.8".
 * Also handles cases that match only the language part (for example, "ko" → "ko-KR").
 */
export function resolveLocaleFromHeader(
  acceptLanguage: string | null,
): SupportedLocale | null {
  if (!acceptLanguage) {
    return null;
  }

  // "ko-KR,ko;q=0.9,en;q=0.8" → [{lang: "ko-KR", q: 1}, {lang: "ko", q: 0.9}, ...]
  const entries = acceptLanguage
    .split(",")
    .map((part) => {
      const [lang = "", ...params] = part.trim().split(";");
      const qParam = params.find((p) => p.trim().startsWith("q="));
      const q = qParam ? parseFloat(qParam.trim().slice(2)) : 1;
      return { lang: lang.trim(), q };
    })
    .sort((a, b) => b.q - a.q);

  // language → locale mapping (language prefix match)
  const langToLocale: Record<string, SupportedLocale> = {
    en: "en-US",
    ko: "ko-KR",
    ja: "ja-JP",
    fr: "fr-FR",
  };

  for (const entry of entries) {
    // Exact locale match
    if (isSupportedLocale(entry.lang)) {
      return entry.lang;
    }

    // language prefix match (for example, "ko" → "ko-KR")
    const langPrefix = entry.lang.split("-")[0];
    if (langPrefix != null && langPrefix in langToLocale) {
      // The condition above guarantees langPrefix is one of langToLocale keys
      return langToLocale[langPrefix] as SupportedLocale;
    }
  }

  return null;
}

/** Locale language names (shown in each locale language) */
export const LOCALE_DISPLAY_NAMES: Record<SupportedLocale, string> = {
  "en-US": "English",
  "ko-KR": "Korean",
  "ja-JP": "日本語",
  "fr-FR": "Français",
};
