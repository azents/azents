"use client";

import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  Stack,
  Text,
  Timeline,
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

export function ActionExecutionTimelineCard({
  actionExecution,
  onRetry,
  onDiscard,
}: ActionExecutionTimelineCardProps): React.ReactElement {
  const t = useTranslations("chat.actionExecution");
  const { execution, events } = actionExecution;
  const failed = execution.status === "failed";
  const visibleEvents = events.slice(-8);

  return (
    <Card withBorder radius="md" p="md" my="sm">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" gap="sm">
          <Stack gap={2}>
            <Group gap="xs">
              <Text fw={600}>{t("title")}</Text>
              <Badge
                color={statusColor(execution.status)}
                variant="light"
                leftSection={statusIcon(execution.status)}
              >
                {statusLabel(execution.status, t)}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed">
              {t("attempt", { attempt: execution.attempt })}
            </Text>
          </Stack>
          {failed && (
            <Group gap="xs">
              <Button
                size="xs"
                variant="light"
                onClick={() => onRetry(execution.id)}
              >
                {t("retry")}
              </Button>
              <Button
                size="xs"
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
          <Text size="sm" c="red">
            {execution.failure_summary}
          </Text>
        )}

        {visibleEvents.length > 0 && (
          <Timeline
            active={visibleEvents.length - 1}
            bulletSize={18}
            lineWidth={1}
          >
            {visibleEvents.map((event) => (
              <Timeline.Item
                key={event.id}
                title={eventLabel(event.kind, event.step_key)}
              >
                {event.command_argv && event.command_argv.length > 0 && (
                  <Code block>{event.command_argv.join(" ")}</Code>
                )}
                {event.content && (
                  <Text size="sm" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
                    {event.content}
                  </Text>
                )}
              </Timeline.Item>
            ))}
          </Timeline>
        )}
      </Stack>
    </Card>
  );
}
