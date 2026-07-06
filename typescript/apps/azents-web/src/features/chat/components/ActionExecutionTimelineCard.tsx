"use client";

import { Badge, Box, Button, Group, rem, Stack, Text } from "@mantine/core";
import { IconAlertCircle, IconCheck, IconLoader2 } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ActionExecutionProjection } from "../types";
import type { ReactNode } from "react";

interface ActionExecutionTimelineCardProps {
  actionExecution: ActionExecutionProjection;
  onRetry: (actionExecutionId: string) => void;
  onDiscard: (actionExecutionId: string) => void;
}

type ActionExecutionEvent = ActionExecutionProjection["events"][number];

const GIT_WORKTREE_STEP_KEY = "create_git_worktree";

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

function shellQuote(argument: string): string {
  if (/^[A-Za-z0-9_/:=.,@%+-]+$/.test(argument)) {
    return argument;
  }
  return `'${argument.replaceAll("'", "'\\''")}'`;
}

function commandLine(commandArgv: string[]): string {
  return `$ ${commandArgv.map(shellQuote).join(" ")}`;
}

function commandStartedEvent(
  events: ActionExecutionEvent[],
): ActionExecutionEvent | null {
  return (
    events.find(
      (event) =>
        event.kind === "command_started" &&
        event.step_key === GIT_WORKTREE_STEP_KEY &&
        Array.isArray(event.command_argv) &&
        event.command_argv.length > 0,
    ) ?? null
  );
}

function commandCompletedEvent(
  events: ActionExecutionEvent[],
): ActionExecutionEvent | null {
  return (
    events.find(
      (event) =>
        event.kind === "command_completed" &&
        event.step_key === GIT_WORKTREE_STEP_KEY,
    ) ?? null
  );
}

function streamText(
  events: ActionExecutionEvent[],
  kind: "stdout" | "stderr",
): string | null {
  const text = events
    .filter(
      (event) =>
        event.kind === kind &&
        (event.step_key === null || event.step_key === GIT_WORKTREE_STEP_KEY) &&
        event.content,
    )
    .map((event) => event.content)
    .join("");
  return text.length > 0 ? text : null;
}

function commandArgumentAfter(
  commandArgv: string[] | null,
  flag: string,
): string | null {
  if (commandArgv === null) {
    return null;
  }
  const index = commandArgv.indexOf(flag);
  const value = commandArgv[index + 1];
  return index >= 0 && value ? value : null;
}

function worktreePath(commandArgv: string[] | null): string | null {
  if (commandArgv === null) {
    return null;
  }
  const branchFlagIndex = commandArgv.indexOf("-b");
  if (branchFlagIndex >= 0) {
    return commandArgv[branchFlagIndex + 2] ?? null;
  }
  const addIndex = commandArgv.indexOf("add");
  return addIndex >= 0 ? (commandArgv[addIndex + 1] ?? null) : null;
}

function startingRef(commandArgv: string[] | null): string | null {
  if (commandArgv === null || commandArgv.length === 0) {
    return null;
  }
  return commandArgv.at(-1) ?? null;
}

function isFailedStatus(status: string): boolean {
  return status === "failed" || status === "failed_final";
}

function resultLabel(
  actionExecution: ActionExecutionProjection,
  commandCompleted: ActionExecutionEvent | null,
  t: ReturnType<typeof useTranslations<"chat.actionExecution">>,
): string {
  const status = actionExecution.execution.status;
  if (status === "completed") {
    return t("result.completed");
  }
  if (isFailedStatus(status)) {
    return commandCompleted?.exit_code === 0
      ? t("result.registrationFailed")
      : t("result.failed");
  }
  if (status === "running") {
    return t("result.running");
  }
  return t("result.pending");
}

