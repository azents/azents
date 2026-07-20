"use client";

import {
  Box,
  Collapse,
  Divider,
  Group,
  Loader,
  Paper,
  rem,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconAlertCircle,
  IconChevronRight,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { MarkdownContent } from "./MarkdownContent";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ToolCallCard } from "./ToolCallCard";
import type {
  ToolActivityCall,
  ToolActivityGroup as ToolActivityGroupModel,
} from "../toolActivityPresentation";

interface ToolActivityGroupProps {
  activity: ToolActivityGroupModel;
  dimmed?: boolean;
}

interface ActivityStatusCounts {
  failed: number;
  running: number;
}

function activityStatusCounts(calls: ToolActivityCall[]): ActivityStatusCounts {
  let failed = 0;
  let running = 0;

  for (const call of calls) {
    if (call.toolCall.status === "failed") {
      failed += 1;
    }
    if (
      call.toolCall.status === "running" ||
      (call.type === "client" && call.toolCall.status === "preparing")
    ) {
      running += 1;
    }
  }

  return { failed, running };
}

export function ToolActivityGroup({
  activity,
  dimmed = false,
}: ToolActivityGroupProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const [opened, { toggle }] = useDisclosure(false);
  const [phaseOpened, { toggle: togglePhase }] = useDisclosure(false);
  const counts = activityStatusCounts(activity.calls);
  const summaryParts = [
    t("turnCount", { count: activity.turnCount }),
    t("callCount", { count: activity.calls.length }),
  ];

  if (counts.failed > 0) {
    summaryParts.push(t("failedCount", { count: counts.failed }));
  }
  if (counts.running > 0) {
    summaryParts.push(t("runningCount", { count: counts.running }));
  }

  return (
    <Box mb="md" opacity={dimmed ? 0.45 : 1} style={{ minWidth: 0 }}>
      <Paper
        withBorder
        radius="md"
        px="sm"
        bg="var(--mantine-color-body)"
        data-tool-activity-id={activity.id}
      >
        <UnstyledButton
          w="100%"
          py="sm"
          onClick={toggle}
          aria-expanded={opened}
          aria-label={opened ? t("collapseActivity") : t("expandActivity")}
        >
          <Group justify="space-between" gap="sm" wrap="nowrap">
            <Group gap="sm" wrap="nowrap" miw={0}>
              <ThemeIcon size={rem(22)} variant="transparent" color="gray">
                <IconTool size={rem(15)} />
              </ThemeIcon>
              <Box miw={0}>
                <Text size="sm" fw={550} lh={1.3}>
                  {t("title")}
                </Text>
                <Text size="xs" c="dimmed" lh={1.45} truncate>
                  {summaryParts.join(" · ")}
                </Text>
              </Box>
            </Group>
            <Group gap="xs" wrap="nowrap">
              {counts.failed > 0 ? (
                <IconAlertCircle
                  aria-label={t("failedCount", { count: counts.failed })}
                  size={rem(15)}
                  color="var(--mantine-color-dimmed)"
                />
              ) : null}
              {counts.running > 0 ? (
                <Loader
                  size={rem(14)}
                  color="gray"
                  aria-label={t("runningCount", { count: counts.running })}
                />
              ) : null}
              <IconChevronRight
                aria-hidden="true"
                size={rem(15)}
                color="var(--mantine-color-dimmed)"
                style={{
                  transform: opened ? "rotate(90deg)" : "none",
                  transition: "transform 120ms ease",
                }}
              />
            </Group>
          </Group>
        </UnstyledButton>

        <Collapse expanded={opened}>
          <Divider />
          <Stack gap={0} pb="sm">
            {activity.reasoningSummaries.length > 0 ? (
              <Box py="sm" px={rem(2)}>
                <Text size="xs" fw={600} c="dimmed" mb="xs">
                  {t("reasoning", {
                    count: activity.reasoningSummaries.length,
                  })}
                </Text>
                <Stack gap="xs">
                  {activity.reasoningSummaries.map((summary, index) => (
                    <Box
                      key={`${activity.id}:reasoning:${index}`}
                      c="dimmed"
                      style={{ overflowWrap: "anywhere" }}
                    >
                      <MarkdownContent>{summary}</MarkdownContent>
                    </Box>
                  ))}
                </Stack>
              </Box>
            ) : null}
            {activity.compactionCount > 0 ? (
              <Text size="xs" c="dimmed" py="xs" px={rem(2)}>
                {t("compactionCount", { count: activity.compactionCount })}
              </Text>
            ) : null}
            <UnstyledButton
              w="100%"
              py="sm"
              px={rem(2)}
              onClick={togglePhase}
              aria-expanded={phaseOpened}
              aria-label={phaseOpened ? t("collapsePhase") : t("expandPhase")}
            >
              <Group justify="space-between" gap="sm" wrap="nowrap">
                <Box miw={0}>
                  <Text size="sm" fw={550}>
                    {t("genericPhase")}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t("callCount", { count: activity.calls.length })}
                  </Text>
                </Box>
                <IconChevronRight
                  aria-hidden="true"
                  size={rem(15)}
                  color="var(--mantine-color-dimmed)"
                  style={{
                    transform: phaseOpened ? "rotate(90deg)" : "none",
                    transition: "transform 120ms ease",
                  }}
                />
              </Group>
            </UnstyledButton>
            <Collapse expanded={phaseOpened}>
              <Stack gap="xs">
                {activity.calls.map((call) =>
                  call.type === "client" ? (
                    <ToolCallCard
                      key={`${call.type}:${call.toolCall.id}`}
                      toolCall={call.toolCall}
                    />
                  ) : (
                    <ProviderToolCallCard
                      key={`${call.type}:${call.toolCall.id}`}
                      toolCall={call.toolCall}
                    />
                  ),
                )}
              </Stack>
            </Collapse>
          </Stack>
        </Collapse>
      </Paper>
    </Box>
  );
}
