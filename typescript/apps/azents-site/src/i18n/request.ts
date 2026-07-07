import { getRequestConfig } from "next-intl/server";
import { DEFAULT_LOCALE } from "@/shared/lib/locale";
import { getMessagesForLocale } from "./messages";

export default getRequestConfig(() => ({
  locale: DEFAULT_LOCALE,
  messages: getMessagesForLocale(DEFAULT_LOCALE),
}));
