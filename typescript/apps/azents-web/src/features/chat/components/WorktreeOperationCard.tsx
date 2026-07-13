"use client";

import {
  Accordion,
  Badge,
  Code,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronRight,
  IconGitBranch,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { WorktreeOperation, WorktreeOperationEvent } from "../types";

interface WorktreeOperationCardProps {
  operation: WorktreeOperation;
}

const WORKTREE_STEP_KEY = "create_git_worktree";

function statusColor(status: WorktreeOperation["execution"]["status"]): string {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "running":
      return "blue";
    case "pending":
      return "yellow";
  }
}

function statusIcon(
  status: WorktreeOperation["execution"]["status"],
): React.ReactElement {
  switch (status) {
    case "completed":
      return <IconCheck size={rem(16)} />;
    case "failed":
      return <IconAlertTriangle size={rem(16)} />;
    case "running":
      return <Loader size={rem(16)} />;
    case "pending":
      return <IconGitBranch size={rem(16)} />;
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

function commandEvent(
  events: WorktreeOperationEvent[],
): WorktreeOperationEvent | null {
  return (
    events.find(
      (event) =>
        event.kind === "command_started" &&
        event.step_key === WORKTREE_STEP_KEY &&
        event.command_argv !== null,
    ) ?? null
  );
}

function streamText(
  events: WorktreeOperationEvent[],
  kind: "stdout" | "stderr",
): string | null {
  const text = events
    .filter(
      (event) =>
        event.kind === kind &&
        (event.step_key === null || event.step_key === WORKTREE_STEP_KEY),
    )
    .map((event) => event.content ?? "")
    .join("");
  return text.length > 0 ? text : null;
}

function resultLabel(
  status: WorktreeOperation["execution"]["status"],
  t: ReturnType<typeof useTranslations<"chat.actionExecution">>,
): string {
  switch (status) {
    case "completed":
      return t("result.completed");
    case "failed":
      return t("result.failed");
    case "running":
      return t("result.running");
    case "pending":
      return t("result.pending");
  }
}

function DetailBlock({ children }: { children: string }): React.ReactElement {
  return (
    <ScrollArea.Autosize mah={rem(200)}>
      <Code block style={{ fontSize: rem(12), whiteSpace: "pre-wrap" }}>
        {children}
      </Code>
    </ScrollArea.Autosize>
  );
}

export function WorktreeOperationCard({
  operation,
}: WorktreeOperationCardProps): React.ReactElement {
  const t = useTranslations("chat.actionExecution");
  const [opened, setOpened] = useState<string | null>(null);
  const { execution, events } = operation;
  const command = commandEvent(events)?.command_argv ?? null;
  const stdout = streamText(events, "stdout");
  const stderr = streamText(events, "stderr");
  const isOpened = opened === execution.id;

  return (
    <Accordion
      variant="contained"
      my="xs"
      value={opened}
      onChange={setOpened}
      disableChevronRotation
      chevron={
        <IconChevronRight
          size={rem(16)}
          style={{
            transform: isOpened ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 120ms ease",
          }}
        />
      }
    >
      <Accordion.Item value={execution.id}>
        <Accordion.Control icon={statusIcon(execution.status)}>
          <Group gap="xs" wrap="nowrap">
            <Text size="sm" fw={500} truncate>
              {t("title")}
            </Text>
            <Badge
              size="xs"
              variant="light"
              color={statusColor(execution.status)}
            >
              {t(`status.${execution.status}`)}
            </Badge>
          </Group>
        </Accordion.Control>
        <Accordion.Panel>
          <Stack gap="xs">
            {command !== null ? (
              <Stack gap={rem(4)}>
                <Text size="xs" c="dimmed" fw={600}>
                  {t("command")}
                </Text>
                <DetailBlock>{commandLine(command)}</DetailBlock>
              </Stack>
            ) : null}
            {stdout !== null ? (
              <Stack gap={rem(4)}>
                <Text size="xs" c="dimmed" fw={600}>
                  {t("stdout")}
                </Text>
                <DetailBlock>{stdout}</DetailBlock>
              </Stack>
            ) : null}
            {stderr !== null ? (
              <Stack gap={rem(4)}>
                <Text size="xs" c="red" fw={600}>
                  {t("stderr")}
                </Text>
                <DetailBlock>{stderr}</DetailBlock>
              </Stack>
            ) : null}
            {execution.failure_summary !== null ? (
              <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap" }}>
                {execution.failure_summary}
              </Text>
            ) : null}
            <Text
              size="xs"
              fw={600}
              c={execution.status === "failed" ? "red" : "dimmed"}
            >
              {resultLabel(execution.status, t)}
            </Text>
          </Stack>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
