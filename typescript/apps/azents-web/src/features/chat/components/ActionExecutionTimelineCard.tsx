"use client";

import {
  Badge,
  Button,
  Code,
  Group,
  Paper,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { IconAlertCircle, IconCheck, IconLoader2 } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ActionExecutionProjection } from "../types";
import type { ReactNode } from "react";

interface ActionExecutionTimelineCardProps {
  actionExecution: ActionExecutionProjection;
  onRetry: (actionExecutionId: string) => void;
  onDiscard: (actionExecutionId: string) => void;
}

function statusColor(status: string): string {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "failed_final":
      return "gray";
    case "running":
      return "blue";
    default:
      return "yellow";
  }
}

function statusIcon(status: string): ReactNode {
  switch (status) {
    case "completed":
      return <IconCheck size="0.85rem" />;
    case "failed":
    case "failed_final":
      return <IconAlertCircle size="0.85rem" />;
    default:
      return <IconLoader2 size="0.85rem" />;
  }
}

function eventLabel(kind: string, stepKey?: string | null): string {
  return stepKey ? `${kind} · ${stepKey}` : kind;
}

function statusLabel(
  status: string,
  t: ReturnType<typeof useTranslations<"chat.actionExecution">>,
): string {
  switch (status) {
    case "completed":
      return t("status.completed");
    case "failed":
      return t("status.failed");
    case "failed_final":
      return t("status.failed_final");
    case "running":
      return t("status.running");
    default:
      return t("status.pending");
  }
}

function exitCodeLabel(exitCode?: number | null): string | null {
  return typeof exitCode === "number" ? `exit ${exitCode}` : null;
}

export function ActionExecutionTimelineCard({
  actionExecution,
  onRetry,
  onDiscard,
}: ActionExecutionTimelineCardProps): React.ReactElement {
  const t = useTranslations("chat.actionExecution");
  const { execution, events } = actionExecution;
  const failed = execution.status === "failed";
  const visibleEvents = events.slice(-4);

  return (
    <Paper withBorder radius="sm" px="sm" py={rem(6)} my={rem(4)}>
      <Stack gap={rem(4)}>
        <Group justify="space-between" align="center" gap="xs" wrap="nowrap">
          <Group gap="xs" miw={0} wrap="nowrap">
            <Text size="sm" fw={600} truncate>
              {t("title")}
            </Text>
            <Badge
              size="sm"
              color={statusColor(execution.status)}
              variant="light"
              leftSection={statusIcon(execution.status)}
            >
              {statusLabel(execution.status, t)}
            </Badge>
            <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
              {t("attempt", { attempt: execution.attempt })}
            </Text>
          </Group>
          {failed && (
            <Group gap={rem(4)} wrap="nowrap">
              <Button
                size="compact-xs"
                variant="light"
                onClick={() => onRetry(execution.id)}
              >
                {t("retry")}
              </Button>
              <Button
                size="compact-xs"
                color="gray"
                variant="subtle"
                onClick={() => onDiscard(execution.id)}
              >
                {t("discard")}
              </Button>
            </Group>
          )}
        </Group>

        {execution.failure_summary && (
          <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap" }}>
            {execution.failure_summary}
          </Text>
        )}

        {visibleEvents.length > 0 && (
          <Stack gap={rem(3)}>
            {visibleEvents.map((event) => {
              const exitCode = exitCodeLabel(event.exit_code);
              return (
                <Stack key={event.id} gap={rem(2)}>
                  <Group gap={rem(4)} wrap="nowrap" align="baseline">
                    <Text size="xs" c="dimmed" fw={500} truncate>
                      {eventLabel(event.kind, event.step_key)}
                    </Text>
                    {exitCode !== null && (
                      <Text size="xs" c="dimmed">
                        {exitCode}
                      </Text>
                    )}
                  </Group>
                  {event.command_argv && event.command_argv.length > 0 && (
                    <Code block fz="xs" px="xs" py={rem(3)}>
                      {event.command_argv.join(" ")}
                    </Code>
                  )}
                  {event.content && (
                    <Text
                      size="xs"
                      c="dimmed"
                      style={{ whiteSpace: "pre-wrap" }}
                    >
                      {event.content}
                    </Text>
                  )}
                </Stack>
              );
            })}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
