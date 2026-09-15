import { isSupportedLocale, type SupportedLocale } from "./locale.ts";

export function isAccessTokenUsableForAccountLocale(
  expiresAt: number,
  now: number = Date.now(),
): boolean {
  return expiresAt > now;
}

export function accountLocaleToSynchronize(
  renderedLocale: SupportedLocale,
  accountLocale?: string | null,
): SupportedLocale | null {
  if (
    !accountLocale ||
    !isSupportedLocale(accountLocale) ||
    accountLocale === renderedLocale
  ) {
    return null;
  }
  return accountLocale;
}
