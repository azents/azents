"use client";

import { Box, Group, List, rem, Stack, Text } from "@mantine/core";
import { useFormatter, useTranslations } from "next-intl";
import type {
  RoutineJudgmentMessage,
  RoutineJudgmentView,
} from "@azents/session-core/routinePresentation";

export function RoutineJudgmentDisclosure({
  judgment,
}: {
  judgment: RoutineJudgmentMessage | null;
}): React.ReactElement {
  const t = useTranslations("routines");
  const formatter = useFormatter();
  const observation: RoutineJudgmentView = judgment?.observation ?? {
    type: "UNAVAILABLE",
  };
  return (
    <Box component="details" mb="md" style={{ minWidth: 0 }}>
      <Box component="summary" style={{ cursor: "pointer" }}>
        <Text component="span" size="xs" c="dimmed">
          {t("judgment.label")}
        </Text>
      </Box>
      <Stack
        gap="sm"
        mt="sm"
        pl="md"
        maw={rem(720)}
        style={{ minWidth: 0, overflowWrap: "anywhere" }}
      >
        {observation.type === "UNAVAILABLE" ? (
          <Text size="sm" c="dimmed">
            {t("judgment.unavailable")}
          </Text>
        ) : (
          <>
            <Text size="sm" fw={500}>
              {t(`judgment.states.${observation.status}`)}
            </Text>
            {observation.error !== null && (
              <Text size="sm" c="red" style={{ whiteSpace: "pre-wrap" }}>
                {observation.error}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              {t("judgment.considered")}
            </Text>
            <List size="sm" spacing="xs">
              {observation.items.map((item) => (
                <List.Item key={item.routineId}>
                  <Text size="sm" fw={500}>
                    {item.title}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {item.slug}
                  </Text>
                  <Text size="sm">
                    {item.act === null
                      ? t("judgment.noDecision")
                      : item.act
                        ? t("judgment.selected")
                        : t("judgment.noAction")}
                  </Text>
                </List.Item>
              ))}
            </List>
            <Group gap="xs" align="flex-start">
              <Text size="xs" c="dimmed">
                {t("judgment.model")}
              </Text>
              <Text size="xs">
                {judgment?.provider ?? t("judgment.unknown")} ·{" "}
                {judgment?.model ?? t("judgment.unknown")}
              </Text>
            </Group>
            {observation.callUsage === null ? (
              <Text size="xs" c="dimmed">
                {t("judgment.usageUnavailable")}
              </Text>
            ) : (
              <Stack gap="xs">
                <Text size="xs" c="dimmed">
                  {t("judgment.callUsage")}
                </Text>
                <Text size="xs">
                  {t("judgment.tokens", {
                    total: formatter.number(observation.callUsage.totalTokens),
                    prompt: formatter.number(
                      observation.callUsage.promptTokens,
                    ),
                    completion: formatter.number(
                      observation.callUsage.completionTokens,
                    ),
                  })}
                </Text>
                {observation.callUsage.cachedTokens !== null && (
                  <Text size="xs">
                    {t("judgment.cached")}:{" "}
                    {formatter.number(observation.callUsage.cachedTokens)}
                  </Text>
                )}
                {observation.callUsage.cacheCreationTokens !== null && (
                  <Text size="xs">
                    {t("judgment.cacheCreated")}:{" "}
                    {formatter.number(
                      observation.callUsage.cacheCreationTokens,
                    )}
                  </Text>
                )}
                {observation.callUsage.reasoningTokens !== null && (
                  <Text size="xs">
                    {t("judgment.reasoning")}:{" "}
                    {formatter.number(observation.callUsage.reasoningTokens)}
                  </Text>
                )}
                {observation.callUsage.costUsd !== null && (
                  <Text size="xs">
                    {t("judgment.cost")}:{" "}
                    {formatter.number(observation.callUsage.costUsd, {
                      style: "currency",
                      currency: "USD",
                      maximumFractionDigits: 6,
                    })}
                  </Text>
                )}
                <Text size="xs" c="dimmed">
                  {t("judgment.separateUsage")}
                </Text>
              </Stack>
            )}
          </>
        )}
      </Stack>
    </Box>
  );
}
