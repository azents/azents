"use client";

/** Chat header token usage with the active turn's applied inference profile. */

import {
  ActionIcon,
  Box,
  Group,
  Popover,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { memo, useMemo, useState } from "react";
import type { ChatLiveRunState, TokenUsageSummary } from "../types";
import type { AppliedInferenceProfile } from "@azents/public-client";

interface TokenUsageIndicatorProps {
  usage: TokenUsageSummary | null;
  activeRun: ChatLiveRunState | null;
}

function formatNumber(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

function resolveUsageProfile(
  usage: TokenUsageSummary | null,
  activeRun: ChatLiveRunState | null,
): AppliedInferenceProfile | null {
  const runId = usage?.runId ?? null;
  if (runId === null || activeRun?.run_id !== runId) {
    return null;
  }
  return activeRun.inferenceProfile;
}

export const TokenUsageIndicator = memo(function TokenUsageIndicator({
  usage,
  activeRun,
}: TokenUsageIndicatorProps): React.ReactElement {
  const t = useTranslations("chat.tokenUsage");
  const [opened, setOpened] = useState(false);
  const inferenceProfile = useMemo(
    () => resolveUsageProfile(usage, activeRun),
    [activeRun, usage],
  );

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      withArrow
      shadow="md"
      width={rem(280)}
    >
      <Popover.Target>
        <ActionIcon
          aria-label={t("ariaLabel")}
          onClick={() => setOpened((current) => !current)}
          radius="xl"
          variant="subtle"
        >
          <Box
            component="svg"
            viewBox="0 0 18 18"
            aria-hidden="true"
            style={{
              display: "block",
              height: rem(18),
              width: rem(18),
            }}
          >
            <circle
              cx="9"
              cy="9"
              r="7"
              fill="none"
              stroke="var(--mantine-color-default-border)"
              strokeWidth="4"
            />
          </Box>
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Box>
            <Text fw={600} size="sm">
              {t("title")}
            </Text>
            <Text size="xs" c="dimmed">
              {inferenceProfile?.model_target_label ?? t("unknownModel")}
            </Text>
            {usage !== null &&
              usage.runId !== null &&
              inferenceProfile === null && (
                <Text size="xs" c="dimmed">
                  {t("unknownProvenance")}
                </Text>
              )}
          </Box>
          <UsageRow
            label={t("total")}
            value={formatNumber(usage?.totalTokens ?? null)}
          />
          <UsageRow
            label={t("prompt")}
            value={formatNumber(usage?.promptTokens ?? null)}
          />
          <UsageRow
            label={t("completion")}
            value={formatNumber(usage?.completionTokens ?? null)}
          />
          <UsageRow
            label={t("cached")}
            value={formatNumber(usage?.cachedTokens ?? null)}
          />
          <UsageRow
            label={t("cacheCreation")}
            value={formatNumber(usage?.cacheCreationTokens ?? null)}
          />
          <UsageRow
            label={t("reasoning")}
            value={formatNumber(usage?.reasoningTokens ?? null)}
          />
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
});

function UsageRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Group justify="space-between" gap="md" wrap="nowrap">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xs" fw={600} ta="right">
        {value}
      </Text>
    </Group>
  );
}
