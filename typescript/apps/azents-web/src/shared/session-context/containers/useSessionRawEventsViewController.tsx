"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useLocale } from "@/shared/providers/locale";
import type { SessionContextResponse } from "@azents/public-client";
interface SessionRawEventsViewProps {
  context: SessionContextResponse;
}

export interface SessionRawEventsViewViewProps {
  context: SessionRawEventsViewProps["context"];
  t: ReturnType<typeof useTranslations<"chat.context">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  openedEventId: string | null;
  setOpenedEventId: React.Dispatch<React.SetStateAction<string | null>>;
}
export function useSessionRawEventsViewController({
  context,
}: SessionRawEventsViewProps): SessionRawEventsViewViewProps {
  const t = useTranslations("chat.context");
  const { locale } = useLocale();
  const [openedEventId, setOpenedEventId] = useState<string | null>(null);
  return { context, t, locale, openedEventId, setOpenedEventId };
}
