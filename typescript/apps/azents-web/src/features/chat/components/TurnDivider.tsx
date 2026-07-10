"use client";

/**
 * turn/run boundary control.
 *
 * turn_complete  token usageonly display as collapsible.
 * Divider  does not render.
 */

import { Box, Group, rem, Stack, Text, UnstyledButton } from "@mantine/core";
import { IconChartArcs3, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { memo, useState } from "react";
import inlineControlClasses from "./ChatInlineControl.module.css";

interface TurnDividerProps {
  usage?: Record<string, unknown> | null;
}

/** usage in number field safely extract. */
function getNum(usage: Record<string, unknown>, key: string): number | null {
  const v = usage[key];
  return typeof v === "number" ? v : null;
}

/** number text unit separator format with convert.. */
function formatNumber(n: number): string {
  return n.toLocaleString();
}

export const TurnDivider = memo(function TurnDivider({
  usage,
}: TurnDividerProps): React.ReactElement | null {
  const t = useTranslations("chat");
  const [opened, setOpened] = useState(false);

  const totalTokens = usage ? getNum(usage, "total_tokens") : null;
  const promptTokens = usage ? getNum(usage, "prompt_tokens") : null;
  const completionTokens = usage ? getNum(usage, "completion_tokens") : null;
  const cachedTokens = usage ? getNum(usage, "cached_tokens") : null;
  const cacheCreationTokens = usage
    ? getNum(usage, "cache_creation_tokens")
    : null;
  const reasoningTokens = usage ? getNum(usage, "reasoning_tokens") : null;

  if (totalTokens == null) {
    return null;
  }

  return (
    <Box mt="xs" mb="sm">
      <Group gap="xs" align="center">
        <UnstyledButton
          className={inlineControlClasses.root}
          onClick={() => setOpened((current) => !current)}
          style={{
            color: "var(--mantine-color-dimmed)",
            display: "inline-flex",
            gap: rem(6),
          }}
        >
          <IconChevronRight
            size={rem(14)}
            style={{
              transform: opened ? "rotate(90deg)" : "rotate(0deg)",
              transition: "transform 120ms ease",
            }}
          />
          <IconChartArcs3 aria-hidden="true" size={rem(14)} stroke={1.8} />
          <Text size="xs" c="dimmed" className={inlineControlClasses.label}>
            {t("turnUsage.tokens", { count: formatNumber(totalTokens) })}
          </Text>
        </UnstyledButton>
      </Group>

      {opened && (
        <Stack gap={rem(4)} mt="xs" maw={rem(220)}>
          {promptTokens != null && (
            <UsageRow label={t("turnUsage.prompt")} value={promptTokens} />
          )}
          {completionTokens != null && (
            <UsageRow
              label={t("turnUsage.completion")}
              value={completionTokens}
            />
          )}
          {cachedTokens != null && cachedTokens > 0 && (
            <UsageRow label={t("turnUsage.cached")} value={cachedTokens} />
          )}
          {cacheCreationTokens != null && cacheCreationTokens > 0 && (
            <UsageRow
              label={t("turnUsage.cacheCreation")}
              value={cacheCreationTokens}
            />
          )}
          {reasoningTokens != null && reasoningTokens > 0 && (
            <UsageRow
              label={t("turnUsage.reasoning")}
              value={reasoningTokens}
            />
          )}
          <UsageRow label={t("turnUsage.total")} value={totalTokens} bold />
        </Stack>
      )}
    </Box>
  );
});

/** token usage row. */
function UsageRow({
  label,
  value,
  bold,
}: {
  label: string;
  value: number;
  bold?: boolean;
}): React.ReactElement {
  return (
    <Group justify="space-between" gap="xs">
      <Text size="xs" c="dimmed" {...(bold ? { fw: 600 } : {})}>
        {label}
      </Text>
      <Text size="xs" c="dimmed" {...(bold ? { fw: 600 } : {})}>
        {formatNumber(value)}
      </Text>
    </Group>
  );
}
