/**
 * next-intl server settings.
 *
 * Resolves locale without URL-based routing in this order:
 * account preference → cookie → Accept-Language → default value.
 */
import { userV1Me } from "@azents/public-client";
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { loadMessages } from "@/i18n/message-loader";
import { getAccessToken, isTokenExpiringSoon } from "@/shared/lib/cookies";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  LOCALE_COOKIE,
  resolveLocaleFromHeader,
} from "@/shared/lib/locale";
import { createApiClientWithAccessToken } from "@/trpc/context";
import type { SupportedLocale } from "@/shared/lib/locale";

async function resolveAccountLocale(): Promise<SupportedLocale | null> {
  const accessToken = await getAccessToken();
  if (accessToken === null || isTokenExpiringSoon(accessToken.expiresAt)) {
    return null;
  }

  try {
    const { data } = await userV1Me({
      client: createApiClientWithAccessToken(accessToken.token, {
        cache: "no-store",
      }),
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
      messages: await loadMessages(accountLocale),
    };
  }

  // 2. Read locale from Cookie.
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;

  if (cookieLocale && isSupportedLocale(cookieLocale)) {
    return {
      locale: cookieLocale,
      messages: await loadMessages(cookieLocale),
    };
  }

  // 3. Extract locale from Accept-Language header.
  const headerStore = await headers();
  const acceptLanguage = headerStore.get("accept-language");
  const headerLocale = resolveLocaleFromHeader(acceptLanguage);

  if (headerLocale) {
    return {
      locale: headerLocale,
      messages: await loadMessages(headerLocale),
    };
  }

  // 4. Default value.
  return {
    locale: DEFAULT_LOCALE,
    messages: await loadMessages(DEFAULT_LOCALE),
  };
});
