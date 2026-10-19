"use client";

/**
 * MCP tool settings form fields.
 *
 * Handles MCP config such as server_url, auth_type, timeout,
 * and credentials(secret) input by auth_type.
 *
 * Layout composition:
 * - Required fields: server_url, auth_type
 * - credential fields by auth_type
 * - Connection test button
 * - Advanced settings (Accordion): timeout, header_name, token_url, auth_url, scopes, discovery_url
 */

import {
  Accordion,
  Alert,
  Button,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
} from "@mantine/core";
import { IconPlugConnected } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { projectMcpConfigFields } from "../containers/mcpConfigFieldsProjection";
import type { McpConfigFieldsViewProps } from "../containers/mcpConfigFieldsProjection";

const AUTH_TYPE_OPTIONS = ["none", "header", "bearer", "oauth2"] as const;

import type { McpConfigFieldsProps } from "../types";

export function McpConfigFields(
  props: McpConfigFieldsProps,
): React.ReactElement {
  return <McpConfigFieldsView {...projectMcpConfigFields(props)} />;
}

export function McpConfigFieldsView({
  configView,
  credentialsView,
  hasCredentials,
  testState,
  onTestConnection,
  canTest,
  onSetConfig: setConfig,
  onSetCredential: setCred,
  onAuthTypeChange: handleAuthTypeChange,
}: McpConfigFieldsViewProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.mcp");

  const testResult = testState.type === "RESULT" ? testState.result : null;
  const authType = configView.auth_type;
  const timeoutValue = configView.timeout;
  const serverUrl = configView.server_url;
  const isOAuth = authType === "oauth2";

  return (
    <Stack gap="sm">
      {/* Required fields */}
      <TextInput
        label={t("serverUrlLabel")}
        placeholder="https://mcp.example.com/sse"
        required
        value={serverUrl}
        onChange={(e) => setConfig("server_url", e.currentTarget.value)}
      />

      <Select
        label={t("authTypeLabel")}
        data={AUTH_TYPE_OPTIONS.map((v) => ({
          value: v,
          label: t(`authType_${v}`),
        }))}
        value={authType}
        onChange={handleAuthTypeChange}
      />

      {/* credential fields by auth_type */}
      {authType === "header" && (
        <>
          <TextInput
            label={t("headerNameLabel")}
            description={t("headerNameDescription")}
            placeholder="Authorization"
            required
            value={configView.header_name}
            onChange={(e) => setConfig("header_name", e.currentTarget.value)}
          />
          <PasswordInput
            label={t("headerValueLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={credentialsView.value}
            onChange={(e) => setCred("value", e.currentTarget.value)}
          />
        </>
      )}

      {authType === "bearer" && (
        <PasswordInput
          label={t("bearerTokenLabel")}
          placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
          value={credentialsView.token}
          onChange={(e) => setCred("token", e.currentTarget.value)}
        />
      )}

      {authType === "oauth2" && (
        <>
          <PasswordInput
            label={t("clientIdLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={credentialsView.client_id}
            onChange={(e) => setCred("client_id", e.currentTarget.value)}
          />
          <PasswordInput
            label={t("clientSecretLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={credentialsView.client_secret}
            onChange={(e) => setCred("client_secret", e.currentTarget.value)}
          />
        </>
      )}

      {hasCredentials && (
        <Text size="xs" c="dimmed">
          {t("credentialsSetHint")}
        </Text>
      )}

      {/* OAuth scopes */}
      {isOAuth && (
        <TagsInput
          label={t("scopesLabel")}
          placeholder={t("scopesPlaceholder")}
          splitChars={[",", " ", "\n"]}
          value={configView.scopes}
          onChange={(v) => setConfig("scopes", v)}
        />
      )}

      {/* Connection test */}
      {canTest && (
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={() => onTestConnection()}
          loading={testState.type === "TESTING"}
          w="fit-content"
        >
          {t("testConnection")}
        </Button>
      )}

      {testResult && (
        <Alert color={testResult.success ? "green" : "red"}>
          <Stack gap="xs">
            <Text size="sm">{testResult.message}</Text>
            {isOAuth && (
              <>
                {testResult.discoveredAuthUrl != null && (
                  <Text size="xs" c="dimmed">
                    {t("testConnectionDiscoverySuccess")}
                  </Text>
                )}
                {testResult.supportsDcr != null && (
                  <Text size="xs" c="dimmed">
                    {testResult.supportsDcr
                      ? t("testConnectionDcrSupported")
                      : t("testConnectionDcrNotSupported")}
                  </Text>
                )}
              </>
            )}
          </Stack>
        </Alert>
      )}

      {/* Advanced settings */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control>{t("advancedSettings")}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <NumberInput
                label={t("timeoutLabel")}
                description={t("timeoutDescription")}
                value={timeoutValue}
                onChange={(v) => setConfig("timeout", v)}
                min={1}
                max={300}
              />

              {/* header_name is promoted to Required fields for header auth — removed from Advanced settings */}

              {isOAuth && (
                <>
                  <TextInput
                    label={t("tokenUrlLabel")}
                    placeholder="https://auth.example.com/token"
                    value={configView.token_url}
                    onChange={(e) =>
                      setConfig("token_url", e.currentTarget.value)
                    }
                  />
                  <TextInput
                    label={t("authUrlLabel")}
                    placeholder="https://auth.example.com/authorize"
                    value={configView.auth_url}
                    onChange={(e) =>
                      setConfig("auth_url", e.currentTarget.value)
                    }
                  />
                  <TextInput
                    label={t("discoveryUrlLabel")}
                    description={t("discoveryUrlDescription")}
                    placeholder="https://auth.example.com/.well-known/oauth-authorization-server"
                    value={configView.discovery_url}
                    onChange={(e) =>
                      setConfig("discovery_url", e.currentTarget.value)
                    }
                  />
                </>
              )}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
