import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  type SupportedLocale,
} from "@/shared/lib/locale";
import enMessages from "../../messages/en-US.json";
import frMessages from "../../messages/fr-FR.json";
import jaMessages from "../../messages/ja-JP.json";
import koMessages from "../../messages/ko-KR.json";

export type SiteMessages = typeof enMessages;

export const MESSAGES_BY_LOCALE: Record<SupportedLocale, SiteMessages> = {
  "en-US": enMessages,
  "fr-FR": frMessages,
  "ja-JP": jaMessages,
  "ko-KR": koMessages,
};

export function resolveSupportedLocale(value: string): SupportedLocale {
  return isSupportedLocale(value) ? value : DEFAULT_LOCALE;
}

export function getMessagesForLocale(locale: SupportedLocale): SiteMessages {
  return MESSAGES_BY_LOCALE[locale];
}
