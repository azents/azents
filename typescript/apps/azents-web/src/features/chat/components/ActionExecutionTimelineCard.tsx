"use client";

import { Badge, Box, Group, rem, Stack, Text } from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconLoader2,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ActionExecutionProjection } from "../types";
import type { ReactNode } from "react";

interface ActionExecutionTimelineCardProps {
  actionExecution: ActionExecutionProjection;
}

type ActionExecutionEvent = ActionExecutionProjection["events"][number];

const GIT_WORKTREE_STEP_KEY = "create_git_worktree";

interface CleanupCandidate {
  path: string;
  outcome: string;
  reason_code: string | null;
  summary: string | null;
}

interface CleanupResult {
  phase: string;
  examined_count: number;
  protected_count: number;
  removed_count: number;
  already_absent_count: number;
  failed_count: number;
  unresolved_count: number;
  candidates: CleanupCandidate[];
}

function statusColor(status: string): string {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "cancelled":
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
      return <IconCheck size={rem(14)} />;
    case "failed":
      return <IconAlertCircle size={rem(14)} />;
    case "cancelled":
      return <IconX size={rem(14)} />;
    default:
      return <IconLoader2 size={rem(14)} />;
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
    case "cancelled":
      return t("status.cancelled");
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
  return status === "failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberField(value: Record<string, unknown>, key: string): number {
  const field = value[key];
  return typeof field === "number" ? field : 0;
}

function cleanupResult(value: unknown): CleanupResult | null {
  if (!isRecord(value)) {
    return null;
  }
  const candidates = Array.isArray(value.candidates)
    ? value.candidates.flatMap((candidate) => {
        if (
          !isRecord(candidate) ||
          typeof candidate.path !== "string" ||
          typeof candidate.outcome !== "string"
        ) {
          return [];
        }
        return [
          {
            path: candidate.path,
            outcome: candidate.outcome,
            reason_code:
              typeof candidate.reason_code === "string"
                ? candidate.reason_code
                : null,
            summary:
              typeof candidate.summary === "string" ? candidate.summary : null,
          },
        ];
      })
    : [];
  return {
    phase: typeof value.phase === "string" ? value.phase : "pending",
    examined_count: numberField(value, "examined_count"),
    protected_count: numberField(value, "protected_count"),
    removed_count: numberField(value, "removed_count"),
    already_absent_count: numberField(value, "already_absent_count"),
    failed_count: numberField(value, "failed_count"),
    unresolved_count: numberField(value, "unresolved_count"),
    candidates,
  };
}

function cleanupOutcomeColor(outcome: string): string {
  switch (outcome) {
    case "removed":
      return "green";
    case "already_absent":
    case "protected":
      return "blue";
    case "failed":
      return "red";
    default:
      return "yellow";
  }
}

function CleanupActionExecutionTimelineCard({
  actionExecution,
  t,
}: {
  actionExecution: ActionExecutionProjection;
  t: ReturnType<typeof useTranslations<"chat.actionExecution">>;
}): React.ReactElement {
  const { execution, events } = actionExecution;
  const result = cleanupResult(execution.result);
  const color = statusColor(execution.status);
  const latestEvent = events.at(-1);

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
          <Text size="xs" fw={700} c="dimmed" truncate>
            {t("cleanup.title")}
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

        <Text size="xs" c="dimmed">
          {t("cleanup.phase", { phase: result?.phase ?? "pending" })}
        </Text>

        {result !== null ? (
          <Group gap="xs">
            <Badge size="xs" variant="light">
              {t("cleanup.examined", { count: result.examined_count })}
            </Badge>
            <Badge size="xs" color="green" variant="light">
              {t("cleanup.removed", { count: result.removed_count })}
            </Badge>
            <Badge size="xs" color="blue" variant="light">
              {t("cleanup.protected", { count: result.protected_count })}
            </Badge>
            {result.already_absent_count > 0 ? (
              <Badge size="xs" color="blue" variant="light">
                {t("cleanup.alreadyAbsent", {
                  count: result.already_absent_count,
                })}
              </Badge>
            ) : null}
            {result.failed_count > 0 || result.unresolved_count > 0 ? (
              <Badge size="xs" color="red" variant="light">
                {t("cleanup.attention", {
                  count: result.failed_count + result.unresolved_count,
                })}
              </Badge>
            ) : null}
          </Group>
        ) : null}

        {latestEvent?.content ? (
          <Text size="xs" c="dimmed">
            {latestEvent.content}
          </Text>
        ) : null}

        {result?.candidates.map((candidate) => (
          <Box
            key={`${candidate.path}:${candidate.outcome}`}
            px="xs"
            py={rem(5)}
            style={{
              borderRadius: rem(6),
              background: "var(--mantine-color-default-hover)",
            }}
          >
            <Group
              justify="space-between"
              align="flex-start"
              gap="xs"
              wrap="nowrap"
            >
              <Text
                size="xs"
                c="dimmed"
                style={{ wordBreak: "break-all", minWidth: 0 }}
              >
                {candidate.path}
              </Text>
              <Badge
                size="xs"
                color={cleanupOutcomeColor(candidate.outcome)}
                variant="light"
              >
                {candidate.outcome}
              </Badge>
            </Group>
            {(candidate.summary ?? candidate.reason_code) ? (
              <Text size="xs" c="dimmed" mt={rem(3)}>
                {candidate.summary ?? candidate.reason_code}
              </Text>
            ) : null}
          </Box>
        ))}

        {execution.failure_summary && isFailedStatus(execution.status) ? (
          <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap" }}>
            {execution.failure_summary}
          </Text>
        ) : null}
        {execution.cancellation_summary && execution.status === "cancelled" ? (
          <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
            {execution.cancellation_summary}
          </Text>
        ) : null}
      </Stack>
    </Box>
  );
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
  if (status === "cancelled") {
    return t("result.cancelled");
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
}: ActionExecutionTimelineCardProps): React.ReactElement {
  const t = useTranslations("chat.actionExecution");
  const { execution, events } = actionExecution;
  if (execution.action_type === "cleanup_orphan_git_worktrees") {
    return (
      <CleanupActionExecutionTimelineCard
        actionExecution={actionExecution}
        t={t}
      />
    );
  }
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

        {execution.cancellation_summary && execution.status === "cancelled" ? (
          <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
            {execution.cancellation_summary}
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
