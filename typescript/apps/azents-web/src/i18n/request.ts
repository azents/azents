/**
 * next-intl server settings.
 *
 * Resolves locale without URL-based routing in this order:
 * account preference → cookie → Accept-Language → default value.
 */
import { userV1Me } from "@azents/public-client";
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { getAccessToken, isTokenExpiringSoon } from "@/shared/lib/cookies";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  LOCALE_COOKIE,
  resolveLocaleFromHeader,
} from "@/shared/lib/locale";
import { createApiClientWithAccessToken } from "@/trpc/context";

async function resolveAccountLocale(): Promise<string | null> {
  const accessToken = await getAccessToken();
  if (accessToken === null || isTokenExpiringSoon(accessToken.expiresAt)) {
    return null;
  }

  try {
    const { data } = await userV1Me({
      client: createApiClientWithAccessToken(accessToken.token),
      throwOnError: true,
    });
    return isSupportedLocale(data.locale) ? data.locale : null;
  } catch {
    return null;
  }
}

export default getRequestConfig(async () => {
  // 1. Read account locale for authenticated requests.
  const accountLocale = await resolveAccountLocale();
  if (accountLocale) {
    return {
      locale: accountLocale,
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
      messages: (await import(`../../messages/${accountLocale}.json`)).default,
    };
  }

  // 2. Read locale from Cookie.
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;

  if (cookieLocale && isSupportedLocale(cookieLocale)) {
    return {
      locale: cookieLocale,
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
      messages: (await import(`../../messages/${cookieLocale}.json`)).default,
    };
  }

  // 3. Extract locale from Accept-Language header.
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

  // 4. Default value.
  return {
    locale: DEFAULT_LOCALE,
    // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access -- next-intl dynamic import
    messages: (await import(`../../messages/${DEFAULT_LOCALE}.json`)).default,
  };
});
