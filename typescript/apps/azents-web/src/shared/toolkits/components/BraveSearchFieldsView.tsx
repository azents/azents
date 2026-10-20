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

import type {
  BraveFieldCallbacks,
  BraveFormFields,
} from "../provider-form-fields";
import type { BraveSearchTestState } from "../types";

export interface BraveSearchFieldsViewProps extends BraveFieldCallbacks {
  fields: BraveFormFields;
  hasCredentials: boolean;
  replacingKey: boolean;
  onReplaceKey: () => void;
  onTestConnection: () => void;
  testState: BraveSearchTestState;
}

export function BraveSearchFieldsView({
  fields,
  onApiKeyChange,
  onCountryChange,
  onLanguageChange,
  onSafesearchChange,
  onTimeoutChange,
  hasCredentials,
  replacingKey,
  onReplaceKey,
  onTestConnection,
  testState,
}: BraveSearchFieldsViewProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.braveSearch");
  const { apiKey: key, country, language, safesearch, timeout } = fields;
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
          onChange={(event) => onApiKeyChange(event.currentTarget.value)}
        />
      )}

      <TextInput
        label={t("country")}
        description={t("countryHint")}
        value={country}
        maxLength={3}
        onChange={(event) => onCountryChange(event.currentTarget.value)}
      />
      <TextInput
        label={t("language")}
        description={t("languageHint")}
        value={language}
        maxLength={5}
        onChange={(event) => onLanguageChange(event.currentTarget.value)}
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
        onChange={onSafesearchChange}
      />
      <NumberInput
        label={t("timeout")}
        min={1}
        max={30}
        value={timeout}
        onChange={onTimeoutChange}
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
