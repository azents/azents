/** Supported locale list */
export const SUPPORTED_LOCALES = ["en-US", "ko-KR", "ja-JP", "fr-FR"] as const;

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

/** Default locale */
export const DEFAULT_LOCALE: SupportedLocale = "en-US";

/** Cookie name */
export const LOCALE_COOKIE = "locale";

const LANG_TO_LOCALE: ReadonlyMap<string, SupportedLocale> = new Map([
  ["en", "en-US"],
  ["fr", "fr-FR"],
  ["ja", "ja-JP"],
  ["ko", "ko-KR"],
]);

interface LocalePreference {
  lang: string;
  q: number;
}

function parseLocalePreference(part: string): LocalePreference | null {
  const [lang = "", ...params] = part.trim().split(";");
  const qParam = params.find((param) => param.trim().startsWith("q="));
  const normalizedLang = lang.trim();
  const qValue = qParam?.trim().slice(2);
  const q = qValue ? Number(qValue) : qParam ? Number.NaN : 1;

  if (!normalizedLang || !Number.isFinite(q) || q < 0 || q > 1) {
    return null;
  }

  return { lang: normalizedLang, q };
}

/** Check whether value is a supported locale */
export function isSupportedLocale(value: string): value is SupportedLocale {
  return SUPPORTED_LOCALES.some((locale) => locale === value);
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
    .map(parseLocalePreference)
    .filter((entry): entry is LocalePreference => entry !== null)
    .sort((a, b) => b.q - a.q);

  for (const entry of entries) {
    if (isSupportedLocale(entry.lang)) {
      return entry.lang;
    }

    const langPrefix = entry.lang.split("-")[0];
    if (langPrefix) {
      const locale = LANG_TO_LOCALE.get(langPrefix);
      if (locale) {
        return locale;
      }
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
