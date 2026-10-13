"use client";

/**
 * Notion tool settings form fields.
 *
 * Notion MCP server URL and auth type are fixed on server (predefined),
 * so they are not exposed to user.
 */

import { Accordion, Button, NumberInput, Stack } from "@mantine/core";
import { IconPlugConnected, IconSettings } from "@tabler/icons-react";

import { ProviderConnectionTestFeedback } from "./ProviderConnectionTestFeedback";
import type { SimpleProviderFieldsProps } from "../types";

export function NotionConfigFields({
  config,
  onConfigChange,
  toolkitConfigId,
  testState,
  onTestConnection,
}: SimpleProviderFieldsProps): React.ReactElement {
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  // Connection test

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
            onClick={onTestConnection}
            loading={testState.type === "TESTING"}
            disabled={testState.type === "TESTING"}
          >
            Connection test
          </Button>

          <ProviderConnectionTestFeedback state={testState} preWrap={false} />
        </Stack>
      )}
    </Stack>
  );
}
