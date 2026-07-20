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
import {
  groupToolActivityPhases,
  toolCallPresentation,
} from "../toolPresentationRegistry";
import { MarkdownContent } from "./MarkdownContent";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ToolCallCard } from "./ToolCallCard";
import type {
  ToolActivityCall,
  ToolActivityGroup as ToolActivityGroupModel,
} from "../toolActivityPresentation";
import type {
  ToolActivityPhase,
  ToolActivityPhaseKind,
} from "../toolPresentationRegistry";
import type { ReactNode } from "react";

interface ToolActivityGroupProps {
  activity: ToolActivityGroupModel;
  authorizationAction?: ReactNode;
  dimmed?: boolean;
}

interface ActivityStatusCounts {
  failed: number;
  running: number;
}

interface ToolActivityPhaseRowProps {
  phase: ToolActivityPhase;
  label: string;
  callCountLabel: string;
  expandLabel: string;
  collapseLabel: string;
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

function ToolActivityPhaseRow({
  phase,
  label,
  callCountLabel,
  expandLabel,
  collapseLabel,
}: ToolActivityPhaseRowProps): React.ReactElement {
  const [opened, { toggle }] = useDisclosure(false);

  return (
    <Box>
      <UnstyledButton
        w="100%"
        py="sm"
        px={rem(2)}
        onClick={toggle}
        aria-expanded={opened}
        aria-label={`${opened ? collapseLabel : expandLabel}: ${label}`}
      >
        <Group justify="space-between" gap="sm" wrap="nowrap">
          <Box miw={0}>
            <Text size="sm" fw={550}>
              {label}
            </Text>
            <Text size="xs" c="dimmed">
              {callCountLabel}
            </Text>
          </Box>
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
      </UnstyledButton>
      <Collapse expanded={opened}>
        <Stack gap="xs">
          {phase.calls.map((call) => {
            const presentation = toolCallPresentation(call);
            const hiddenAttachmentUris = presentation.deliverables.map(
              (attachment) => attachment.uri,
            );
            return call.type === "client" ? (
              <ToolCallCard
                key={`${call.type}:${call.toolCall.id}`}
                toolCall={call.toolCall}
                hiddenAttachmentUris={hiddenAttachmentUris}
              />
            ) : (
              <ProviderToolCallCard
                key={`${call.type}:${call.toolCall.id}`}
                toolCall={call.toolCall}
                hiddenAttachmentUris={hiddenAttachmentUris}
              />
            );
          })}
        </Stack>
      </Collapse>
    </Box>
  );
}

export function ToolActivityGroup({
  activity,
  authorizationAction,
  dimmed = false,
}: ToolActivityGroupProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const [opened, { toggle }] = useDisclosure(false);
  const counts = activityStatusCounts(activity.calls);
  const phases = groupToolActivityPhases(activity.calls);
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
  if (authorizationAction) {
    summaryParts.push(t("approvalNeeded"));
  }

  function phaseLabel(kind: ToolActivityPhaseKind): string {
    switch (kind) {
      case "inspection":
        return t("phaseInspection");
      case "execution":
        return t("phaseExecution");
      case "changes":
        return t("phaseChanges");
      case "generation":
        return t("phaseGeneration");
      case "generic":
        return t("genericPhase");
    }
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
        <Group gap="sm" wrap="nowrap" py="sm">
          <UnstyledButton
            flex={1}
            miw={0}
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
          {authorizationAction}
        </Group>

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
            {phases.map((phase, index) => (
              <Box key={phase.id}>
                {index > 0 ? <Divider /> : null}
                <ToolActivityPhaseRow
                  phase={phase}
                  label={phaseLabel(phase.kind)}
                  callCountLabel={t("callCount", {
                    count: phase.calls.length,
                  })}
                  expandLabel={t("expandPhase")}
                  collapseLabel={t("collapsePhase")}
                />
              </Box>
            ))}
          </Stack>
        </Collapse>
      </Paper>
    </Box>
  );
}
