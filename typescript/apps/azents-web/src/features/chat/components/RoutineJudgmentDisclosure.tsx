"use client";

import { Box, Group, rem, Stack, Text, Tooltip } from "@mantine/core";
import {
  IconRepeat,
  IconSquare,
  IconSquareCheck,
  IconSquareMinus,
} from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { ActivityRow } from "./ActivityRow";
import { activityRowIconSize } from "./activityRowPresentation";
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
    <ActivityRow
      primary={t("judgment.label")}
      ariaLabel={t("judgment.label")}
      icon={<IconRepeat aria-hidden="true" size={activityRowIconSize} />}
      detail={
        <Stack
          gap="xs"
          maw={rem(720)}
          style={{ minWidth: 0, overflowWrap: "anywhere" }}
        >
          {observation.type === "UNAVAILABLE" ? (
            <Text size="xs" c="dimmed">
              {t("judgment.unavailable")}
            </Text>
          ) : (
            <>
              <Text size="xs" c="dimmed">
                {t(`judgment.states.${observation.status}`)}
              </Text>
              {observation.error !== null && (
                <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap" }}>
                  {observation.error}
                </Text>
              )}
              <Stack
                gap={rem(6)}
                role="list"
                aria-label={t("judgment.considered")}
              >
                {observation.items.map((item) => {
                  const label =
                    item.act === null
                      ? t("judgment.noDecision")
                      : item.act
                        ? t("judgment.selected")
                        : t("judgment.noAction");
                  const StatusIcon =
                    item.act === null
                      ? IconSquareMinus
                      : item.act
                        ? IconSquareCheck
                        : IconSquare;
                  return (
                    <Group
                      key={item.routineId}
                      role="listitem"
                      gap="xs"
                      align="flex-start"
                      wrap="nowrap"
                    >
                      <Tooltip label={label}>
                        <Box
                          role="img"
                          aria-label={label}
                          c="dimmed"
                          style={{
                            display: "flex",
                            flexShrink: 0,
                            marginTop: rem(2),
                          }}
                        >
                          <StatusIcon
                            aria-hidden="true"
                            size={activityRowIconSize}
                          />
                        </Box>
                      </Tooltip>
                      <Box miw={0}>
                        <Text size="sm" lh={1.35}>
                          {item.title}
                        </Text>
                        <Text size="xs" c="dimmed" lh={1.35}>
                          {item.slug}
                        </Text>
                      </Box>
                    </Group>
                  );
                })}
              </Stack>
              <Stack gap={rem(4)}>
                <Text size="xs" c="dimmed">
                  {judgment?.provider ?? t("judgment.unknown")} ·{" "}
                  {judgment?.model ?? t("judgment.unknown")}
                </Text>
                {observation.callUsage === null ? (
                  <Text size="xs" c="dimmed">
                    {t("judgment.usageUnavailable")}
                  </Text>
                ) : (
                  <>
                    <Text size="xs" c="dimmed">
                      {t("judgment.tokens", {
                        total: formatter.number(
                          observation.callUsage.totalTokens,
                        ),
                        prompt: formatter.number(
                          observation.callUsage.promptTokens,
                        ),
                        completion: formatter.number(
                          observation.callUsage.completionTokens,
                        ),
                      })}
                    </Text>
                    <Group gap="xs" c="dimmed">
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
                          {formatter.number(
                            observation.callUsage.reasoningTokens,
                          )}
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
                    </Group>
                  </>
                )}
              </Stack>
            </>
          )}
        </Stack>
      }
    />
  );
}
