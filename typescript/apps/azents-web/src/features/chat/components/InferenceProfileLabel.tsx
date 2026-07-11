"use client";

import { Group, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import type {
  ModelReasoningEffort,
  RequestedInferenceProfile,
} from "@azents/public-client";

interface InferenceProfileLabelProps {
  profile: RequestedInferenceProfile | null;
}

function effortLabel(
  effort: ModelReasoningEffort | null,
  labels: {
    defaultEffort: string;
    none: string;
    minimal: string;
    low: string;
    medium: string;
    high: string;
    xhigh: string;
    max: string;
  },
): string {
  switch (effort) {
    case null:
      return labels.defaultEffort;
    case "none":
      return labels.none;
    case "minimal":
      return labels.minimal;
    case "low":
      return labels.low;
    case "medium":
      return labels.medium;
    case "high":
      return labels.high;
    case "xhigh":
      return labels.xhigh;
    case "max":
      return labels.max;
  }
}

export function InferenceProfileLabel({
  profile,
}: InferenceProfileLabelProps): React.ReactElement | null {
  const t = useTranslations("chat.inferenceProvenance");
  if (profile === null) {
    return null;
  }

  return (
    <Group gap="2xs" wrap="nowrap">
      <Text size="xs" c="dimmed" fw={500}>
        {profile.model_target_label}
      </Text>
      <Text size="xs" c="dimmed" aria-hidden="true">
        ·
      </Text>
      <Text size="xs" c="dimmed">
        {effortLabel(profile.reasoning_effort, {
          defaultEffort: t("defaultEffort"),
          none: t("effortNone"),
          minimal: t("effortMinimal"),
          low: t("effortLow"),
          medium: t("effortMedium"),
          high: t("effortHigh"),
          xhigh: t("effortXhigh"),
          max: t("effortMax"),
        })}
      </Text>
    </Group>
  );
}
