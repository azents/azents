"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Collapse,
  Divider,
  Group,
  Loader,
  Paper,
  rem,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconCircleCheck,
  IconClock,
  IconPlayerPlay,
  IconRefresh,
  IconTerminal2,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import type { SessionInitializationDetailState } from "../types";
import type {
  SessionInitializationEventResponse,
  SessionInitializationResponse,
  SessionInitializationStepResponse,
} from "@azents/public-client";

interface InitializationTimelineCardProps {
  initialization: SessionInitializationResponse;
  detailState: SessionInitializationDetailState;
  pendingInputCount: number;
  onLoadDetails: () => void;
  onDeletePendingInputs: () => void;
  onRetryInitialization?: (() => void) | null;
  onRetryCleanup?: (() => void) | null;
}

interface StepEvents {
  step: SessionInitializationStepResponse;
  events: SessionInitializationEventResponse[];
}

function noopAction(): void {}

function isActiveStatus(status: string): boolean {
  return status === "pending" || status === "running";
}

function isFailureStatus(status: string): boolean {
  return status === "failed" || status === "cleanup_required";
}

function initializationTone(status: string): "blue" | "green" | "red" | "gray" {
  if (status === "ready" || status === "cleaned") {
    return "green";
  }
  if (isFailureStatus(status) || status === "canceled") {
    return "red";
  }
  if (isActiveStatus(status)) {
    return "blue";
  }
  return "gray";
}

function stepTone(status: string): "blue" | "green" | "red" | "gray" {
  if (status === "completed" || status === "skipped") {
    return "green";
  }
  if (status === "failed" || status === "canceled") {
    return "red";
  }
  if (status === "pending" || status === "running") {
    return "blue";
  }
  return "gray";
}

function statusIcon(status: string): React.ReactElement {
  if (status === "ready" || status === "cleaned" || status === "completed") {
    return <IconCircleCheck size="1rem" />;
  }
  if (isFailureStatus(status) || status === "failed" || status === "canceled") {
    return <IconAlertTriangle size="1rem" />;
  }
  return <IconClock size="1rem" />;
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) =>
      part.length === 0 ? part : part.charAt(0).toUpperCase() + part.slice(1),
    )
    .join(" ");
}

