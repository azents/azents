"use client";

/** Context-window usage details for the active turn's applied inference profile. */

import { Box, Group, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { memo, useMemo } from "react";
import type { ChatLiveRunState, TokenUsageSummary } from "../types";
import type { AppliedInferenceProfile } from "@azents/public-client";

interface TokenUsageDetailsProps {
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

export const TokenUsageDetails = memo(function TokenUsageDetails({
  usage,
  activeRun,
}: TokenUsageDetailsProps): React.ReactElement {
  const t = useTranslations("chat.tokenUsage");
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

  return (
    <Stack aria-label={t("title")} gap="xs" role="region">
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
        value={percent === null ? "—" : t("percent", { value: percent / 100 })}
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
