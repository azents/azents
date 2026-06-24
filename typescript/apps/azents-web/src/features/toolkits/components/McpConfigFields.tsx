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
import { useState } from "react";
import { trpc } from "@/trpc/client";

type McpConfig = Record<string, unknown>;
type McpCredentials = Record<string, unknown> | null;

const AUTH_TYPE_OPTIONS = ["none", "header", "bearer", "oauth2"] as const;

interface McpConfigFieldsProps {
  config: McpConfig;
  onConfigChange: (config: McpConfig) => void;
  credentials: McpCredentials;
  onCredentialsChange: (credentials: McpCredentials) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
  /** Workspace handle for connection test API call */
  handle?: string;
  /** Stored toolkit ID (edit mode) */
  toolkitConfigId?: string;
}

/** Connection test result type */
interface TestResult {
  success: boolean;
  message: string;
  discoveredAuthUrl?: string;
  discoveredTokenUrl?: string;
  supportsDcr?: boolean;
}

export function McpConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  handle,
  toolkitConfigId,
}: McpConfigFieldsProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.mcp");

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  /** Connection test: common for all auth types */
  const handleTestConnection = async (): Promise<void> => {
    if (!handle) {
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const result = await testConnectionMutation.mutateAsync({
        handle,
        toolkitType: "mcp",
        toolkitConfigId: toolkitConfigId ?? null,
        config,
        credentials,
      });

      const nextResult: TestResult = {
        success: result.success,
        message: result.success
          ? t("testConnectionSuccess")
          : t("testConnectionFailed", { message: result.message }),
      };
      if (result.discovered_auth_url != null) {
        nextResult.discoveredAuthUrl = result.discovered_auth_url;
      }
      if (result.discovered_token_url != null) {
        nextResult.discoveredTokenUrl = result.discovered_token_url;
      }
      if (result.supports_dcr != null) {
        nextResult.supportsDcr = result.supports_dcr;
      }
      setTestResult(nextResult);
    } catch (error) {
      setTestResult({
        success: false,
        message: t("testConnectionFailed", {
          message: error instanceof Error ? error.message : "Unknown error",
        }),
      });
    } finally {
      setTesting(false);
    }
  };

  const authType = (config.auth_type as string) || "none";

  const setConfig = (key: string, value: unknown): void => {
    onConfigChange({ ...config, [key]: value });
  };

  const setCred = (key: string, value: unknown): void => {
    onCredentialsChange({ ...(credentials ?? {}), [key]: value });
  };

  const handleAuthTypeChange = (value: string | null): void => {
    const newType = value ?? "none";
    onConfigChange({
      ...config,
      auth_type: newType,
    });

    if (newType === "oauth2") {
      onCredentialsChange(null);
    } else {
      // Synchronize credentials discriminator
      onCredentialsChange({ type: newType });
    }
  };

  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;
  const serverUrl = (config.server_url as string) || "";
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
            value={(config.header_name as string) || ""}
            onChange={(e) => setConfig("header_name", e.currentTarget.value)}
          />
          <PasswordInput
            label={t("headerValueLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={(credentials?.value as string) || ""}
            onChange={(e) => setCred("value", e.currentTarget.value)}
          />
        </>
      )}

      {authType === "bearer" && (
        <PasswordInput
          label={t("bearerTokenLabel")}
          placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
          value={(credentials?.token as string) || ""}
          onChange={(e) => setCred("token", e.currentTarget.value)}
        />
      )}

      {authType === "oauth2" && (
        <>
          <PasswordInput
            label={t("clientIdLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={(credentials?.client_id as string) || ""}
            onChange={(e) => setCred("client_id", e.currentTarget.value)}
          />
          <PasswordInput
            label={t("clientSecretLabel")}
            placeholder={hasCredentials ? t("credentialsEditPlaceholder") : ""}
            value={(credentials?.client_secret as string) || ""}
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
          value={
            Array.isArray(config.scopes) ? (config.scopes as string[]) : []
          }
          onChange={(v) => setConfig("scopes", v)}
        />
      )}

      {/* Connection test */}
      {serverUrl && handle && (
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={() => void handleTestConnection()}
          loading={testing}
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
                    value={(config.token_url as string) || ""}
                    onChange={(e) =>
                      setConfig("token_url", e.currentTarget.value)
                    }
                  />
                  <TextInput
                    label={t("authUrlLabel")}
                    placeholder="https://auth.example.com/authorize"
                    value={(config.auth_url as string) || ""}
                    onChange={(e) =>
                      setConfig("auth_url", e.currentTarget.value)
                    }
                  />
                  <TextInput
                    label={t("discoveryUrlLabel")}
                    description={t("discoveryUrlDescription")}
                    placeholder="https://auth.example.com/.well-known/oauth-authorization-server"
                    value={(config.discovery_url as string) || ""}
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
