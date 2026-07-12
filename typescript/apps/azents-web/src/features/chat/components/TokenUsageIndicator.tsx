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

function percentUsed(
  totalTokens: number | null,
  thresholdTokens: number | null,
): number | null {
  if (
    totalTokens === null ||
    thresholdTokens === null ||
    thresholdTokens <= 0
  ) {
    return null;
  }
  return Math.min(100, Math.max(0, (totalTokens / thresholdTokens) * 100));
}

function progressColor(percent: number | null): string {
  if (percent === null) {
    return "var(--mantine-color-gray-5)";
  }
  if (percent >= 90) {
    return "var(--mantine-color-red-6)";
  }
  if (percent >= 70) {
    return "var(--mantine-color-yellow-6)";
  }
  return "var(--mantine-color-teal-6)";
}

function resolveUsageProfile(
  usage: TokenUsageSummary | null,
  activeRun: ChatLiveRunState | null,
): AppliedInferenceProfile | null {
  if (usage !== null && usage.inferenceProfile !== null) {
    return usage.inferenceProfile;
  }
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
  const percent = useMemo(
    () =>
      percentUsed(
        usage?.totalTokens ?? null,
        usage?.effectiveAutoCompactionThresholdTokens ?? null,
      ),
    [usage?.effectiveAutoCompactionThresholdTokens, usage?.totalTokens],
  );
  const color = progressColor(percent);
  const ringPercent = percent ?? 0;
  const ringRadius = 7;
  const ringCircumference = 2 * Math.PI * ringRadius;
  const ringDashOffset = ringCircumference * (1 - ringPercent / 100);

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
              r={ringRadius}
              fill="none"
              stroke="var(--mantine-color-default-border)"
              strokeWidth="4"
            />
            {ringPercent > 0 && (
              <circle
                cx="9"
                cy="9"
                r={ringRadius}
                fill="none"
                stroke={color}
                strokeDasharray={ringCircumference}
                strokeDashoffset={ringDashOffset}
                strokeLinecap="round"
                strokeWidth="4"
                style={{
                  transform: "rotate(-90deg)",
                  transformOrigin: "50% 50%",
                }}
              />
            )}
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
            {inferenceProfile !== null &&
              (inferenceProfile.model_display_name !== null ||
                inferenceProfile.reasoning_effort !== null) && (
                <Text size="xs" c="dimmed">
                  {[
                    inferenceProfile.model_display_name,
                    inferenceProfile.reasoning_effort,
                  ]
                    .filter((value) => value !== null)
                    .join(" · ")}
                </Text>
              )}
            {usage !== null &&
              usage.runId !== null &&
              inferenceProfile === null && (
                <Text size="xs" c="dimmed">
                  {t("unknownProvenance")}
                </Text>
              )}
          </Box>
          <UsageRow
            label={t("usedPercent")}
            value={
              percent === null ? "—" : t("percent", { value: percent / 100 })
            }
          />
          <UsageRow
            label={t("total")}
            value={formatNumber(usage?.totalTokens ?? null)}
          />
          <UsageRow
            label={t("effectiveContextWindow")}
            value={formatNumber(usage?.effectiveContextWindowTokens ?? null)}
          />
          <UsageRow
            label={t("autoCompactionThreshold")}
            value={formatNumber(
              usage?.effectiveAutoCompactionThresholdTokens ?? null,
            )}
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
