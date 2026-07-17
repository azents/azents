"use client";

/**
 * Context compaction in progress indicator.
 *
 * isCompacting statuswhen dotted line + Loader + text display.
 * TurnDividerand similar style use.
 */

import { Box, Group, Loader, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

/** dotted line style */
const dashedLineStyle: React.CSSProperties = {
  flex: 1,
  borderBottom: "1px dashed var(--mantine-color-default-border)",
};

export function CompactionIndicator(): React.ReactElement {
  const t = useTranslations("chat");

  return (
    <Group gap="xs" align="center" mb="md">
      <Box style={dashedLineStyle} />
      <Group gap="xs" align="center">
        <Loader size="xs" color="gray" />
        <Text size="xs" c="dimmed">
          {t("compaction.inProgress")}
        </Text>
      </Group>
      <Box style={dashedLineStyle} />
    </Group>
  );
}
