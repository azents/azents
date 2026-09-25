"use client";

/** Pure Brave Search settings and explicit quota-bearing connection test view. */

import {
  Alert,
  Button,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";

export interface BraveSearchFieldsViewProps {
  config: Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  credentials: Record<string, unknown> | null;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  hasCredentials: boolean;
  replacingKey: boolean;
  onReplaceKey: () => void;
  onTestConnection: () => void;
  testState:
    | { type: "IDLE" }
    | { type: "TESTING" }
    | { type: "SUCCESS"; message: string }
    | { type: "FAILURE"; message: string };
}

export function BraveSearchFieldsView({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  replacingKey,
  onReplaceKey,
  onTestConnection,
  testState,
}: BraveSearchFieldsViewProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.braveSearch");
  const key =
    typeof credentials?.api_key === "string" ? credentials.api_key : "";
  const country = typeof config.country === "string" ? config.country : "US";
  const language =
    typeof config.search_lang === "string" ? config.search_lang : "en";
  const safesearch =
    typeof config.safesearch === "string" ? config.safesearch : "strict";
  const timeout = typeof config.timeout === "number" ? config.timeout : 10;
  const testFeedback = (() => {
    switch (testState.type) {
      case "IDLE":
      case "TESTING":
        return null;
      case "SUCCESS":
        return <Alert color="green">{testState.message}</Alert>;
      case "FAILURE":
        return <Alert color="red">{testState.message}</Alert>;
    }
  })();

  return (
    <Stack gap="md">
      {hasCredentials && !replacingKey && !key ? (
        <Stack gap="xs">
          <Text size="sm">{t("keyConfigured")}</Text>
          <Button
            type="button"
            size="xs"
            variant="light"
            onClick={onReplaceKey}
          >
            {t("replaceKey")}
          </Button>
        </Stack>
      ) : (
        <PasswordInput
          label={t("apiKey")}
          description={hasCredentials ? t("keepKey") : t("apiKeyRequired")}
          autoComplete="new-password"
          required={!hasCredentials}
          value={key}
          onChange={(event) => {
            const value = event.currentTarget.value;
            onCredentialsChange(value ? { api_key: value } : null);
          }}
        />
      )}

      <TextInput
        label={t("country")}
        description={t("countryHint")}
        value={country}
        maxLength={3}
        onChange={(event) =>
          onConfigChange({
            ...config,
            country: event.currentTarget.value.toUpperCase(),
          })
        }
      />
      <TextInput
        label={t("language")}
        description={t("languageHint")}
        value={language}
        maxLength={5}
        onChange={(event) =>
          onConfigChange({
            ...config,
            search_lang: event.currentTarget.value.toLowerCase(),
          })
        }
      />
      <Select
        label={t("safeSearch")}
        value={safesearch}
        allowDeselect={false}
        data={[
          { value: "strict", label: t("strict") },
          { value: "moderate", label: t("moderate") },
          { value: "off", label: t("off") },
        ]}
        onChange={(value) =>
          onConfigChange({ ...config, safesearch: value ?? "strict" })
        }
      />
      <NumberInput
        label={t("timeout")}
        min={1}
        max={30}
        value={timeout}
        onChange={(value) => onConfigChange({ ...config, timeout: value })}
      />

      <Stack gap="xs">
        <Text size="xs" c="dimmed">
          {t("testQuotaHint")}
        </Text>
        <Button
          type="button"
          variant="light"
          disabled={(!key && !hasCredentials) || testState.type === "TESTING"}
          loading={testState.type === "TESTING"}
          onClick={onTestConnection}
        >
          {t("testConnection")}
        </Button>
        {testFeedback}
      </Stack>
    </Stack>
  );
}
