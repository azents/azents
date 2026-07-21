import type { SupportedLocale } from "./locale";

export function formatLocalizedDate(
  value: Date,
  locale: SupportedLocale,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat(locale, options).format(value);
}
