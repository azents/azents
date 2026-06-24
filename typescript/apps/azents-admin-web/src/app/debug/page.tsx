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
import { useState } from "react";

import { trpc } from "@/trpc/client";

type LogLevel = "warning" | "error" | "critical";

export default function DebugPage(): React.ReactElement {
  const [logLevel, setLogLevel] = useState<LogLevel>("error");
  const [logMessage, setLogMessage] = useState("Debug test log from admin web");
  const [exceptionMessage, setExceptionMessage] = useState(
    "Debug test exception from admin web",
  );

  const fireLog = trpc.debug.fireLog.useMutation();
  const fireException = trpc.debug.fireException.useMutation();

  return (
    <Stack gap="xl" p="md" maw={600}>
      <Title order={2}>Debug</Title>
      <Text c="dimmed">Sentry/Logging integration test</Text>

      {/* Fire Log */}
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
          onChange={(v) => {
            if (v) {
              setLogLevel(v);
            }
          }}
        />

        <TextInput
          label="Message"
          value={logMessage}
          onChange={(e) => setLogMessage(e.currentTarget.value)}
        />

        <Button
          leftSection={<IconSend size={16} />}
          onClick={() =>
            fireLog.mutate({ level: logLevel, message: logMessage })
          }
          loading={fireLog.isPending}
        >
          Fire Log
        </Button>

        {fireLog.isSuccess && (
          <Stack gap="xs">
            <Alert color="green" title="Fired">
              {fireLog.data.level.toUpperCase()}: {fireLog.data.message}
              {fireLog.data.sentry_event_id && (
                <>
                  <br />
                  Sentry Event ID: <Code>{fireLog.data.sentry_event_id}</Code>
                </>
              )}
              {!fireLog.data.sentry_event_id &&
                fireLog.data.level !== "warning" && (
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
                color={fireLog.data.sentry.initialized ? "green" : "red"}
                size="sm"
              >
                {fireLog.data.sentry.initialized
                  ? "initialized"
                  : "NOT initialized"}
              </Badge>
              <Badge
                color={fireLog.data.sentry.dsn_configured ? "green" : "red"}
                size="sm"
              >
                {fireLog.data.sentry.dsn_configured
                  ? "DSN configured"
                  : "NO DSN"}
              </Badge>
            </Group>
          </Stack>
        )}
        {fireLog.isError && (
          <Alert color="red" title="Error">
            {fireLog.error.message}
          </Alert>
        )}
      </Stack>

      {/* Fire Exception */}
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
          onChange={(e) => setExceptionMessage(e.currentTarget.value)}
        />

        <Button
          color="red"
          leftSection={<IconBug size={16} />}
          onClick={() => fireException.mutate({ message: exceptionMessage })}
          loading={fireException.isPending}
        >
          Fire Exception
        </Button>

        {fireException.isError && (
          <Alert color="green" title="Expected 500 Error">
            Server returned 500. Check Sentry for the event.
          </Alert>
        )}
      </Stack>
    </Stack>
  );
}
