"use client";

import { Badge, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import type { AgentResponse } from "@azents/public-client";

interface AgentDeletionStatusProps {
  status: AgentResponse["deletion_status"];
}

export function AgentDeletionBadge({
  status,
}: AgentDeletionStatusProps): React.ReactElement | null {
  const t = useTranslations("workspace.agents.deletion");
  if (status === null) {
    return null;
  }
  return (
    <Badge color={status === "deletion_error" ? "red" : "yellow"} size="sm">
      {status === "deletion_error" ? t("error") : t("deleting")}
    </Badge>
  );
}

export function AgentDeletionNotice({
  status,
}: AgentDeletionStatusProps): React.ReactElement | null {
  const t = useTranslations("workspace.agents.deletion");
  if (status === null) {
    return null;
  }
  return (
    <Text size="sm" c="dimmed" px="md" pb="sm" role="status">
      {status === "deletion_error" ? t("errorNotice") : t("notice")}
    </Text>
  );
}
