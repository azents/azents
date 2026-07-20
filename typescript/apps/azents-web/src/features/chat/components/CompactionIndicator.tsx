"use client";

import { Box, Group, Loader, rem, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: `${rem(1)} dashed var(--mantine-color-default-border)`,
};

export function CompactionIndicator(): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <Group gap="xs" align="center" mb="md" role="status">
      <Box style={dashedLineStyle} />
      <Group gap="xs" align="center">
        <Loader size="xs" color="var(--mantine-color-dimmed)" />
        <Text size="xs" c="dimmed">
          {t("compaction.inProgress")}
        </Text>
      </Group>
      <Box style={dashedLineStyle} />
    </Group>
  );
}
