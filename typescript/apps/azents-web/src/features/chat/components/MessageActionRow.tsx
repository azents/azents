"use client";

import { Group, rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import { ChatCopyButton } from "./ChatCopyButton";
import classes from "./MessageActionRow.module.css";
import { MessageMetadataFooter } from "./MessageMetadataFooter";
import type {
  AppliedInferenceProfile,
  RequestedInferenceProfile,
} from "@azents/public-client";

export type MessageActionAlign = "assistant" | "user";

interface MessageActionRowProps {
  content: string | null;
  createdAt: string;
  align: MessageActionAlign;
  inferenceProfile?: RequestedInferenceProfile | AppliedInferenceProfile | null;
  additionalActions?: React.ReactNode;
}

export function MessageActionRow({
  content,
  createdAt,
  align,
  inferenceProfile = null,
  additionalActions = null,
}: MessageActionRowProps): React.ReactElement {
  const t = useTranslations("chat");
  const actionRowClassName =
    align === "assistant"
      ? `${classes.actionRow} ${classes.actionRowAssistant}`
      : `${classes.actionRow} ${classes.actionRowUser}`;

  return (
    <Group
      gap={rem(4)}
      mt={rem(4)}
      wrap="nowrap"
      className={actionRowClassName}
    >
      {align === "user" && (
        <MessageMetadataFooter
          createdAt={createdAt}
          profile={inferenceProfile}
        />
      )}
      {content !== null && (
        <ChatCopyButton
          value={content}
          copyLabel={t("copy")}
          copiedLabel={t("copied")}
          position={align === "user" ? "left" : "right"}
        />
      )}
      {additionalActions}
      {align === "assistant" && <MessageMetadataFooter createdAt={createdAt} />}
    </Group>
  );
}
