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
  defaultEffort: string,
): string {
  return effort ?? defaultEffort;
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
        {effortLabel(profile.reasoning_effort, t("defaultEffort"))}
      </Text>
    </Group>
  );
}
