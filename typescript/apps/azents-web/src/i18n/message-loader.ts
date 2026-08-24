import type enUSMessages from "./en-US-messages";
import type { SupportedLocale } from "@/shared/lib/locale";

type Messages = typeof enUSMessages;
type MessageLoader = () => Promise<Messages>;

const MESSAGE_LOADERS: Record<SupportedLocale, MessageLoader> = {
  "en-US": async () => (await import("./en-US-messages")).default,
  "fr-FR": async () => (await import("./fr-FR-messages")).default,
  "ja-JP": async () => (await import("./ja-JP-messages")).default,
  "ko-KR": async () => (await import("./ko-KR-messages")).default,
};

export async function loadMessages(locale: SupportedLocale): Promise<Messages> {
  return MESSAGE_LOADERS[locale]();
}
