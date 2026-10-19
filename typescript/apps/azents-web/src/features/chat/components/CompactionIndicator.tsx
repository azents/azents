"use client";

import { Box, Group, Loader, rem, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { ChatTimelineItem } from "./ChatTimelineItem";

const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: `${rem(1)} dashed var(--mantine-color-default-border)`,
};

export function CompactionIndicator(): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <ChatTimelineItem kind="boundary">
      <Group gap="xs" align="center" role="status">
        <Box style={dashedLineStyle} />
        <Group gap="xs" align="center">
          <Loader size="xs" color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed">
            {t("compaction.inProgress")}
          </Text>
        </Group>
        <Box style={dashedLineStyle} />
      </Group>
    </ChatTimelineItem>
  );
}
