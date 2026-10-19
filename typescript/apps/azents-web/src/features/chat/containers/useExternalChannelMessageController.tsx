"use client";
import { useDisclosure } from "@mantine/hooks";
import { useLocale, useTranslations } from "next-intl";
import type { ExternalChannelMessagePresentation } from "../externalChannelMessage";
interface ExternalChannelMessageProps {
  source: ExternalChannelMessagePresentation;
  partial?: boolean;
  actions?: React.ReactNode;
}

export interface ExternalChannelMessageViewProps {
  source: ExternalChannelMessageProps["source"];
  partial: boolean;
  actions: ExternalChannelMessageProps["actions"];
  t: ReturnType<typeof useTranslations<"chat">>;
  locale: string;
  opened: boolean;
  toggle: () => void;
  detailsOpened: boolean;
  details: ReturnType<typeof useDisclosure>[1];
  sourceLabel: string;
}
export function useExternalChannelMessageController({
  source,
  partial = false,
  actions = null,
}: ExternalChannelMessageProps): ExternalChannelMessageViewProps {
  const t = useTranslations("chat");
  const locale = useLocale();
  const [opened, { toggle }] = useDisclosure(false);
  const [detailsOpened, details] = useDisclosure(false);
  const sourceLabel = `${source.senderDisplayName} · ${source.resourceLabel}`;
  return {
    source,
    partial,
    actions,
    t,
    locale,
    opened,
    toggle,
    detailsOpened,
    details,
    sourceLabel,
  };
}