function formatTimestamp(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function latestTimestamp(
  initialization: SessionInitializationResponse,
): string | null {
  return (
    formatTimestamp(initialization.failed_at) ??
    formatTimestamp(initialization.completed_at) ??
    formatTimestamp(initialization.started_at) ??
    formatTimestamp(initialization.updated_at)
  );
}

function eventContent(
  event: SessionInitializationEventResponse,
): string | null {
  const argv = event.command_argv?.join(" ") ?? null;
  if (event.content && argv) {
    return `${argv}\n${event.content}`;
  }
  return event.content ?? argv;
}

function sortEvents(
  events: SessionInitializationEventResponse[],
): SessionInitializationEventResponse[] {
  return [...events].sort((a, b) => a.sequence - b.sequence);
}

function groupEventsByStep(
  initialization: SessionInitializationResponse,
  events: SessionInitializationEventResponse[],
): StepEvents[] {
  const eventsByStepId = new Map<
    string,
    SessionInitializationEventResponse[]
  >();
  for (const event of events) {
    if (!event.step_id) {
      continue;
    }
    const current = eventsByStepId.get(event.step_id) ?? [];
    eventsByStepId.set(event.step_id, [...current, event]);
  }
  return initialization.steps
    .slice()
    .sort((a, b) => a.sequence - b.sequence)
    .map((step) => ({
      step,
      events: sortEvents(eventsByStepId.get(step.id) ?? []),
    }));
}

function StepDetail({ item }: { item: StepEvents }): React.ReactElement {
  const t = useTranslations("chat.initialization");
  const startedAt = formatTimestamp(item.step.started_at);
  const completedAt = formatTimestamp(item.step.completed_at);
  const failedAt = formatTimestamp(item.step.failed_at);

  return (
    <Paper p="sm" radius="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" gap="sm" align="flex-start">
          <Stack gap={rem(2)} style={{ minWidth: 0, flex: 1 }}>
            <Group gap="xs" wrap="nowrap">
              <Badge
                size="sm"
                variant="light"
                color={stepTone(item.step.status)}
              >
                {formatLabel(item.step.status)}
              </Badge>
              <Text fw={600} size="sm" truncate>
                {formatLabel(item.step.step_key)}
              </Text>
            </Group>
            <Text size="xs" c="dimmed">
              {formatLabel(item.step.step_type)} ·{" "}
              {t("attempt", { attempt: item.step.attempt })}
            </Text>
          </Stack>
          <Group gap={rem(4)}>
            {item.step.blocking && (
              <Badge size="xs" color="red" variant="light">
                {t("blocking")}
              </Badge>
            )}
            {item.step.retryable && (
              <Badge size="xs" color="blue" variant="light">
                {t("retryable")}
              </Badge>
            )}
          </Group>
        </Group>
        {(startedAt || completedAt || failedAt) && (
          <Text size="xs" c="dimmed">
            {[
              startedAt && t("startedAt", { value: startedAt }),
              completedAt && t("completedAt", { value: completedAt }),
              failedAt && t("failedAt", { value: failedAt }),
            ]
              .filter((value): value is string => typeof value === "string")
              .join(" · ")}
          </Text>
        )}
        {item.step.failure_reason && (
          <Alert
            color="red"
            variant="light"
            icon={<IconAlertTriangle size="1rem" />}
          >
            <Text size="sm">{item.step.failure_reason}</Text>
          </Alert>
        )}
        {item.events.length > 0 && (
          <Stack gap="xs">
            {item.events.map((event) => (
              <Paper
                key={event.id}
                p="xs"
                radius="sm"
                bg="var(--mantine-color-default-hover)"
              >
                <Stack gap={rem(6)}>
                  <Group gap="xs" justify="space-between">
                    <Badge
                      size="xs"
                      variant="outline"
                      color={
                        event.kind === "stderr" || event.kind === "failed"
                          ? "red"
                          : "gray"
                      }
                    >
                      {formatLabel(event.kind)}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      #{event.sequence}
                    </Text>
                  </Group>
                  {eventContent(event) && (
                    <Code
                      block
                      style={{ whiteSpace: "pre-wrap", fontSize: rem(12) }}
                    >
                      {eventContent(event)}
                    </Code>
                  )}
                  {typeof event.exit_code === "number" && (
                    <Text
                      size="xs"
                      c={event.exit_code === 0 ? "dimmed" : "red"}
                    >
                      {t("exitCode", { code: event.exit_code })}
                    </Text>
                  )}
                </Stack>
              </Paper>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

export function InitializationTimelineCard({
  initialization,
  detailState,
  pendingInputCount,
  onLoadDetails,
  onDeletePendingInputs,
  onRetryInitialization = null,
  onRetryCleanup = null,
}: InitializationTimelineCardProps): React.ReactElement {
  const t = useTranslations("chat.initialization");
  const [expanded, setExpanded] = useState(false);
  const tone = initializationTone(initialization.status);
  const steps = useMemo(
    () =>
      detailState.type === "READY"
        ? groupEventsByStep(initialization, detailState.events)
        : initialization.steps
            .slice()
            .sort((a, b) => a.sequence - b.sequence)
            .map((step) => ({ step, events: [] })),
    [detailState, initialization],
  );
  const failedSteps = initialization.steps.filter(
    (step) => step.status === "failed",
  );
  const hasRetryableFailure = failedSteps.some((step) => step.retryable);
  const timestamp = latestTimestamp(initialization);
  const progressText = t("progress", {
    completed: initialization.steps.filter(
      (step) => step.status === "completed",
    ).length,
    total: initialization.steps.length,
  });

  const handleToggleExpanded = (): void => {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    if (nextExpanded && detailState.type === "IDLE") {
      onLoadDetails();
    }
  };

  return (
    <Paper
      p="md"
      radius="lg"
      withBorder
      mb="md"
      style={{ borderColor: `var(--mantine-color-${tone}-outline)` }}
    >
      <Stack gap="sm">
        <Group justify="space-between" gap="sm" align="flex-start">
          <Group gap="sm" align="flex-start" style={{ minWidth: 0, flex: 1 }}>
            <ThemeIcon color={tone} variant="light" radius="xl">
              {statusIcon(initialization.status)}
            </ThemeIcon>
            <Stack gap={rem(3)} style={{ minWidth: 0, flex: 1 }}>
              <Group gap="xs" wrap="nowrap">
                <Text fw={700} size="sm" truncate>
                  {isActiveStatus(initialization.status)
                    ? t("preparingTitle")
                    : t("statusTitle")}
                </Text>
                <Badge size="sm" color={tone} variant="light">
                  {formatLabel(initialization.status)}
                </Badge>
              </Group>
              <Text size="sm" c="dimmed">
                {initialization.failure_summary ?? progressText}
              </Text>
              {timestamp && (
                <Text size="xs" c="dimmed">
                  {t("updatedAt", { value: timestamp })}
                </Text>
              )}
            </Stack>
          </Group>
          {initialization.status === "running" && (
            <Loader size="sm" color={tone} />
          )}
        </Group>

        {isFailureStatus(initialization.status) && (
          <Alert
            color="red"
            variant="light"
            icon={<IconAlertTriangle size="1rem" />}
          >
            <Text size="sm">
              {initialization.status === "cleanup_required"
                ? t("cleanupRequiredGuidance")
                : t("failureGuidance")}
            </Text>
          </Alert>
        )}

        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            leftSection={
              expanded ? (
                <IconChevronDown size="1rem" />
              ) : (
                <IconChevronRight size="1rem" />
              )
            }
            onClick={handleToggleExpanded}
          >
            {expanded ? t("hideDetails") : t("showDetails")}
          </Button>
          {expanded && (
            <Button
              size="xs"
              variant="subtle"
              leftSection={<IconRefresh size="1rem" />}
              loading={detailState.type === "LOADING"}
              onClick={onLoadDetails}
            >
              {t("refreshDetails")}
            </Button>
          )}
          {isFailureStatus(initialization.status) && hasRetryableFailure && (
            <Tooltip
              label={
                onRetryInitialization ? t("retrySetup") : t("retryUnavailable")
              }
              withArrow
            >
              <Button
                size="xs"
                variant="light"
                color="blue"
                leftSection={<IconPlayerPlay size="1rem" />}
                disabled={!onRetryInitialization}
                onClick={onRetryInitialization ?? noopAction}
              >
                {t("retrySetup")}
              </Button>
            </Tooltip>
          )}
          {initialization.status === "cleanup_required" && (
            <Tooltip
              label={
                onRetryCleanup
                  ? t("retryCleanup")
                  : t("cleanupRetryUnavailable")
              }
              withArrow
            >
              <Button
                size="xs"
                variant="light"
                color="red"
                leftSection={<IconTerminal2 size="1rem" />}
                disabled={!onRetryCleanup}
                onClick={onRetryCleanup ?? noopAction}
              >
                {t("retryCleanup")}
              </Button>
            </Tooltip>
          )}
          {pendingInputCount > 0 && isFailureStatus(initialization.status) && (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection={<IconTrash size="1rem" />}
              onClick={onDeletePendingInputs}
            >
              {t("deletePendingInputs", { count: pendingInputCount })}
            </Button>
          )}
        </Group>

        <Collapse expanded={expanded}>
          <Divider mb="sm" />
          {detailState.type === "LOADING" && (
            <Group gap="sm">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                {t("loadingDetails")}
              </Text>
            </Group>
          )}
          {detailState.type === "ERROR" && (
            <Alert
              color="red"
              variant="light"
              icon={<IconAlertTriangle size="1rem" />}
            >
              <Text size="sm">{t("detailLoadError")}</Text>
            </Alert>
          )}
          {(detailState.type === "READY" || detailState.type === "IDLE") && (
            <Stack gap="sm">
              <Group gap="xs">
                <Badge variant="outline" color="gray">
                  {progressText}
                </Badge>
                <Badge variant="outline" color="gray">
                  {t("retryCount", { count: initialization.retry_count })}
                </Badge>
              </Group>
              {steps.map((item) => (
                <StepDetail key={item.step.id} item={item} />
              ))}
              {detailState.type === "IDLE" && (
                <Box>
                  <Button size="xs" variant="subtle" onClick={onLoadDetails}>
                    {t("loadDurableEvents")}
                  </Button>
                </Box>
              )}
            </Stack>
          )}
        </Collapse>
      </Stack>
    </Paper>
  );
}
