import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  LOCALE_COOKIE,
  resolveLocaleFromHeader,
  type SupportedLocale,
} from "@/shared/lib/locale";
import enMessages from "../../messages/en-US.json";
import frMessages from "../../messages/fr-FR.json";
import jaMessages from "../../messages/ja-JP.json";
import koMessages from "../../messages/ko-KR.json";

const messagesByLocale: Record<SupportedLocale, typeof enMessages> = {
  "en-US": enMessages,
  "fr-FR": frMessages,
  "ja-JP": jaMessages,
  "ko-KR": koMessages,
};

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;

  if (cookieLocale && isSupportedLocale(cookieLocale)) {
    return {
      locale: cookieLocale,
      messages: messagesByLocale[cookieLocale],
    };
  }

  const headerStore = await headers();
  const headerLocale = resolveLocaleFromHeader(
    headerStore.get("accept-language"),
  );

  if (headerLocale) {
    return {
      locale: headerLocale,
      messages: messagesByLocale[headerLocale],
    };
  }

  return {
    locale: DEFAULT_LOCALE,
    messages: messagesByLocale[DEFAULT_LOCALE],
  };
});
