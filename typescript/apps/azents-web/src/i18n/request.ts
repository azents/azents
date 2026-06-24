/**
 * next-intl server settings.
 *
 * Resolves locale without URL-based routing in this order:
 * cookie → Accept-Language → default value.
 */
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  LOCALE_COOKIE,
  resolveLocaleFromHeader,
} from "@/shared/lib/locale";

export default getRequestConfig(async () => {
  // 1. Read locale from Cookie
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;

  if (cookieLocale && isSupportedLocale(cookieLocale)) {
    return {
      locale: cookieLocale,
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
      messages: (await import(`../../messages/${cookieLocale}.json`)).default,
    };
  }

  // 2. Extract locale from Accept-Language header
  const headerStore = await headers();
  const acceptLanguage = headerStore.get("accept-language");
  const headerLocale = resolveLocaleFromHeader(acceptLanguage);

  if (headerLocale) {
    return {
      locale: headerLocale,
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
      messages: (await import(`../../messages/${headerLocale}.json`)).default,
    };
  }

  // 3. Default value
  return {
    locale: DEFAULT_LOCALE,
    // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
    messages: (await import(`../../messages/${DEFAULT_LOCALE}.json`)).default,
  };
});
