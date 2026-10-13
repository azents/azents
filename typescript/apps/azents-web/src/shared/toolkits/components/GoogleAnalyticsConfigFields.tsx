"use client";

/**
 * Google Analytics Toolkit settings form fields.
 *
 * GA4 MCP server connection settings. Simpler than GCP/AWS.
 * Includes runtime wait time guidance.
 */

import {
  Accordion,
  Alert,
  Button,
  Code,
  FileInput,
  Group,
  NumberInput,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  IconBrandGoogleAnalytics,
  IconInfoCircle,
  IconPlugConnected,
  IconSettings,
  IconUpload,
} from "@tabler/icons-react";
import { useCallback, useMemo } from "react";
import { getOptionalString, parseJsonRecord } from "@/shared/lib/unknown-value";
import { getServiceAccountKey } from "../service-account-fields";
import { ProviderConnectionTestFeedback } from "./ProviderConnectionTestFeedback";
import type { ServiceAccountProviderFieldsProps } from "../types";

export function GoogleAnalyticsConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  testState,
  onTestConnection,
  showKeyInput,
  onShowKeyInput,
  onKeyFileUpload,
}: ServiceAccountProviderFieldsProps): React.ReactElement {
  const propertyId =
    typeof config.default_property_id === "string"
      ? config.default_property_id
      : "";
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  const clientEmail = useMemo(() => {
    if (!credentials) {
      return null;
    }
    const serviceAccountKey = getServiceAccountKey(
      credentials.service_account_key,
    );
    return serviceAccountKey
      ? (getOptionalString(serviceAccountKey.client_email) ?? null)
      : null;
  }, [credentials]);

  const handleKeyPaste = useCallback(
    (value: string): void => {
      if (!value.trim()) {
        onCredentialsChange(null);
        return;
      }
      const serviceAccountKey = getServiceAccountKey(parseJsonRecord(value));
      if (serviceAccountKey) {
        onCredentialsChange({ service_account_key: serviceAccountKey });
      }
    },
    [onCredentialsChange],
  );

  return (
    <Stack gap="md">
      {/* Property ID */}
      <TextInput
        label="Default Property ID"
        description="GA4 property ID (optional). Leave empty to auto-discover."
        placeholder="123456789"
        value={propertyId}
        onChange={(e) =>
          onConfigChange({
            ...config,
            default_property_id: e.currentTarget.value || null,
          })
        }
      />

      {/* SA Key */}
      <Stack gap="xs">
        <Text fw={500} size="sm">
          Service Account Key
          <Text span c="red" ml={4}>
            *
          </Text>
        </Text>

        {clientEmail && !showKeyInput ? (
          <Alert
            variant="light"
            color="blue"
            icon={<IconBrandGoogleAnalytics size={16} />}
          >
            <Group justify="space-between" align="center">
              <Text size="sm">
                Authenticated as <Code>{clientEmail}</Code>
              </Text>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => onShowKeyInput()}
              >
                Replace Key
              </Button>
            </Group>
          </Alert>
        ) : (
          <Stack gap="xs">
            <Textarea
              placeholder='Paste Service Account Key JSON ({"type": "service_account", ...})'
              minRows={4}
              maxRows={8}
              autosize
              onChange={(e) => handleKeyPaste(e.currentTarget.value)}
            />
            <FileInput
              placeholder="Or upload .json file"
              accept=".json"
              leftSection={<IconUpload size={16} />}
              onChange={onKeyFileUpload}
            />
          </Stack>
        )}
      </Stack>

      {/* Setup guide */}
      <Alert
        variant="light"
        color="blue"
        icon={<IconInfoCircle size={16} />}
        title="Required Setup"
      >
        <Stack gap={4}>
          <Text size="xs" fw={600}>
            1. Enable API in GCP Console:
          </Text>
          <Text size="xs" ml="sm">
            Google Analytics Data API + Google Analytics Admin API
          </Text>
          <Text size="xs" fw={600} mt="xs">
            2. GA4 Grant SA access to property:
          </Text>
          <Text size="xs" ml="sm">
            GA4 Admin → Property Access Management → Add SA email as Viewer
          </Text>
        </Stack>
      </Alert>

      {/* Runtime wait notice */}
      <Alert variant="light" color="yellow" icon={<IconInfoCircle size={16} />}>
        <Text size="xs">
          This tool requires an agent runtime to run. The first session may take
          up to 30 seconds to start. Subsequent sessions will be instant while
          the runtime is active.
        </Text>
      </Alert>

      {/* Connection Test */}
      <Stack gap="xs">
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={onTestConnection}
          loading={testState.type === "TESTING"}
          disabled={!credentials && !hasCredentials}
        >
          Test Connection
        </Button>

        <ProviderConnectionTestFeedback state={testState} preWrap />
      </Stack>

      {/* Advanced */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced Settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="MCP tool call timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
