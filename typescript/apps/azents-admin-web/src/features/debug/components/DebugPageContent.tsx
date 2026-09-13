"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconBug, IconSend } from "@tabler/icons-react";

import type { DebugPageContainerOutput } from "../containers/useDebugPageContainer";

export function DebugPageContent({
  logLevel,
  logMessage,
  exceptionMessage,
  logState,
  exceptionState,
  onLogLevelChange,
  onLogMessageChange,
  onExceptionMessageChange,
  onFireLog,
  onFireException,
}: DebugPageContainerOutput): React.ReactElement {
  return (
    <Stack gap="xl" p="md" maw={600}>
      <Title order={2}>Debug</Title>
      <Text c="dimmed">Sentry/Logging integration test</Text>

      <Stack
        gap="sm"
        p="md"
        style={{
          border: "1px solid var(--mantine-color-default-border)",
          borderRadius: "var(--mantine-radius-md)",
        }}
      >
        <Group gap="xs">
          <IconSend size={20} />
          <Title order={4}>Fire Log</Title>
        </Group>
        <Text size="sm" c="dimmed">
          WARNING = Sentry breadcrumb / ERROR, CRITICAL = capture_message
        </Text>

        <Select
          label="Level"
          data={[
            { value: "warning", label: "WARNING (breadcrumb only)" },
            { value: "error", label: "ERROR (Sentry event)" },
            { value: "critical", label: "CRITICAL (Sentry event)" },
          ]}
          value={logLevel}
          onChange={onLogLevelChange}
        />

        <TextInput
          label="Message"
          value={logMessage}
          onChange={(event) => onLogMessageChange(event.currentTarget.value)}
        />

        <Button
          leftSection={<IconSend size={16} />}
          onClick={onFireLog}
          loading={logState.type === "SUBMITTING"}
        >
          Fire Log
        </Button>

        {logState.type === "SUCCESS" && (
          <Stack gap="xs">
            <Alert color="green" title="Fired">
              {logState.level.toUpperCase()}: {logState.message}
              {logState.sentryEventId && (
                <>
                  <br />
                  Sentry Event ID: <Code>{logState.sentryEventId}</Code>
                </>
              )}
              {!logState.sentryEventId && logState.level !== "warning" && (
                <>
                  <br />
                  Sentry Event ID: <Code>None</Code> (not sent)
                </>
              )}
            </Alert>
            <Group gap="xs">
              <Text size="sm" fw={500}>
                Sentry SDK:
              </Text>
              <Badge
                color={logState.sentryInitialized ? "green" : "red"}
                size="sm"
              >
                {logState.sentryInitialized ? "initialized" : "NOT initialized"}
              </Badge>
              <Badge
                color={logState.sentryDsnConfigured ? "green" : "red"}
                size="sm"
              >
                {logState.sentryDsnConfigured ? "DSN configured" : "NO DSN"}
              </Badge>
            </Group>
          </Stack>
        )}
        {logState.type === "ERROR" && (
          <Alert color="red" title="Error">
            {logState.message}
          </Alert>
        )}
      </Stack>

      <Stack
        gap="sm"
        p="md"
        style={{
          border: "1px solid var(--mantine-color-default-border)",
          borderRadius: "var(--mantine-radius-md)",
        }}
      >
        <Group gap="xs">
          <IconBug size={20} />
          <Title order={4}>Fire Exception</Title>
        </Group>
        <Text size="sm" c="dimmed">
          Unhandled RuntimeError raise (500) + Sentry event with stacktrace
        </Text>

        <Alert
          color="yellow"
          icon={<IconAlertTriangle size={16} />}
          title="Warning"
        >
          500 Internal Server Error
        </Alert>

        <TextInput
          label="Message"
          value={exceptionMessage}
          onChange={(event) =>
            onExceptionMessageChange(event.currentTarget.value)
          }
        />

        <Button
          color="red"
          leftSection={<IconBug size={16} />}
          onClick={onFireException}
          loading={exceptionState.type === "SUBMITTING"}
        >
          Fire Exception
        </Button>

        {exceptionState.type === "EXPECTED_ERROR" && (
          <Alert color="green" title="Expected 500 Error">
            Server returned 500. Check Sentry for the event.
          </Alert>
        )}
      </Stack>
    </Stack>
  );
}