function TerminalBlock({
  children,
}: {
  children: ReactNode;
}): React.ReactElement {
  return (
    <Box
      component="pre"
      m={0}
      px="xs"
      py={rem(6)}
      style={{
        borderRadius: rem(6),
        background: "var(--mantine-color-default-hover)",
        color: "var(--mantine-color-dimmed)",
        fontFamily: "var(--mantine-font-family-monospace)",
        fontSize: rem(12),
        lineHeight: 1.45,
        overflowX: "auto",
        whiteSpace: "pre-wrap",
      }}
    >
      {children}
    </Box>
  );
}

export function ActionExecutionTimelineCard({
  actionExecution,
  onRetry,
  onDiscard,
}: ActionExecutionTimelineCardProps): React.ReactElement {
  const t = useTranslations("chat.actionExecution");
  const { execution, events } = actionExecution;
  const failed = execution.status === "failed";
  const color = statusColor(execution.status);
  const commandEvent = commandStartedEvent(events);
  const commandArgv = commandEvent?.command_argv ?? null;
  const commandCompleted = commandCompletedEvent(events);
  const stdout = streamText(events, "stdout");
  const stderr = streamText(events, "stderr");
  const branchName = commandArgumentAfter(commandArgv, "-b");
  const createdPath = worktreePath(commandArgv);
  const baseRef = startingRef(commandArgv);

  return (
    <Box
      my={rem(3)}
      pl="sm"
      py={rem(5)}
      style={{
        borderLeft: `${rem(2)} solid var(--mantine-color-${color}-6)`,
      }}
    >
      <Stack gap="xs">
        <Group justify="space-between" align="center" gap="xs" wrap="nowrap">
          <Group gap="xs" miw={0} wrap="nowrap">
            <Text size="xs" fw={700} c="dimmed" truncate>
              {t("title")}
            </Text>
            <Badge
              size="xs"
              color={color}
              variant="light"
              leftSection={statusIcon(execution.status)}
            >
              {statusLabel(execution.status, t)}
            </Badge>
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

        {commandArgv !== null ? (
          <Stack gap={rem(4)}>
            <Text size="xs" c="dimmed" fw={600}>
              {t("command")}
            </Text>
            <TerminalBlock>{commandLine(commandArgv)}</TerminalBlock>
          </Stack>
        ) : null}

        {stdout !== null ? (
          <Stack gap={rem(4)}>
            <Text size="xs" c="dimmed" fw={600}>
              {t("stdout")}
            </Text>
            <TerminalBlock>{stdout}</TerminalBlock>
          </Stack>
        ) : null}

        {stderr !== null ? (
          <Stack gap={rem(4)}>
            <Text
              size="xs"
              c={isFailedStatus(execution.status) ? "red" : "dimmed"}
              fw={600}
            >
              {t("stderr")}
            </Text>
            <TerminalBlock>{stderr}</TerminalBlock>
          </Stack>
        ) : null}

        {execution.failure_summary && isFailedStatus(execution.status) ? (
          <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap" }}>
            {execution.failure_summary}
          </Text>
        ) : null}

        {commandCompleted?.exit_code !== null &&
        typeof commandCompleted?.exit_code === "number" ? (
          <Text size="xs" c="dimmed">
            {t("exitCode", { code: commandCompleted.exit_code })}
          </Text>
        ) : null}

        <Stack gap={rem(2)}>
          <Text
            size="xs"
            c={isFailedStatus(execution.status) ? "red" : "dimmed"}
            fw={600}
          >
            {resultLabel(actionExecution, commandCompleted, t)}
          </Text>
          {execution.status === "completed" && createdPath !== null ? (
            <Text size="xs" c="dimmed" style={{ wordBreak: "break-all" }}>
              {t("projectRegistered", { path: createdPath })}
            </Text>
          ) : null}
          {branchName !== null ? (
            <Text size="xs" c="dimmed" style={{ wordBreak: "break-all" }}>
              {t("branch", { branch: branchName })}
            </Text>
          ) : null}
          {baseRef !== null ? (
            <Text size="xs" c="dimmed" style={{ wordBreak: "break-all" }}>
              {t("baseRef", { ref: baseRef })}
            </Text>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}
