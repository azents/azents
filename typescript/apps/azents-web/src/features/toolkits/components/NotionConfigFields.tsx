"use client";

/**
 * Notion tool settings form fields.
 *
 * Notion MCP server URL and auth type are fixed on server (predefined),
 * so they are not exposed to user.
 */

import { Accordion, Alert, Button, NumberInput, Stack } from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconPlugConnected,
  IconSettings,
} from "@tabler/icons-react";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";

type NotionConfig = Record<string, unknown>;
type NotionCredentials = Record<string, unknown> | null;

interface NotionConfigFieldsProps {
  config: NotionConfig;
  onConfigChange: (config: NotionConfig) => void;
  credentials: NotionCredentials;
  onCredentialsChange: (credentials: NotionCredentials) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
  handle: string;
  /** Existing toolkit config ID in edit mode */
  toolkitConfigId?: string;
}

export function NotionConfigFields({
  config,
  onConfigChange,
  credentials,
  handle,
  toolkitConfigId,
}: NotionConfigFieldsProps): React.ReactElement {
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  // Connection test
  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  const handleTestConnection = useCallback(() => {
    testConnectionMutation.mutate({
      handle,
      toolkitType: "notion",
      toolkitConfigId: toolkitConfigId ?? null,
      config,
      credentials,
    });
  }, [handle, toolkitConfigId, config, credentials, testConnectionMutation]);

  return (
    <Stack gap="md">
      {/* Advanced settings */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="MCP request timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      {/* Connection test */}
      {toolkitConfigId && (
        <Stack gap="xs">
          <Button
            variant="light"
            leftSection={<IconPlugConnected size={16} />}
            onClick={handleTestConnection}
            loading={testConnectionMutation.isPending}
            disabled={testConnectionMutation.isPending}
          >
            Connection test
          </Button>

          {testConnectionMutation.isSuccess && (
            <Alert
              variant="light"
              color={testConnectionMutation.data.success ? "green" : "red"}
              icon={
                testConnectionMutation.data.success ? (
                  <IconCheck size={16} />
                ) : (
                  <IconAlertTriangle size={16} />
                )
              }
            >
              {testConnectionMutation.data.message}
            </Alert>
          )}
        </Stack>
      )}
    </Stack>
  );
}
